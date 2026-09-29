"""Backtest: `python scripts/backtest.py [--days 1000] [--test-days 730] [--send]`

Kripto evrenini (hacim filtresi + coins.yaml) geçmişte yeniden oynatır, ayar setlerini karşılaştırır.
Çıktılar: data/backtest_*.png, tracking/backtest.md (repoda saklanır), --send ile Telegram'a.
"""
import argparse
import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from core import ROOT, backtest, chart, data, onchain, settings  # noqa: E402

TZ = ZoneInfo("Europe/Istanbul")
LIVE = {"regime_filter": True, "entry_mode": "market", "horizon_h": 24, "buy_threshold": 65,
        "sell_threshold": 35, "cand_min_rr": 2.0}


async def universe(n: int) -> list[str]:
    try:
        top = await data.top_by_volume(n, settings.get("min_volume_usd"))
    finally:
        await data.close()
    return list(dict.fromkeys(["BTC"] + top + onchain.manual_coins()))


def fmt(s: dict) -> str:
    if not s["trades"]:
        return "işlem yok"
    pf = "—" if s["profit_factor"] is None else f"{s['profit_factor']:.2f}"
    return (f"{s['trades']} işlem · kazanma %{s['win_rate']:.0f} · beklenti {s['expectancy']:+.2f}R · "
            f"toplam {s['total_r']:+.0f}R · PF {pf} · düşüş %{s['max_dd']:.1f}")


def is_live(r: dict) -> bool:
    return not r.get("old_norm") and all(r[k] == v for k, v in LIVE.items())


def equity_chart(rows: list[tuple[str, dict, str]], split_ts: int, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(16, 8), dpi=100, facecolor=chart.BG)
    chart._style_ax(ax)
    for label, stats, color in rows:
        c = stats["all"]["curve"]
        if c:
            ax.plot([datetime.fromtimestamp(t, TZ) for t, _ in c], [e for _, e in c], label=label, color=color, lw=2)
    ax.axvline(datetime.fromtimestamp(split_ts, TZ), color=chart.YELLOW, ls="--", lw=1.2)
    ax.text(datetime.fromtimestamp(split_ts, TZ), ax.get_ylim()[1], "  ← eğitim | test (hiç dokunulmamış) →",
            color=chart.YELLOW, va="top", fontsize=11)
    ax.axhline(1000, color=chart.GRID, ls=":")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f} $".replace(",", ".")))
    ax.legend(facecolor=chart.PANEL, edgecolor=chart.GRID, labelcolor=chart.TEXT, loc="upper left")
    ax.set_title("Backtest — sanal hesap (1.000 $, işlem başı %1 risk, bileşik)", color=chart.TEXT, fontsize=15, loc="left")
    fig.savefig(path, facecolor=chart.BG, bbox_inches="tight")
    plt.close(fig)


