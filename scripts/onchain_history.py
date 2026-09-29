"""Geçmiş on-chain verisiyle tahmin gücü + backtest: `python scripts/onchain_history.py [--days 365]`

1) coins.yaml'daki Ethereum tokenları için borsa cüzdanlarının geçmiş transferlerini indirir (önbellekli)
2) Her 4 saatte bir canlıdakiyle aynı on-chain skorunu yeniden hesaplar (sadece eksiksiz kapsanan dönemde)
3) Skorun 24s / 72s sonraki getiriyle sıra korelasyonunu ölçer (eğitim / test ayrı)
4) Seçilen strateji ailesinde on-chain ağırlığı 0/10/20/30 ile backtest (sadece kapsanan dönem)
Sonuç: tracking/onchain_history.md
"""
import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core import ROOT, backtest, data, onchain, onchain_history, settings  # noqa: E402

TZ = ZoneInfo("Europe/Istanbul")
d = lambda ts: datetime.fromtimestamp(ts, TZ).strftime("%d.%m.%Y")  # noqa: E731


def fwd_return(m15: pd.DataFrame, steps: list[int], hours: int) -> np.ndarray:
    t = m15.index.as_unit("s").asi8
    c = m15["Close"].to_numpy()
    i0 = np.clip(np.searchsorted(t, steps, side="left") - 1, 0, len(c) - 1)
    i1 = np.searchsorted(t, np.array(steps) + hours * 3600, side="left") - 1
    out = np.full(len(steps), np.nan)
    ok = i1 < len(c)
    out[ok] = 100 * (c[i1[ok]] / c[i0[ok]] - 1)
    return out


def spearman(a: pd.Series, b: pd.Series) -> float:
    return float(a.rank().corr(b.rank()))


async def download(tokens: list[str], days: int):
    since = int(time.time()) - days * 86400
    flows, m15s = {}, {}
    try:
        for s in tokens:
            t0 = time.time()
            res = await onchain_history.token_flows(s, since)
            if res is None:
                continue
            df, covered, n_w = res
            flows[s] = (df, covered)
            print(f"  {s:6} {len(df):7} borsa transferi · {n_w} cüzdan · eksiksiz kapsam {d(covered)} → bugün "
                  f"({(time.time() - covered) / 86400:.0f} gün) · {time.time() - t0:.0f}s", flush=True)
            m15s[s] = await backtest.fetch_15m(s, max(days, 400) + 30)
    finally:
        await data.close()
    return flows, m15s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--no-backtest", action="store_true")
    a = ap.parse_args()
    t0 = time.time()

    tokens = [s for s, i in (onchain._coins().get("tokens") or {}).items() if int(i["chainid"]) == 1]
    print(f"Ethereum tokenları ({len(tokens)}): {', '.join(tokens)}")
    flows, m15s = asyncio.run(download(tokens, a.days))

    now = int(time.time()) // backtest.STEP * backtest.STEP - 3 * 86400
    rows, values = [], {}
    for s, (df, covered) in flows.items():
        steps = list(range((covered // backtest.STEP + 1) * backtest.STEP + 86400, now, backtest.STEP))
        if len(steps) < 30:
            continue
        sc = onchain_history.score_series(df, m15s[s], steps)
        values[s] = {T: v / 100 for T, v in zip(steps, sc) if v == v}
        rows.append(pd.DataFrame({"symbol": s, "ts": steps, "score": sc,
                                  "fwd24": fwd_return(m15s[s], steps, 24), "fwd72": fwd_return(m15s[s], steps, 72)}))
    panel = pd.concat(rows).dropna()
    split = int(panel["ts"].quantile(0.6))
    lines = [f"# Geçmiş on-chain analizi — {datetime.now(TZ):%d.%m.%Y %H:%M}", "",
             f"- {len(values)} token, {len(panel)} gözlem (4 saatte bir), eğitim/test ayrımı {d(split)}",
             "- Skor: canlıdakiyle aynı (son 24s borsa net akışı ÷ %5 × 24s hacim, ±100). + = borsadan çıkış (birikim)",
             "", "## Tahmin gücü (sıra korelasyonu, + = skor doğru yönü gösteriyor)", "",
             "| | 24s sonrası | 72s sonrası | gözlem |", "|---|---|---|---|"]
    for label, sub in (("Eğitim", panel[panel.ts < split]), ("Test", panel[panel.ts >= split]), ("Tümü", panel)):
        lines.append(f"| {label} | {spearman(sub.score, sub.fwd24):+.3f} | {spearman(sub.score, sub.fwd72):+.3f} | {len(sub)} |")
    lines += ["", "| Token | 24s | 72s | gözlem | kapsam başlangıcı |", "|---|---|---|---|---|"]
    for s, sub in panel.groupby("symbol"):
        lines.append(f"| {s} | {spearman(sub.score, sub.fwd24):+.3f} | {spearman(sub.score, sub.fwd72):+.3f} | "
                     f"{len(sub)} | {d(flows[s][1])} |")
    # uç değerler: güçlü birikim / güçlü dağıtım sonrası ortalama getiri
    lines += ["", "## Uç skorlardan sonra ortalama getiri (%)", "", "| Skor | 24s | 72s | gözlem |", "|---|---|---|---|"]
    for label, mask in (("≥ +50 (güçlü çıkış)", panel.score >= 50), ("−50…+50", panel.score.abs() < 50),
                        ("≤ −50 (güçlü giriş)", panel.score <= -50)):
        sub = panel[mask]
        lines.append(f"| {label} | {sub.fwd24.mean():+.2f} | {sub.fwd72.mean():+.2f} | {len(sub)} |")

    if not a.no_backtest:
        print("backtest hazırlanıyor…", flush=True)
        base_cfg = settings.all_settings()
        symbols = list(dict.fromkeys(["BTC"] + list(values)))
        bt_m15 = asyncio.run(backtest._load_and_close(symbols, 1000))
        start = int(panel["ts"].min())
        built = backtest.build(bt_m15, (now - start) // 86400 + 3)
        by_ts, snaps, regimes, arrays, _ = built
        added = backtest.inject_component(snaps, "onchain", values)
        cut = int(panel["ts"].quantile(0.6))
        results = backtest.run_all((by_ts, snaps, regimes, arrays, cut), base_cfg,
                                   backtest.focus_grid(base_cfg["weights"], "onchain", "on-chain"))
        lines += ["", f"## Backtest (sadece on-chain tokenları + BTC, {d(start)} → bugün, {added} anlık görüntüde skor var)",
                  "", "| Ayar seti | Eğitim | Test |", "|---|---|---|"]
        fmt = lambda s: "işlem yok" if not s["trades"] else (  # noqa: E731
            f"{s['trades']} işlem · %{s['win_rate']:.0f} · {s['expectancy']:+.2f}R · toplam {s['total_r']:+.0f}R · düşüş %{s['max_dd']:.0f}")
        lines += [f"| {r['name']} | {fmt(r['stats']['is'])} | {fmt(r['stats']['oos'])} |" for r in results]

    report = "\n".join(lines)
    print(report)
    (ROOT / "tracking" / "onchain_history.md").write_text(report + "\n", encoding="utf-8")
    print(f"bitti: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
