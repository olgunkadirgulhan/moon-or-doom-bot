"""Tahmin kaydı, isabet değerlendirmesi ve sanal hesap — kalıcı dosyalar (repoda saklanır, kaybolmaz):

  tracking/predictions.csv  her rapordaki her tahmin (candidate=1 → strateji kurallarını geçen işlem adayı)
  tracking/outcomes.csv     24 saati dolmuş tahminlerin kesin sonucu (bir kez hesaplanır)
  tracking/results.csv      gönderilen her dönem özetinin (günlük … yıllık) kaydı

Giriş: "market" tahminler verildiği anda, "limit" tahminler fiyat 12 saat içinde giriş seviyesine
değerse o anda açılmış sayılır; değmezse işlem hiç açılmamıştır (NOFILL — isabete ve hesaba girmez).

İsabet: giriş anından itibaren 24 saat 15 dakikalık mumlarla izlenir; önce SL'ye değerse ✗, önce
TP1'e değerse ✓, hiçbirine değmediyse "açık". Aynı mumda ikisi birden görülürse temkinli olup SL sayılır.

Strateji (sanal hesap): SL'de −1R; TP1'de yarısı kapanır ve stop girişe çekilir; kalan yarı
TP2'de, girişte (başabaş) ya da horizon_h (varsayılan 72) saat sonunda son fiyattan kapanır.
Komisyon R'den düşülür.
"""
import csv
import time
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core import ROOT, data, settings, tradfi

TZ = ZoneInfo("Europe/Istanbul")
TRACK_DIR = ROOT / "tracking"
PRED_FILE = TRACK_DIR / "predictions.csv"
OUT_FILE = TRACK_DIR / "outcomes.csv"
RESULTS_FILE = TRACK_DIR / "results.csv"
PRED_FIELDS = ["ts", "symbol", "side", "signal", "score", "rr", "entry", "sl", "tp1", "tp2", "market", "candidate",
               "price", "mode", "onchain", "netflow"]
OUT_FIELDS = ["ts", "symbol", "side", "market", "outcome", "tp2_hit", "pnl", "r", "exit_ts"]
RESULT_FIELDS = ["sent_at", "period", "title", "total", "tp", "sl", "open", "accuracy",
                 "acc_crypto", "acc_tradfi", "acc_bist", "acct_trades", "acct_expectancy_r", "acct_equity"]
TF = "15m"
TF_MS = 15 * 60 * 1000
HORIZON = 24 * 3600  # isabet ölçümü: giriş sonrası izleme süresi
FILL_H = 12  # limit emrin geçerlilik süresi (saat)
FEE_PCT = 0.1  # giriş + çıkış toplam komisyon, pozisyonun %'si
MARKET_LABEL = {"crypto": "Kripto", "tradfi": "Altın/Gümüş/Endeks", "bist": "BIST hisse"}

# dönem → (ay sayısı, hangi ay sonlarında gönderilir)
LONG_PERIODS = {"3m": (3, {3, 6, 9, 12}), "6m": (6, {6, 12}), "9m": (9, {9}), "12m": (12, {12})}
PERIOD_NAMES = {"daily": "Günlük", "weekly": "Haftalık", "monthly": "Aylık",
                "3m": "3 Aylık", "6m": "6 Aylık", "9m": "9 Aylık", "12m": "Yıllık"}


# ---------- dosya yardımcıları ----------

