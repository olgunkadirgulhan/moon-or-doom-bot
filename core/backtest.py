"""Backtest: botun geçmişte her 4 saatte bir ne diyeceğini, SADECE o ana kadar kapanmış mumlarla yeniden üretir.

Canlı kodun aynısı kullanılır (levels, signal.features/_plan, scanner._rank, strategy.select, tracker._simulate,
tracker.account). Geleceğe bakma yok: her adımda seviyeler/indikatörler yalnızca kapanmış mumlardan hesaplanır;
swing noktası, sağındaki n mum kapandıktan sonra kullanılır (canlıdaki gibi).

Veri: Binance 15 dk mumları (data/bt/ altında önbelleklenir); 1h/4h/8h/1d bunlardan türetilir, işlem sonuçları
15 dk mumlarla simüle edilir. Dönemin ilk %60'ı "eğitim" (ayar seçimi), son %40'ı "test" (hiç dokunulmamış).
"""
import asyncio
import itertools
import logging
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from core import ROOT, data, levels, scanner, signal, strategy, tracker
from core.indicators import add_indicators, last_atr

log = logging.getLogger(__name__)
CACHE = ROOT / "data" / "bt"
TFS = {"1h": "1h", "4h": "4h", "8h": "8h", "1d": "24h"}  # epoch kökenli → UTC gün sınırı (Binance ile aynı)
TF_SEC = {"1h": 3600, "4h": 14400, "8h": 28800, "1d": 86400}
AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
WINDOW = 300          # canlıdaki LIMIT ile aynı
STEP = 4 * 3600       # canlı rapor sıklığı
MIN_BARS = scanner.MIN_BARS
LIMIT_FILL_H = 12     # limit emrin geçerlilik süresi
IS_SHARE = 0.6        # eğitim payı


# ---------- veri ----------

async def fetch_15m(symbol: str, days: int) -> pd.DataFrame:
    path = CACHE / f"{symbol}_15m.pkl"
    since = int((time.time() - days * 86400) * 1000)
    if path.exists() and time.time() - path.stat().st_mtime < 86400:
        df = pd.read_pickle(path)
        meta = CACHE / f"{symbol}_15m.since"
        # önbellek istenen başlangıcı kapsıyorsa kullan (coin daha yeni listelendiyse de kapsar sayılır)
        if meta.exists() and int(meta.read_text()) <= since + 86_400_000:
            return df
    ex, rows = data.exchange(), []
    cursor = since
    while True:
        batch = await ex.fetch_ohlcv(f"{symbol}/USDT", "15m", since=cursor, limit=1000)
        if not batch:
            break
        rows += batch
        cursor = batch[-1][0] + 900_000
        if len(batch) < 1000:
            break
    df = data._to_df(rows)
    df = df[~df.index.duplicated()].iloc[:-1]  # son (kapanmamış) mum hariç
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_pickle(path)
    (CACHE / f"{symbol}_15m.since").write_text(str(since))
    return df


