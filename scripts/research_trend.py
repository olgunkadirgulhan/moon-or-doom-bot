"""Trend ailelerinin araştırma backtesti: `python scripts/research_trend.py [--days 1000]`

Aynı veri (data/bt önbelleği), aynı çıkış simülasyonu (tracker._simulate / trend.simulate_trail), aynı hesap kuralları
(tracker.account: max 3 açık, aynı yönde max 2, %1 risk). Dönemin ilk %60'ı eğitim, son %40'ı test.
Çıktı: tracking/research_trend.md
"""
import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from core import ROOT, backtest, settings, tracker, trend  # noqa: E402

SYMS = ("BTC ETH ZEC SOL XRP NEAR HBAR QNT SUI LINK UNI BNB DOGE XLM WLD AVAX ENA ONDO ADA TAO LTC ALGO AAVE PEPE "
        "DASH TRX").split()


def sim(p, arr, d1):
    candles = backtest._candles(arr, p["ts"], p["ts"] + p["horizon_h"] * 3600)
    if p["exit"] == "trail":
        return trend.simulate_trail(p, candles, d1)
    s = tracker._simulate(p, candles, p["horizon_h"] * 3600)
    s["r"] -= trend.SLIP_PCT / 100 * p["entry"] / abs(p["entry"] - p["sl"])
    return s


def raw(xs):
    rs = [x["r"] for x in xs]
    if not rs:
        return "işlem yok"
    g, l_ = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    pf = f"{g / l_:.2f}" if l_ else "—"
    t = np.mean(rs) / (np.std(rs) / len(rs) ** 0.5) if len(rs) > 2 and np.std(rs) else 0
    return f"{len(rs)} · kazanma %{100 * np.mean([r > 0 for r in rs]):.0f} · {np.mean(rs):+.2f}R · PF {pf} · t={t:.1f}"


def acct(xs, cfg):
    a = tracker.account(xs, cfg["capital_usd"], cfg["risk_pct"], cfg["max_open"], cfg["max_same_dir_crypto"])
    if not a["trades"]:
        return "işlem yok"
    return (f"{a['trades']} işlem · {a['expectancy']:+.2f}R · toplam {a['total_r']:+.0f}R · "
            f"düşüş %{a['max_dd']:.1f} · sermaye {a['equity']:.0f}$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1000)
    a = ap.parse_args()
    cfg = settings.defaults() if hasattr(settings, "defaults") else {k: settings.get(k) for k in
                                                                       ("capital_usd", "risk_pct", "max_open",
                                                                        "max_same_dir_crypto")}
    m15s = asyncio.run(backtest._load_and_close(SYMS, a.days))
    frames = {s: backtest._frames(df) for s, df in m15s.items()}
    btc_d1 = frames["BTC"]["1d"]
    btc_tr = (btc_d1.index.as_unit("s").asi8 + 86400, trend.daily_trend(btc_d1))
    arrays = {s: {"t": df.index.as_unit("ms").asi8,
                  "rows": np.column_stack([df.index.as_unit("ms").asi8,
                                           df[list(backtest.AGG)].to_numpy()]).tolist()} for s, df in m15s.items()}
    t0 = max(int(df.index[0].timestamp()) for df in m15s.values()) + 210 * 86400  # EMA200 ısınması
    t0 = min(t0, int(m15s["BTC"].index[0].timestamp()) + 260 * 86400)
    t1 = int(m15s["BTC"].index[-1].timestamp()) - 3 * 86400
    split = t0 + int((t1 - t0) * backtest.IS_SHARE)

    res = defaultdict(list)
    for s in m15s:
        for p in trend.plans(s, frames[s], btc_tr, start_ts=t0):
            if p["ts"] > t1:
                continue
            p.update(sim(p, arrays[s], frames[s]["1d"]))
            res[p["family"]].append(p)

    lines = ["# Trend aileleri araştırması", "",
             f"- {len(m15s)} coin · eğitim/test ayrımı {np.datetime64(split, 's')} · komisyon %{tracker.FEE_PCT} + "
             f"kayma %{trend.SLIP_PCT} · hesap: %{cfg['risk_pct']} risk, max {cfg['max_open']} açık", "",
             "| Aile | Eğitim (tüm sinyaller) | Test (tüm sinyaller) | Test (hesap kurallarıyla) |", "|---|---|---|---|"]
    for fam in trend.FAMILIES:
        xs = res.get(fam, [])
        is_, oos = [x for x in xs if x["ts"] < split], [x for x in xs if x["ts"] >= split]
        lines.append(f"| {fam} | {raw(is_)} | {raw(oos)} | {acct(oos, cfg)} |")
    combos = {"breakout+breakdown": ("breakout", "breakdown"), "hepsi": trend.FAMILIES,
              "pullback+breakout": ("pullback", "breakout")}
    for name, fams in combos.items():
        xs = [x for f in fams for x in res.get(f, [])]
        is_, oos = [x for x in xs if x["ts"] < split], [x for x in xs if x["ts"] >= split]
        lines.append(f"| **{name}** | {raw(is_)} | {raw(oos)} | {acct(oos, cfg)} |")
    # yıllara göre (rejim değişimine dayanıklılık)
    lines += ["", "Yıllara göre (tüm sinyaller):", "", "| Aile | " + " | ".join(
        str(y) for y in range(2023, 2027)) + " |", "|---|" + "---|" * 4]
    for fam in trend.FAMILIES:
        by = defaultdict(list)
        for x in res.get(fam, []):
            by[np.datetime64(x["ts"], "s").astype("datetime64[Y]").astype(int) + 1970].append(x)
        lines.append(f"| {fam} | " + " | ".join(raw(by.get(y, [])) for y in range(2023, 2027)) + " |")
    out = ROOT / "tracking" / "research_trend.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
