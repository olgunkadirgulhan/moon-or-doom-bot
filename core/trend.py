"""Trend takibi sinyal aileleri (zaman serisi momentumu). Akademik kanıtı en sağlam kripto etkisi:
trend yönünde işlem + volatiliteye göre stop. Az parametre (aşırı uydurmaya karşı), hepsi kapanmış mumlarla.

Aileler:
  pullback   4s: günlük yükseliş trendindeki coinde RSI 40 altına çekilip 45 üstüne dönüş → long
  breakout   1g: 20 günlük zirvenin hacimle kırılması (turtle/Donchian) → long
  breakdown  1g: 20 günlük dibin hacimle kırılması, sadece BTC düşüş trendindeyken → short
  pullback_s 4s: pullback'in aynası, sadece BTC düşüş trendindeyken → short

Her plan: entry (sinyal mumunun kapanışı), sl (ATR/swing), tp1, tp2, exit = "fixed" (TP1'de yarısı, stop başabaşa)
ya da "trail" (avize stop: en yüksek kapanış − k×ATR; sabit hedef yok, trend bitene kadar).
"""
import numpy as np
import pandas as pd

FAMILIES = ("pullback", "breakout", "breakdown", "pullback_s")
SLIP_PCT = 0.05  # komisyona ek kayma (giriş+çıkış), pozisyonun %'si


def daily_trend(d1: pd.DataFrame) -> np.ndarray:
    """+1 yükseliş (fiyat ve EMA50 > EMA200), −1 düşüş, 0 nötr — strategy.regime ile aynı tanım."""
    c, e50, e200 = d1["Close"].to_numpy(), d1["ema50"].to_numpy(), d1["ema200"].to_numpy()
    up = (c > e200) & (e50 > e200)
    dn = (c < e200) & (e50 < e200)
    out = np.where(up, 1, np.where(dn, -1, 0))
    out[np.isnan(e200)] = 0
    return out


def _asof(index_end: np.ndarray, values: np.ndarray, T: int, default=0):
    """T anında kapanmış son mumun değeri."""
    k = int(np.searchsorted(index_end, T, side="right")) - 1
    return values[k] if k >= 0 else default


BREAKOUT = {"lookback": 20, "vol_mult": 1.3, "atr_stop": 2.0, "trail_k": 3.0}