def table_chart(results: list[dict], power: dict, path: Path) -> None:
    top = sorted((r for r in results if r["stats"]["is"]["trades"] >= 30),
                 key=lambda r: (r["stats"]["is"]["expectancy"] or -9) * r["stats"]["is"]["trades"] ** 0.5,
                 reverse=True)[:12]
    fig = plt.figure(figsize=(20, 11), dpi=100, facecolor=chart.BG)
    ax = fig.add_axes([0.01, 0.30, 0.98, 0.62])
    ax.axis("off")
    cell = lambda s: "—" if not s["trades"] else f"{s['trades']} · {s['expectancy']:+.2f}R · %{s['max_dd']:.0f}"  # noqa: E731
    rows = [[r["name"], cell(r["stats"]["is"]), cell(r["stats"]["oos"]),
             f"{r['stats']['oos']['total_r']:+.0f}R" if r["stats"]["oos"]["trades"] else "—"] for r in top]
    tbl = ax.table(cellText=rows, colLabels=["Ayar seti", "EĞİTİM: işlem · beklenti · düşüş",
                                             "TEST: işlem · beklenti · düşüş", "TEST toplam"],
                   loc="upper center", cellLoc="center", colWidths=[0.42, 0.22, 0.22, 0.1])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(11)
    tbl.scale(1, 1.8)
    for (row, col), c in tbl.get_celld().items():
        c.set_edgecolor(chart.GRID)
        c.set_facecolor("#232937" if row == 0 else chart.PANEL)
        c.set_text_props(color=chart.TEXT, fontweight="bold" if row == 0 else "normal")
        if row and col in (1, 2, 3):
            s = top[row - 1]["stats"]["is" if col == 1 else "oos"]
            if s["trades"]:
                c.set_text_props(color=chart.GREEN if s["expectancy"] > 0 else chart.RED)
    fig.text(0.5, 0.96, "En iyi 12 ayar seti (sıralama sadece EĞİTİM dönemine göre)", color=chart.TEXT,
             ha="center", fontsize=16, fontweight="bold")

    ax2 = fig.add_axes([0.08, 0.05, 0.86, 0.2])
    chart._style_ax(ax2)
    comps = list(power["is"])
    x = range(len(comps))
    ax2.bar([i - 0.2 for i in x], [power["is"][c] for c in comps], 0.4, color=chart.BLUE, label="eğitim")
    ax2.bar([i + 0.2 for i in x], [power["oos"][c] for c in comps], 0.4, color=chart.YELLOW, label="test")
    ax2.axhline(0, color=chart.GRID)
    ax2.set_xticks(list(x), comps)
    ax2.legend(facecolor=chart.PANEL, edgecolor=chart.GRID, labelcolor=chart.TEXT)
    ax2.set_title("Bileşenlerin tahmin gücü (24 saat sonraki hareketle sıra korelasyonu; + = doğru yönü gösteriyor)",
                  color=chart.TEXT, fontsize=12, loc="left")
    fig.savefig(path, facecolor=chart.BG)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1000)
    ap.add_argument("--test-days", type=int, default=730)
    ap.add_argument("--coins", type=int, default=30)
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--funding", action="store_true", help="seçilen strateji ailesinde fonlama oranı bileşenini dene")
    a = ap.parse_args()
    if a.funding:
        return funding_experiment(a)

    t0 = time.time()
    symbols = asyncio.run(universe(a.coins))
    print(f"evren ({len(symbols)}): {', '.join(symbols)}")
    base_cfg = settings.all_settings()
    m15s = asyncio.run(backtest._load_and_close(symbols, a.days))
    print(f"veri: {len(m15s)} coin, {time.time() - t0:.0f}s")
    built = backtest.build(m15s, a.test_days)
    by_ts, snaps, _regimes, _arrays, split = built
    print(f"anlık görüntü: {len(snaps)} ({len(by_ts)} adım), {time.time() - t0:.0f}s")
    results = backtest.run_all(built, base_cfg)
    power = backtest.component_power(snaps, split)
    print(f"varyantlar: {len(results)}, {time.time() - t0:.0f}s")

    old = next(r for r in results if r.get("old_norm"))
    live = next(r for r in results if is_live(r))
    best = backtest.pick_best(results)
    lines = [f"# Backtest — {datetime.now(TZ):%d.%m.%Y %H:%M}", "",
             f"- Dönem: son {a.test_days} gün, her 4 saatte bir adım · {len(m15s)} coin · eğitim/test ayrımı "
             f"{datetime.fromtimestamp(split, TZ):%d.%m.%Y}",
             f"- Evren: {', '.join(m15s)}", "",
             "| Ayar seti | Eğitim | Test (dokunulmamış) |", "|---|---|---|"]
    for label, r in (("ESKİ", old), ("YENİ varsayılan", live), ("EN İYİ (eğitime göre)", best)):
        if r:
            lines.append(f"| **{label}**: {r['name']} | {fmt(r['stats']['is'])} | {fmt(r['stats']['oos'])} |")
    lines += ["", "Bileşen tahmin gücü (Spearman, 24s ileri getiri/ATR):", "",
              "| Bileşen | Eğitim | Test |", "|---|---|---|"]
    lines += [f"| {c} | {power['is'][c]:+.3f} | {power['oos'][c]:+.3f} |" for c in power["is"]]
    report = "\n".join(lines)
    print(report)
    (ROOT / "tracking").mkdir(exist_ok=True)
    (ROOT / "tracking" / "backtest.md").write_text(report + "\n", encoding="utf-8")

    rows = [("ESKİ", old["stats"], chart.RED), ("YENİ varsayılan", live["stats"], chart.BLUE)]
    if best and best is not live:
        rows.append((f"EN İYİ: {best['name']}", best["stats"], chart.GREEN))
    equity_chart(rows, split, ROOT / "data" / "backtest_equity.png")
    table_chart(results, power, ROOT / "data" / "backtest_table.png")
    print(f"bitti: {time.time() - t0:.0f}s")

    if a.send:
        from telegram import Bot
        from bot.auth import allowed_chat_id

        async def send():
            async with Bot(os.environ["TELEGRAM_BOT_TOKEN"]) as bot:
                cid = allowed_chat_id()
                for name, cap in (("backtest_equity.png", "📈 Backtest — sermaye eğrileri"),
                                  ("backtest_table.png", "📋 Backtest — ayar setleri ve bileşen gücü")):
                    await bot.send_photo(cid, (ROOT / "data" / name).read_bytes(), caption=cap, write_timeout=120)
        asyncio.run(send())


def funding_experiment(a) -> None:
    t0 = time.time()
    symbols = asyncio.run(universe(a.coins))
    base_cfg = settings.all_settings()
    m15s = asyncio.run(backtest._load_and_close(symbols, a.days))
    built = backtest.build(m15s, a.test_days)
    by_ts, snaps, _regimes, _arrays, split = built
    funding = asyncio.run(backtest.fetch_funding(list(m15s), a.days))
    added = backtest.inject_funding(snaps, funding)
    print(f"fonlama: {len(funding)} coin, {added}/{len(snaps)} anlık görüntüye eklendi, {time.time() - t0:.0f}s")
    results = backtest.run_all(built, base_cfg, backtest.focus_grid(base_cfg["weights"]))
    power = backtest.component_power(snaps, split)
    lines = [f"# Fonlama oranı deneyi — {datetime.now(TZ):%d.%m.%Y %H:%M}", "",
             f"- {len(m15s)} coin, son {a.test_days} gün, eğitim/test ayrımı {datetime.fromtimestamp(split, TZ):%d.%m.%Y}",
             "", "| Ayar seti | Eğitim | Test |", "|---|---|---|"]
    lines += [f"| {r['name']} | {fmt(r['stats']['is'])} | {fmt(r['stats']['oos'])} |" for r in results]
    lines += ["", "| Bileşen | Tahmin gücü eğitim | test |", "|---|---|---|"]
    lines += [f"| {c} | {power['is'][c]:+.3f} | {power['oos'][c]:+.3f} |" for c in power["is"]]
    report = "\n".join(lines)
    print(report)
    (ROOT / "tracking" / "backtest_funding.md").write_text(report + "\n", encoding="utf-8")
    print(f"bitti: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
