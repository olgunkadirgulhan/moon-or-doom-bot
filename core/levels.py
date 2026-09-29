"""Çoklu TF destek/direnç: fraktal swing noktaları → ATR toleransıyla kümeleme → güç skoru."""
import numpy as np
import pandas as pd

from core.indicators import last_atr

FRACTAL = {"1h": 5, "4h": 3, "8h": 3, "1d": 2}
PER_SIDE = 3


def swing_points(df: pd.DataFrame, n: int) -> list[tuple[float, int]]:
    """(fiyat, mum_index) listesi; hem swing high hem swing low."""
    highs, lows = df["High"].to_numpy(), df["Low"].to_numpy()
    pts = []
    for i in range(n, len(df) - n):
        if highs[i] == highs[i - n: i + n + 1].max():
            pts.append((highs[i], i))
        if lows[i] == lows[i - n: i + n + 1].min():
            pts.append((lows[i], i))
    return pts


def _cluster(pts: list[tuple[float, int]], df: pd.DataFrame, tol: float) -> list[tuple[float, float]]:
    """Yakın noktaları birleştirir; (fiyat, ham_güç) döner."""
    if not pts:
        return []
    vol = df["Volume"].to_numpy()
    vol_mean = vol.mean() or 1.0
    n = len(df)

    groups: list[list[tuple[float, int]]] = []
    for p in sorted(pts):
        if groups and p[0] - np.mean([g[0] for g in groups[-1]]) <= tol:
            groups[-1].append(p)
        else:
            groups.append([p])

    out = []
    for g in groups:
        price = float(np.mean([p for p, _ in g]))
        strength = 0.0
        for _, i in g:
            touch = 1.0
            volume_w = 0.5 * min(vol[i] / vol_mean, 3.0)
            recency = 1.0 - (n - 1 - i) / n  # son mumlar 1'e yakın
            strength += touch + volume_w + recency
        out.append((price, strength))
    return out


def compute_levels(df: pd.DataFrame, tf: str, price: float, pts: list | None = None) -> dict:
    """pts verilirse swing noktaları yeniden aranmaz (backtest hızı için önceden hesaplanmış)."""
    atr = last_atr(df)
    clusters = _cluster(swing_points(df, FRACTAL[tf]) if pts is None else pts, df, 0.5 * atr)
    top = max((s for _, s in clusters), default=1.0)
    norm = [(p, round(100 * s / top, 1), 1) for p, s in clusters]

    supports = sorted((l for l in norm if l[0] < price), key=lambda l: l[1], reverse=True)[:PER_SIDE]
    resistances = sorted((l for l in norm if l[0] > price), key=lambda l: l[1], reverse=True)[:PER_SIDE]
    return {
        "tf": tf,
        "atr": atr,
        # (fiyat, güç 0-100, kaç TF'de var) — en yakından uzağa
        "supports": sorted(supports, key=lambda l: -l[0]),
        "resistances": sorted(resistances, key=lambda l: l[0]),
    }


def annotate_confluence(levels_by_tf: dict[str, dict], tol: float) -> None:
    """Her seviyenin 3. alanını, tol içinde seviyesi olan TF sayısıyla günceller (yerinde)."""
    all_prices = {
        tf: [l[0] for l in lv["supports"] + lv["resistances"]] for tf, lv in levels_by_tf.items()
    }
    for tf, lv in levels_by_tf.items():
        for side in ("supports", "resistances"):
            updated = []
            for p, s, _ in lv[side]:
                count = 1 + sum(
                    any(abs(p - q) <= tol for q in prices)
                    for other, prices in all_prices.items() if other != tf
                )
                updated.append((p, s, count))
            lv[side] = updated