def _frames(m15: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {}
    for tf, rule in TFS.items():
        df = m15.resample(rule, label="left", closed="left", origin="epoch").agg(AGG).dropna(subset=["Close"])
        out[tf] = add_indicators(df)
    return out


def _swings(df: pd.DataFrame, n: int) -> tuple[np.ndarray, np.ndarray]:
    w = 2 * n + 1
    hi = (df["High"].rolling(w, center=True).max() == df["High"]).to_numpy()
    lo = (df["Low"].rolling(w, center=True).min() == df["Low"]).to_numpy()
    return hi, lo


# ---------- anlık görüntüler (her adım × coin) ----------

def _snapshots(args) -> list[dict]:
    """Bir coin için tüm adımların özellikleri + market/limit planları (ayrı süreçte çalışır)."""
    symbol, m15, steps = args
    frames = _frames(m15)
    ends = {tf: df.index.as_unit("s").asi8 + TF_SEC[tf] for tf, df in frames.items()}  # mum kapanış anı
    swings = {tf: _swings(df, levels.FRACTAL[tf]) for tf, df in frames.items()}
    close15 = m15["Close"].to_numpy()
    t15 = m15.index.as_unit("s").asi8
    out = []
    for T in steps:
        ks = {tf: int(np.searchsorted(ends[tf], T, side="right")) for tf in TFS}
        if min(ks.values()) < MIN_BARS:
            continue
        win = {}
        for tf, k in ks.items():
            win[tf] = frames[tf].iloc[max(0, k - WINDOW):k]
        price = float(win["1h"]["Close"].iloc[-1])
        lv = {}
        for tf, k in ks.items():
            start, n = max(0, k - WINDOW), levels.FRACTAL[tf]
            hi, lo = swings[tf]
            df = win[tf]
            hs = np.flatnonzero(hi[start + n:k - n]) + n
            ls = np.flatnonzero(lo[start + n:k - n]) + n
            H, L = df["High"].to_numpy(), df["Low"].to_numpy()
            pts = [(H[i], i) for i in hs] + [(L[i], i) for i in ls]
            lv[tf] = levels.compute_levels(df, tf, price, pts)
        levels.annotate_confluence(lv, 0.5 * last_atr(win["4h"]))
        f = signal.features(win, lv)
        sup, res, atr = f["supports"], f["resistances"], f["atr"]
        # 24 saat sonraki fiyat (bileşen tahmin gücü analizi için)
        j = int(np.searchsorted(t15, T + 86400, side="left"))
        fwd = (close15[j - 1] - price) / atr if j < len(close15) and atr else np.nan
        out.append({
            "ts": T, "symbol": symbol, "price": price, "atr": atr, "components": f["components"], "fwd_atr": fwd,
            "plans_market": {s: signal._plan(s, price, sup, res, atr) for s in ("long", "short")},
            "plans_limit": {s: signal._plan_limit(s, price, sup, res, atr) for s in ("long", "short")},
        })
    return out


# ---------- varyant çalıştırma ----------

def _candles(m15_arr: dict, start_s: int, end_s: int) -> list[list]:
    t = m15_arr["t"]
    i0, i1 = np.searchsorted(t, start_s * 1000), np.searchsorted(t, end_s * 1000)
    return m15_arr["rows"][i0:i1]


def _simulate(p: dict, m15_arr: dict, entry_mode: str, horizon: int) -> dict | None:
    """Canlı takiple aynı giriş (tracker.find_fill) ve çıkış (tracker._simulate) kuralları."""
    fill = tracker.find_fill(p, _candles(m15_arr, p["ts"], p["ts"] + LIMIT_FILL_H * 3600), entry_mode, LIMIT_FILL_H)
    if fill is None:
        return None  # emir dolmadı → işlem yok
    p = {**p, "ts": fill}
    return tracker._simulate(p, _candles(m15_arr, p["ts"], p["ts"] + horizon), horizon)


def run_variant(snaps_by_ts: dict, regimes: dict, m15: dict, v: dict, base_cfg: dict) -> list[dict]:
    """Bir ayar setiyle tüm adımları işler; sonuçlanmış işlem sinyalleri (hesap öncesi) döner."""
    cfg = {**base_cfg, **v}
    plans_key = "plans_limit" if cfg["entry_mode"] == "limit" else "plans_market"
    horizon = cfg["horizon_h"] * 3600
    out = []
    for T, snaps in snaps_by_ts.items():
        results = []
        for s in snaps:
            raw = signal.raw_score({**s["components"], "onchain": 0.0}, cfg["weights"], cfg.get("old_norm", False))
            results.append({"symbol": s["symbol"], "name": s["symbol"], "market": "crypto", "price": s["price"],
                            "atr": s["atr"], "raw_score": raw, "components": s["components"], "plans": s[plans_key]})
        longs, shorts = scanner._rank(results, cfg)
        regs = {"crypto": regimes.get(T, "neutral")} if cfg["regime_filter"] else None
        for c in strategy.select(longs + shorts, cfg, regs, check_session=False):
            p = {k: c[k] for k in ("symbol", "side", "signal", "score", "rr", "entry", "sl", "tp1", "tp2", "price")}
            p.update(ts=T, market="crypto")
            sim = _simulate(p, m15[c["symbol"]], cfg["entry_mode"], horizon)
            if sim:
                out.append({**p, **sim})
    return out


def split_stats(signals: list[dict], split_ts: int, cfg: dict) -> dict:
    acct = lambda xs: tracker.account(xs, cfg["capital_usd"], cfg["risk_pct"],  # noqa: E731
                                      cfg["max_open"], cfg["max_same_dir_crypto"])
    return {"all": acct(signals), "is": acct([s for s in signals if s["ts"] < split_ts]),
            "oos": acct([s for s in signals if s["ts"] >= split_ts])}


def component_power(snaps: list[dict], split_ts: int) -> dict:
    """Her bileşenin 24 saat sonraki (ATR cinsinden) getiriyle sıra korelasyonu — eğitim ve test ayrı."""
    df = pd.DataFrame([{**s["components"], "fwd": s["fwd_atr"], "ts": s["ts"]} for s in snaps]).dropna()
    out = {}
    for part, sub in (("is", df[df.ts < split_ts]), ("oos", df[df.ts >= split_ts])):
        # Spearman = sıralara uygulanan Pearson (scipy gerektirmeden)
        out[part] = {c: float(sub[c].rank().corr(sub["fwd"].rank())) for c in df.columns if c not in ("fwd", "ts")}
    return out


# ---------- fonlama oranı (vadeli işlemler) ----------

FUNDING_NEUTRAL = 0.0001  # %0.01 / 8 saat: Binance'in taban oranı
FUNDING_SCALE = 0.0004    # tabandan bu kadar sapma → bileşen ±1


def funding_component(avg_rate: float) -> float:
    """Kalabalığın tersi: fonlama taban oranın üstündeyse (herkes long) düşüş yönü (−), altındaysa (+)."""
    return max(-1.0, min(1.0, -(avg_rate - FUNDING_NEUTRAL) / FUNDING_SCALE))


async def fetch_funding(symbols: list[str], days: int) -> dict[str, pd.Series]:
    import ccxt.async_support as ccxt
    ex = ccxt.binanceusdm({"enableRateLimit": True})
    out = {}
    try:
        for s in symbols:
            path = CACHE / f"{s}_funding.pkl"
            if path.exists() and time.time() - path.stat().st_mtime < 86400:
                out[s] = pd.read_pickle(path)
                continue
            since, rows = int((time.time() - days * 86400) * 1000), []
            try:
                while True:
                    b = await ex.fetch_funding_rate_history(f"{s}/USDT:USDT", since=since, limit=1000)
                    if not b:
                        break
                    rows += b
                    since = b[-1]["timestamp"] + 1
                    if len(b) < 1000:
                        break
            except Exception as e:  # noqa: BLE001 — vadelisi olmayan coin
                log.info("fonlama yok %s: %s", s, e)
                continue
            if rows:
                ser = pd.Series([r["fundingRate"] for r in rows], index=[r["timestamp"] // 1000 for r in rows])
                ser = ser[~ser.index.duplicated()].sort_index()
                ser.to_pickle(path)
                out[s] = ser
    finally:
        await ex.close()
    return out


def inject_funding(snaps: list[dict], funding: dict[str, pd.Series], lookback: int = 9) -> int:
    """Her anlık görüntüye o ana kadar bilinen son `lookback` fonlamanın (≈3 gün) ortalamasını bileşen olarak ekler."""
    added = 0
    prepared = {s: (ser.index.to_numpy(), ser.rolling(lookback, min_periods=3).mean().to_numpy())
                for s, ser in funding.items()}
    for snap in snaps:
        p = prepared.get(snap["symbol"])
        if p is None:
            continue
        k = int(np.searchsorted(p[0], snap["ts"], side="right")) - 1
        if k >= 0 and p[1][k] == p[1][k]:
            snap["components"] = {**snap["components"], "funding": funding_component(float(p[1][k]))}
            added += 1
    return added


def focus_grid(weights: dict) -> list[dict]:
    """Seçilen strateji ailesi × fonlama ağırlığı (0 = fonlamasız karşılaştırma)."""
    out = []
    for th in (65, 70):
        for fw in (0, 10, 20, 30):
            out.append({"name": f"eşik {th}/{100 - th} · R:R≥2.5 · rejim · limit · 72s · fonlama {fw}",
                        "regime_filter": True, "entry_mode": "limit", "horizon_h": 72, "buy_threshold": th,
                        "sell_threshold": 100 - th, "cand_min_rr": 2.5, "weights": {**weights, "funding": fw}})
    return out


# ---------- ana akış ----------

async def load(symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
    sem = asyncio.Semaphore(5)

    async def one(s):
        async with sem:
            try:
                return s, await fetch_15m(s, days)
            except Exception as e:  # noqa: BLE001
                log.warning("veri alınamadı %s: %s", s, e)
                return s, None

    got = await asyncio.gather(*(one(s) for s in symbols))
    return {s: df for s, df in got if df is not None and len(df) > 96 * 90}  # en az ~90 gün geçmiş


def build(m15s: dict[str, pd.DataFrame], test_days: int, workers: int = 8):
    now = int(time.time()) // STEP * STEP - 3 * 86400  # sonuçları tamamlanmış son adım
    steps = list(range(now - test_days * 86400, now, STEP))
    with ProcessPoolExecutor(workers) as pool:
        per_symbol = list(pool.map(_snapshots, [(s, df, steps) for s, df in m15s.items()]))
    snaps = [x for xs in per_symbol for x in xs]
    by_ts: dict[int, list] = {}
    for s in snaps:
        by_ts.setdefault(s["ts"], []).append(s)
    btc = _frames(m15s["BTC"])["1d"]
    btc_end = btc.index.as_unit("s").asi8 + 86400
    regimes = {}
    for T in by_ts:
        k = int(np.searchsorted(btc_end, T, side="right"))
        regimes[T] = strategy.regime(btc.iloc[:k]) if k >= MIN_BARS else "neutral"
    arrays = {s: {"t": df.index.as_unit("ms").asi8,
                  "rows": np.column_stack([df.index.as_unit("ms").asi8, df[list(AGG)].to_numpy()]).tolist()}
              for s, df in m15s.items()}
    split = steps[0] + int((steps[-1] - steps[0]) * IS_SHARE)
    return dict(sorted(by_ts.items())), snaps, regimes, arrays, split


def grid() -> list[dict]:
    """Karşılaştırılacak ayar setleri (az sayıda, anlamlı eksen → aşırı uydurma riski düşük)."""
    out = [{"name": "ESKİ (düzeltme öncesi)", "old_norm": True, "regime_filter": False, "entry_mode": "market",
            "horizon_h": 24, "buy_threshold": 65, "sell_threshold": 35, "cand_min_rr": 2.0}]
    for th, rr, reg, entry, hz in itertools.product((60, 65, 70), (1.5, 2.0, 2.5), (False, True),
                                                    ("market", "limit"), (24, 72)):
        out.append({"name": f"eşik {th}/{100 - th} · R:R≥{rr:g} · {'rejim' if reg else 'rejimsiz'} · "
                            f"{'limit' if entry == 'limit' else 'piyasa'} · {hz}s",
                    "regime_filter": reg, "entry_mode": entry, "horizon_h": hz,
                    "buy_threshold": th, "sell_threshold": 100 - th, "cand_min_rr": rr})
    return out


def run_all(built, base_cfg: dict, variants: list[dict] | None = None) -> list[dict]:
    by_ts, _snaps, regimes, arrays, split = built
    results = []
    for v in variants or grid():
        sig = run_variant(by_ts, regimes, arrays, v, base_cfg)
        results.append({**v, "stats": split_stats(sig, split, {**base_cfg, **v}), "signals": sig})
    return results


def pick_best(results: list[dict], min_trades: int = 60) -> dict | None:
    """Sadece EĞİTİM dönemine bakarak seç: beklenti × √işlem (tesadüfe karşı t-istatistiği benzeri)."""
    def score(r):
        s = r["stats"]["is"]
        if s["trades"] < min_trades or s["expectancy"] is None:
            return -1e9
        return s["expectancy"] * s["trades"] ** 0.5
    ranked = sorted((r for r in results if not r.get("old_norm")), key=score, reverse=True)
    return ranked[0] if ranked and score(ranked[0]) > -1e9 else None


def run(symbols: list[str], days: int = 1000, test_days: int = 730, base_cfg: dict | None = None):
    m15s = asyncio.run(_load_and_close(symbols, days))
    built = build(m15s, test_days)
    return built, run_all(built, base_cfg)


async def _load_and_close(symbols, days):
    try:
        return await load(symbols, days)
    finally:
        await data.close()