def _read(path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _ensure_header(path, fields: list[str]) -> None:
    """Dosyanın başlığı eksik sütun içeriyorsa yeni başlıkla yeniden yaz (eski satırlar korunur)."""
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    if header == fields:
        return
    rows = _read(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _append(path, fields: list[str], rows: list[dict]) -> None:
    TRACK_DIR.mkdir(exist_ok=True)
    _ensure_header(path, fields)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def record(results: list[dict], mode: str = "market") -> None:
    now = int(time.time())

    def onchain(r, key):  # veri yoksa boş: sonradan tahmin gücü ölçümünde ayırt edilsin
        oc = r.get("onchain") or {}
        return oc.get(key) if oc.get("available") else ""

    _append(PRED_FILE, PRED_FIELDS, [
        {"ts": now, **{k: r.get(k, "") for k in PRED_FIELDS[1:]},
         "market": r.get("market") or "crypto", "candidate": 1 if r.get("candidate") else "", "mode": mode,
         "onchain": onchain(r, "score"), "netflow": onchain(r, "netflow_24h")}
        for r in results
    ])


def _key(p: dict) -> tuple:
    return int(p["ts"]), p["symbol"], p["side"], p.get("market") or "crypto"


def _load(since: int, until: int) -> list[dict]:
    names = {k: v["name"] for k, v in tradfi.instruments().items()}
    out = []
    for r in _read(PRED_FILE):
        ts = int(r["ts"])
        if since <= ts <= until:
            market = r.get("market") or "crypto"
            p = {**r, "ts": ts, "market": market, "candidate": r.get("candidate") == "1",
                 "mode": r.get("mode") or "market",
                 "name": r["symbol"] if market == "crypto" else names.get(r["symbol"], r["symbol"]),
                 **{k: float(r[k]) for k in ("score", "rr", "entry", "sl", "tp1", "tp2")}}
            p["price"] = float(r["price"]) if r.get("price") else p["entry"]  # eski kayıtlar: market giriş
            out.append(p)
    return out


def _outcomes() -> dict[tuple, dict]:
    out = {}
    for o in _read(OUT_FILE):
        out[_key(o)] = {
            "outcome": o["outcome"], "tp2_hit": o["tp2_hit"] == "True", "pnl": float(o["pnl"]),
            "r": float(o["r"]) if o.get("r") not in (None, "") else None,
            "exit_ts": int(o["exit_ts"]) if o.get("exit_ts") not in (None, "") else int(o["ts"]) + HORIZON,
        }
    return out


# ---------- mum verisi ----------

async def _crypto_candles(symbol: str, since_ms: int, until_ms: int) -> list[list]:
    rows, cursor = [], since_ms
    while cursor < until_ms:
        batch = await data.exchange().fetch_ohlcv(f"{symbol}/USDT", TF, since=cursor, limit=1000)
        if not batch:
            break
        rows += [b for b in batch if b[0] < until_ms]
        cursor = batch[-1][0] + TF_MS
        if len(batch) < 1000:
            break
    return rows


async def _candles(market: str, symbol: str, since_ms: int, until_ms: int) -> list[list]:
    if market == "crypto":
        return await _crypto_candles(symbol, since_ms, until_ms)
    return await tradfi.candles(symbol, since_ms, until_ms)


# ---------- tek tahminin sonucu ----------

def _pnl(p: dict, price: float) -> float:
    change = (price - p["entry"]) / p["entry"] * 100
    return change if p["side"] == "long" else -change


def _simulate(p: dict, candles: list[list], horizon: int = HORIZON) -> dict:
    """İsabet (TP/SL/OPEN) + strateji kuralıyla R sonucu ve çıkış zamanı."""
    long = p["side"] == "long"
    entry, risk = p["entry"], abs(p["entry"] - p["sl"])
    rr = lambda price: abs(price - entry) / risk  # noqa: E731
    start, end = p["ts"] * 1000, (p["ts"] + horizon) * 1000
    first, tp2_hit, half, r, exit_ms, last = None, False, False, 0.0, None, entry
    stop = p["sl"]

    for t, _o, high, low, close, _v in candles:
        if t < start:
            continue
        if t >= end:
            break
        last = close
        hit_stop = low <= stop if long else high >= stop
        hit_tp1 = high >= p["tp1"] if long else low <= p["tp1"]
        hit_tp2 = high >= p["tp2"] if long else low <= p["tp2"]
        if not half:
            if hit_stop:  # aynı mumda TP1 de olsa temkinli: SL
                first, r, exit_ms = "SL", -1.0, t
                break
            if hit_tp1:
                first, half, stop = "TP", True, entry
                r = 0.5 * rr(p["tp1"])
                if hit_tp2:
                    tp2_hit, r, exit_ms = True, r + 0.5 * rr(p["tp2"]), t
                    break
        else:
            if hit_stop:  # kalan yarı başabaşta kapandı
                exit_ms = t
                break
            if hit_tp2:
                tp2_hit, r, exit_ms = True, r + 0.5 * rr(p["tp2"]), t
                break

    if exit_ms is None:  # zaman stopu: kalan kısım son fiyattan
        move = (last - entry) / risk * (1 if long else -1)
        r += (0.5 if half else 1.0) * move
        exit_ms = end
    fee_r = (FEE_PCT / 100) * entry / risk if risk else 0.0

    outcome = first or "OPEN"
    pnl_price = p["sl"] if outcome == "SL" else (p["tp2"] if tp2_hit else p["tp1"]) if outcome == "TP" else last
    return {"outcome": outcome, "tp2_hit": tp2_hit, "pnl": _pnl(p, pnl_price),
            "r": r - fee_r, "exit_ts": exit_ms // 1000}


def strategy_horizon() -> int:
    return int(settings.get("horizon_h")) * 3600


def resolve_after() -> int:
    """Bir tahminin kesin sonucu için gereken süre: limit bekleme + en uzun izleme."""
    return FILL_H * 3600 + max(HORIZON, strategy_horizon())


def find_fill(p: dict, candles: list[list], mode: str, fill_h: int = FILL_H) -> int | None:
    """Giriş anı (sn): market → hemen; limit → fiyat fill_h saat içinde girişe değdiği mum; değmezse None."""
    if mode != "limit" or p["entry"] == p.get("price", p["entry"]):
        return p["ts"]
    long = p["side"] == "long"
    start, expiry = p["ts"] * 1000, (p["ts"] + fill_h * 3600) * 1000
    for t, _o, high, low, _c, _v in candles:
        if t < start:
            continue
        if t >= expiry:
            break
        if (low <= p["entry"]) if long else (high >= p["entry"]):
            return t // 1000
    return None


def simulate_full(p: dict, candles: list[list], strat_h: int | None = None) -> dict:
    """İsabet (giriş sonrası 24s) + strateji R'si (giriş sonrası strat_h) — limit dolmadıysa NOFILL."""
    fill = find_fill(p, candles, p.get("mode", "market"))
    if fill is None:
        return {"outcome": "NOFILL", "tp2_hit": False, "pnl": 0.0, "r": None, "exit_ts": p["ts"] + FILL_H * 3600}
    q = {**p, "ts": fill}
    acc = _simulate(q, candles, HORIZON)
    strat = _simulate(q, candles, strat_h or strategy_horizon())
    return {"outcome": acc["outcome"], "tp2_hit": acc["tp2_hit"], "pnl": acc["pnl"],
            "r": strat["r"], "exit_ts": strat["exit_ts"]}


async def _simulate_group(market: str, sym: str, ps: list[dict], until: int) -> list[dict]:
    try:
        candles = await _candles(market, sym, min(p["ts"] for p in ps) * 1000,
                                 min(max(p["ts"] for p in ps) + resolve_after(), until) * 1000)
    except Exception:  # noqa: BLE001 — veri yoksa bu turda sonuçlanmaz
        candles = []
    return [{**p, **simulate_full(p, candles), "_has_data": bool(candles)} for p in ps]


async def resolve_pending(now: int | None = None) -> int:
    """Süresi dolmuş (limit bekleme + izleme) ama sonucu kaydedilmemiş tüm tahminleri kalıcı olarak sonuçlandırır."""
    now = now or int(time.time())
    known = _outcomes()
    pending = defaultdict(list)
    for p in _load(0, now - resolve_after()):
        if _key(p) not in known:
            pending[(p["market"], p["symbol"])].append(p)
    rows = []
    for (market, sym), ps in pending.items():
        for s in await _simulate_group(market, sym, ps, now):
            if s["_has_data"]:
                rows.append({"ts": s["ts"], "symbol": sym, "side": s["side"], "market": market,
                             "outcome": s["outcome"], "tp2_hit": s["tp2_hit"], "pnl": round(s["pnl"], 4),
                             "r": "" if s["r"] is None else round(s["r"], 4), "exit_ts": s["exit_ts"]})
    if rows:
        _append(OUT_FILE, OUT_FIELDS, rows)
    return len(rows)


# ---------- dönem özeti ----------

def _stats(items: list[dict]) -> dict:
    """Dolmayan limit emirler (NOFILL) işlem sayılmaz: toplamda ve doğrulukta yer almaz."""
    tp = sum(i["outcome"] == "TP" for i in items)
    sl = sum(i["outcome"] == "SL" for i in items)
    op = sum(i["outcome"] == "OPEN" for i in items)
    return {"total": tp + sl + op, "tp": tp, "sl": sl, "open": op,
            "nofill": sum(i["outcome"] == "NOFILL" for i in items),
            "accuracy": round(100 * tp / (tp + sl), 1) if tp + sl else None}


def _month_start(now: datetime, months_back: int) -> datetime:
    y, m = now.year, now.month - months_back
    while m <= 0:
        m, y = m + 12, y - 1
    return now.replace(year=y, month=m, day=1, hour=0, minute=0, second=0, microsecond=0)


def period_bounds(period: str, now: datetime | None = None) -> tuple[int, int, str]:
    """(başlangıç_ts, bitiş_ts, başlık)."""
    now = now or datetime.now(TZ)
    if period == "daily":
        start = now - timedelta(days=1)
        title = f"Günlük Sonuç — {now:%d.%m.%Y}"
    elif period == "weekly":
        start = now - timedelta(days=7)
        title = f"Haftalık Sonuç — {start:%d.%m} – {now:%d.%m.%Y}"
    elif period == "monthly":
        start = _month_start(now, 0)
        title = f"Aylık Sonuç — {now:%m.%Y}"
    else:
        months = LONG_PERIODS[period][0]
        start = _month_start(now, months - 1)
        title = f"{PERIOD_NAMES[period]} Sonuç — {start:%m.%Y} – {now:%m.%Y}"
    return int(start.timestamp()), int(now.timestamp()), title


def is_last_day_of_month(now: datetime | None = None) -> bool:
    now = now or datetime.now(TZ)
    return (now + timedelta(days=1)).month != now.month


def due_periods(now: datetime | None = None) -> list[str]:
    """Akşam sonuç çalışmasında bugün gönderilecek dönemler."""
    now = now or datetime.now(TZ)
    periods = ["daily"]
    if now.weekday() == 5:  # cumartesi
        periods.append("weekly")
    if is_last_day_of_month(now):
        periods.append("monthly")
        periods += [p for p, (_, months) in LONG_PERIODS.items() if now.month in months]
    return periods


def _bucket(ts: int, span_days: float) -> tuple[str, str]:
    """(sıralama anahtarı, etiket): ≤31 gün → gün, ≤186 gün → hafta, üstü → ay."""
    d = datetime.fromtimestamp(ts, TZ)
    if span_days <= 31:
        return d.strftime("%Y-%m-%d"), d.strftime("%d.%m")
    if span_days <= 186:
        monday = d - timedelta(days=d.weekday())
        return monday.strftime("%Y-%m-%d"), monday.strftime("%d.%m") + " hf"
    return d.strftime("%Y-%m"), d.strftime("%m.%Y")


async def evaluate(since: int, until: int) -> dict:
    """[since, until] aralığındaki tahminler: kesinleşenler kayıttan, 24 saati dolmayanlar anlık hesaplanır."""
    await resolve_pending(until)
    known = _outcomes()
    items, live = [], defaultdict(list)
    for p in _load(since, until):
        o = known.get(_key(p))
        if o:
            items.append({**p, **o})
        else:
            live[(p["market"], p["symbol"])].append(p)
    for (market, sym), ps in live.items():
        items += await _simulate_group(market, sym, ps, until)

    by_market = {m: [i for i in items if i["market"] == m] for m in MARKET_LABEL}
    groups = {MARKET_LABEL[m]: v for m, v in by_market.items() if v}
    groups |= {
        "İşlem adayı": [i for i in items if i["candidate"]],
        "LONG": [i for i in items if i["side"] == "long"],
        "SHORT": [i for i in items if i["side"] == "short"],
        "AL/SAT": [i for i in items if i["signal"] != "BEKLE"],
        "BEKLE": [i for i in items if i["signal"] == "BEKLE"],
        "R:R ≥ 2": [i for i in items if i["rr"] >= 2],
        "R:R < 2": [i for i in items if i["rr"] < 2],
    }
    cfg = settings.all_settings()
    span_days = (until - since) / 86400
    buckets = defaultdict(list)
    for i in items:
        buckets[_bucket(i["ts"], span_days)].append(i)
    return {
        "overall": _stats(items),
        "groups": {k: _stats(v) for k, v in groups.items() if v},
        "by_market": {m: _stats(v) for m, v in by_market.items()},
        "by_day": [(label, _stats(v)) for (_, label), v in sorted(buckets.items())],
        "coins": len({(i["market"], i["symbol"]) for i in items}),
        "items": items,
        "account": virtual_account(until, *(cfg[k] for k in ("capital_usd", "risk_pct", "max_open",
                                                                   "max_same_dir_crypto"))),
    }


# ---------- sanal hesap ----------

def virtual_account(until: int, capital: float = 1000.0, risk_pct: float = 1.0,
                    max_open: int = 3, max_same_dir_crypto: int = 2) -> dict:
    """Başlangıçtan beri işlem adaylarını strateji kurallarıyla işleyen sanal hesap (bileşik, %risk_pct)."""
    known = _outcomes()
    resolved, pending = [], 0
    for p in sorted((p for p in _load(0, until) if p["candidate"]), key=lambda p: p["ts"]):
        o = known.get(_key(p))
        if o and o["outcome"] == "NOFILL":
            continue  # limit emir dolmadı: işlem açılmadı
        if not o or o["r"] is None:
            pending += 1
        else:
            resolved.append({**p, **o})
    return {**account(resolved, capital, risk_pct, max_open, max_same_dir_crypto), "pending": pending}


def account(signals: list[dict], capital: float = 1000.0, risk_pct: float = 1.0,
            max_open: int = 3, max_same_dir_crypto: int = 2) -> dict:
    """Sonuçlanmış adayları (ts, exit_ts, r, symbol, side, market) sırayla işler: aynı varlıkta ya da limit dolmuşken
    yeni işlem açılmaz; her işlem o anki sermayenin %risk_pct'i kadar risk taşır (bileşik)."""
    open_pos, trades = [], []
    for p in sorted(signals, key=lambda p: p["ts"]):
        open_pos = [q for q in open_pos if q["exit_ts"] > p["ts"]]
        same_dir = sum(q["market"] == "crypto" and q["side"] == p["side"] for q in open_pos)
        if (any(q["symbol"] == p["symbol"] for q in open_pos) or len(open_pos) >= max_open
                or (p["market"] == "crypto" and same_dir >= max_same_dir_crypto)):
            continue
        open_pos.append(p)
        trades.append(p)

    equity, peak, max_dd, curve = capital, capital, 0.0, []
    streak = worst_streak = 0
    for t in sorted(trades, key=lambda t: t["exit_ts"]):
        equity *= 1 + risk_pct / 100 * t["r"]
        peak = max(peak, equity)
        max_dd = max(max_dd, 100 * (peak - equity) / peak)
        streak = streak + 1 if t["r"] < 0 else 0
        worst_streak = max(worst_streak, streak)
        curve.append((t["exit_ts"], equity))

    n = len(trades)
    rs = [t["r"] for t in trades]
    expectancy = sum(rs) / n if n else None
    gains, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return {
        "capital": capital, "risk_pct": risk_pct, "equity": equity, "trades": n, "pending": 0,
        "wins": sum(r > 0 for r in rs), "win_rate": 100 * sum(r > 0 for r in rs) / n if n else None,
        "expectancy": expectancy, "total_r": sum(rs), "max_dd": max_dd, "worst_streak": worst_streak,
        "profit_factor": gains / losses if losses else None, "curve": curve, "taken": trades,
        # Aşama 1 → gerçek para kapısı
        "gate": {"n": n >= 100, "expectancy": expectancy is not None and expectancy > 0.2, "dd": max_dd < 15},
    }


def save_result(period: str, title: str, summary: dict) -> None:
    o, bm, a = summary["overall"], summary["by_market"], summary["account"]
    _append(RESULTS_FILE, RESULT_FIELDS, [{
        "sent_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "period": period, "title": title,
        **{k: o[k] for k in ("total", "tp", "sl", "open", "accuracy")},
        "acc_crypto": bm["crypto"]["accuracy"], "acc_tradfi": bm["tradfi"]["accuracy"],
        "acc_bist": bm["bist"]["accuracy"], "acct_trades": a["trades"],
        "acct_expectancy_r": None if a["expectancy"] is None else round(a["expectancy"], 3),
        "acct_equity": round(a["equity"], 2),
    }])
