"""Bileşen skorları → AL/SAT/BEKLE + giriş/SL/TP/R:R.

Her bileşen [-1, +1] arası bir değer üretir (+1 = tam AL yönü). Toplam skor
50 + Σ(ağırlık × değer) / 2 → ağırlıklar toplamı 100 iken 0–100 aralığı.
"""
import math

import pandas as pd

from core.indicators import last_atr

STRONG_STRENGTH = 50  # güçlü seviye: güç ≥ 50 veya ≥2 TF konfluens


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _is_strong(level: tuple) -> bool:
    return level[1] >= STRONG_STRENGTH or level[2] >= 2


def _merged(levels_by_tf: dict, side: str, tol: float) -> list[tuple]:
    """Tüm TF'lerin seviyelerini birleştirir, tol içindekilerden en güçlüsünü tutar."""
    pts = sorted((l for lv in levels_by_tf.values() for l in lv[side]), key=lambda l: l[0])
    out: list[tuple] = []
    for l in pts:
        if out and abs(l[0] - out[-1][0]) <= tol:
            a = out[-1]
            out[-1] = max(a, l, key=lambda x: (x[2], x[1]))
        else:
            out.append(l)
    return out


def _nearest(levels: list[tuple], price: float, below: bool) -> tuple | None:
    side = [l for l in levels if (l[0] < price if below else l[0] > price)]
    strong = [l for l in side if _is_strong(l)] or side
    if not strong:
        return None
    return max(strong, key=lambda l: l[0]) if below else min(strong, key=lambda l: l[0])


def _trend(frames: dict) -> float:
    vals = []
    for tf in ("4h", "1d"):
        row = frames[tf].iloc[-1]
        if pd.isna(row["ema50"]) or pd.isna(row["ema200"]):
            vals.append(0.0)
        else:
            vals.append(1.0 if row["ema50"] > row["ema200"] else -1.0)
    return sum(vals) / len(vals)


def _rsi(frames: dict) -> float:
    vals = []
    for tf in ("1h", "4h"):
        r = frames[tf]["rsi14"].dropna()
        if len(r) < 2:
            vals.append(0.0)
            continue
        now, prev = r.iloc[-1], r.iloc[-2]
        if 30 <= now <= 45 and now > prev:
            vals.append(1.0)
        elif 55 <= now <= 70 and now < prev:
            vals.append(-1.0)
        elif now < 30:
            vals.append(0.5)
        elif now > 70:
            vals.append(-0.5)
        else:
            vals.append(0.0)
    return sum(vals) / len(vals)


MIN_TARGET_ATR = 0.5  # fiyata bundan yakın seviyeler hedef sayılmaz (gürültü)


def _plan(side: str, price: float, supports: list, resistances: list, atr: float) -> dict:
    """Giriş her zaman güncel fiyat. long: SL en yakın desteğin altında, TP'ler üstteki dirençler; short tersi."""
    entry = price
    if side == "long":
        below = [l[0] for l in supports if l[0] < price]
        sl = (max(below) if below else price - 0.5 * atr) - atr
        targets = [l[0] for l in resistances if l[0] > price + MIN_TARGET_ATR * atr]
        tp1 = targets[0] if targets else price + 2 * atr
        tp2 = targets[1] if len(targets) > 1 else max(tp1 + atr, price + 3.5 * atr)
        rr = (tp1 - entry) / (entry - sl)
    else:
        above = [l[0] for l in resistances if l[0] > price]
        sl = (min(above) if above else price + 0.5 * atr) + atr
        targets = [l[0] for l in reversed(supports) if l[0] < price - MIN_TARGET_ATR * atr]
        tp1 = targets[0] if targets else price - 2 * atr
        tp2 = targets[1] if len(targets) > 1 else min(tp1 - atr, price - 3.5 * atr)
        rr = (entry - tp1) / (sl - entry)
    return {"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "rr": rr}


def evaluate(symbol: str, frames: dict, levels_by_tf: dict, onchain: dict, cfg: dict) -> dict:
    price = float(frames["1h"]["Close"].iloc[-1])
    atr = last_atr(frames["4h"])
    tol = 0.5 * atr
    supports = sorted(_merged(levels_by_tf, "supports", tol), key=lambda l: l[0])
    resistances = sorted(_merged(levels_by_tf, "resistances", tol), key=lambda l: l[0])

    sup = _nearest(supports, price, below=True)
    res = _nearest(resistances, price, below=False)
    near_sup = _clip(1 - (price - sup[0]) / atr, 0, 1) if sup else 0.0
    near_res = _clip(1 - (res[0] - price) / atr, 0, 1) if res else 0.0
    conf_sup = 1.0 if sup and sup[2] >= 2 else 0.0
    conf_res = 1.0 if res and res[2] >= 2 else 0.0

    components = {
        "trend": _trend(frames),
        "proximity": near_sup - near_res,
        "rsi": _rsi(frames),
        "confluence": conf_sup - conf_res,
        "onchain": _clip(onchain.get("score", 0) / 100),
    }
    w = cfg["weights"]
    total_w = sum(w.values()) or 1
    raw = 50 + 50 * sum(w[k] * v for k, v in components.items()) / total_w

    base = {
        "symbol": symbol,
        "price": price,
        "atr": atr,
        "raw_score": raw,
        "components": {k: round(v, 2) for k, v in components.items()},
        "plans": {s: _plan(s, price, supports, resistances, atr) for s in ("long", "short")},
    }
    return with_side(base, "long" if raw >= 50 else "short", cfg)


def with_side(res: dict, side: str, cfg: dict) -> dict:
    """Sonucu verilen yönün planıyla doldurur; düşük R:R o yönün lehine olan skoru 10 puan zayıflatır."""
    plan = {k: (v if math.isfinite(v) else 0.0) for k, v in res["plans"][side].items()}
    rr_low = plan["rr"] < cfg["min_rr"]
    score = res["raw_score"]
    if rr_low:
        score += -cfg["rr_penalty"] if side == "long" else cfg["rr_penalty"]
    score = round(_clip(score, 0, 100), 1)

    if side == "long" and score >= cfg["buy_threshold"]:
        signal = "AL"
    elif side == "short" and score <= cfg["sell_threshold"]:
        signal = "SAT"
    else:
        signal = "BEKLE"
    return {**res, **plan, "side": side, "score": score, "signal": signal, "rr_low": rr_low}