def plans(symbol: str, frames: dict, btc_trend: tuple[np.ndarray, np.ndarray], families=FAMILIES,
          start_ts: int = 0, bo: dict | None = None) -> list[dict]:
    bo = {**BREAKOUT, **(bo or {})}
    h4, d1 = frames["4h"], frames["1d"]
    d1_end = d1.index.as_unit("s").asi8 + 86400
    h4_end = h4.index.as_unit("s").asi8 + 14400
    dtr = daily_trend(d1)
    btc_end, btc_tr = btc_trend
    out = []

    def add(fam, side, T, entry, sl, atr, r1, r2, exit_mode, hz_h, trail_k=None):
        risk = abs(entry - sl)
        if not risk or risk / entry > 0.25:
            return
        sgn = 1 if side == "long" else -1
        out.append({"symbol": symbol, "family": fam, "side": side, "ts": int(T), "price": entry, "entry": entry,
                    "sl": sl, "tp1": entry + sgn * r1 * risk, "tp2": entry + sgn * r2 * risk, "atr": atr,
                    "exit": exit_mode, "horizon_h": hz_h, "trail_k": trail_k, "market": "crypto",
                    "signal": "AL" if side == "long" else "SAT", "score": 0.0, "rr": r2})

    # ---- 4 saatlik geri çekilme (long / short) ----
    if {"pullback", "pullback_s"} & set(families):
        c, lo, hi = h4["Close"].to_numpy(), h4["Low"].to_numpy(), h4["High"].to_numpy()
        rsi, atr, e200 = h4["rsi14"].to_numpy(), h4["atr14"].to_numpy(), h4["ema200"].to_numpy()
        for i in range(210, len(h4)):
            T = h4_end[i]
            if T < start_ts or np.isnan(atr[i]) or np.isnan(rsi[i - 1]):
                continue
            tr, btc = _asof(d1_end, dtr, T), _asof(btc_end, btc_tr, T)
            win_rsi = rsi[i - 6:i]
            if "pullback" in families and tr == 1 and btc != -1 and c[i] > e200[i] \
                    and np.nanmin(win_rsi) < 40 and rsi[i - 1] <= 45 < rsi[i]:
                sl = lo[i - 8:i + 1].min() - 0.3 * atr[i]
                if 0.5 * atr[i] <= c[i] - sl <= 3.5 * atr[i]:
                    add("pullback", "long", T, c[i], sl, atr[i], 1.5, 3.0, "fixed", 72)
            if "pullback_s" in families and tr == -1 and btc == -1 and c[i] < e200[i] \
                    and np.nanmax(win_rsi) > 60 and rsi[i - 1] >= 55 > rsi[i]:
                sl = hi[i - 8:i + 1].max() + 0.3 * atr[i]
                if 0.5 * atr[i] <= sl - c[i] <= 3.5 * atr[i]:
                    add("pullback_s", "short", T, c[i], sl, atr[i], 1.5, 3.0, "fixed", 72)

    # ---- günlük kırılım (long / short) ----
    if {"breakout", "breakdown"} & set(families):
        c, hi, lo = d1["Close"].to_numpy(), d1["High"].to_numpy(), d1["Low"].to_numpy()
        vol, vma = d1["Volume"].to_numpy(), d1["vol_ma20"].to_numpy()
        atr, e200 = d1["atr14"].to_numpy(), d1["ema200"].to_numpy()
        for i in range(201, len(d1)):
            T = d1_end[i]
            if T < start_ts or np.isnan(atr[i]) or np.isnan(vma[i]):
                continue
            btc = _asof(btc_end, btc_tr, T)
            n = bo["lookback"]
            if i < n:
                continue
            hh, ll = hi[i - n:i].max(), lo[i - n:i].min()
            loud = vol[i] > bo["vol_mult"] * vma[i]
            if "breakout" in families and c[i] > hh and loud and c[i] > e200[i] and btc != -1:
                add("breakout", "long", T, c[i], c[i] - bo["atr_stop"] * atr[i], atr[i], 2.0, 4.0, "trail", 24 * 30,
                    bo["trail_k"])
            if "breakdown" in families and c[i] < ll and loud and c[i] < e200[i] and btc == -1:
                add("breakdown", "short", T, c[i], c[i] + bo["atr_stop"] * atr[i], atr[i], 2.0, 4.0, "trail", 24 * 30,
                    bo["trail_k"])
    return out


def simulate_trail(p: dict, candles: list[list], d1: pd.DataFrame) -> dict:
    """Avize stop: stop = max(ilk stop, en yüksek günlük kapanış − k×ATR) (short için ayna). Günlük kapanışta
    güncellenir, gün içinde 15 dk mumlarla tetiklenir. Süre dolunca son fiyattan çıkış."""
    long = p["side"] == "long"
    entry, risk, k = p["entry"], abs(p["entry"] - p["sl"]), p["trail_k"]
    stop, best = p["sl"], entry
    end = (p["ts"] + p["horizon_h"] * 3600) * 1000
    d1_end = d1.index.as_unit("ms").asi8 + 86_400_000
    d_close, d_atr = d1["Close"].to_numpy(), d1["atr14"].to_numpy()
    j = int(np.searchsorted(d1_end, p["ts"] * 1000, side="right"))  # bir sonraki kapanacak gün
    last, exit_ms, exit_px = entry, None, None
    for t, _o, high, low, close, _v in candles:
        if t < p["ts"] * 1000:
            continue
        if t >= end:
            break
        while j < len(d1_end) and d1_end[j] <= t:  # bir gün kapandı → stopu güncelle
            if not np.isnan(d_atr[j]):
                best = max(best, d_close[j]) if long else min(best, d_close[j])
                cand = best - k * d_atr[j] if long else best + k * d_atr[j]
                stop = max(stop, cand) if long else min(stop, cand)
            j += 1
        last = close
        if (low <= stop) if long else (high >= stop):
            exit_ms, exit_px = t, stop
            break
    if exit_ms is None:
        exit_ms, exit_px = end, last
    r = (exit_px - entry) / risk * (1 if long else -1)
    from core.tracker import FEE_PCT
    r -= (FEE_PCT + SLIP_PCT) / 100 * entry / risk
    return {"outcome": "TP" if r > 0 else "SL", "tp2_hit": False, "pnl": 0.0, "r": r, "exit_ts": exit_ms // 1000}
