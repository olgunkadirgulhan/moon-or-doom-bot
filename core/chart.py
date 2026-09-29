"""2×2 coin grafiği ve özet tablo PNG'leri (koyu tema)."""
import io
import math
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mplfinance as mpf  # noqa: E402

BG = "#0f1115"
PANEL = "#161a22"
GRID = "#2a2f3a"
TEXT = "#d8dde6"
GREEN = "#26a69a"
RED = "#ef5350"
BLUE = "#42a5f5"
YELLOW = "#ffca28"
ORANGE = "#ffa726"
LAYOUT = [("1h", 0, 0), ("4h", 0, 1), ("8h", 1, 0), ("1d", 1, 1)]
BARS = 120
TZ = ZoneInfo("Europe/Istanbul")

# matplotlib thread-safe değil; to_thread içinden tek tek çizdir
_lock = threading.Lock()

STYLE = mpf.make_mpf_style(
    base_mpf_style="nightclouds",
    marketcolors=mpf.make_marketcolors(up=GREEN, down=RED, edge="inherit", wick="inherit"),
    facecolor=PANEL,
    figcolor=BG,
    gridcolor=GRID,
    gridstyle=":",
    rc={"axes.labelcolor": TEXT, "xtick.color": TEXT, "ytick.color": TEXT, "font.size": 9},
)


def fmt_price(p: float) -> str:
    if p is None or not math.isfinite(p) or p <= 0:
        return "—"
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.2f}" if p >= 100 else f"{p:.3f}"
    decimals = min(10, 3 - int(math.floor(math.log10(p))))
    return f"{p:.{decimals}f}"


def fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else "-"
    a = abs(v)
    if a >= 1e9:
        return f"{sign}${a / 1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:.0f}K"
    return f"{sign}${a:.0f}"


def side_label(r: dict) -> str:
    return "LONG" if r["side"] == "long" else "SHORT"


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def _draw_tf(ax, df, tf: str, lv: dict, res: dict) -> None:
    d = df.tail(BARS)
    aps = [
        mpf.make_addplot(d["ema50"], ax=ax, color=YELLOW, width=0.9),
        mpf.make_addplot(d["ema200"], ax=ax, color="#ab47bc", width=0.9),
    ]
    aps = [a for a, col in zip(aps, ("ema50", "ema200")) if d[col].notna().any()]
    mpf.plot(d, ax=ax, type="candle", style=STYLE, addplot=aps, xrotation=0,
             datetime_format="%d.%m %H:%M" if tf != "1d" else "%d.%m", warn_too_much_data=10_000)

    lo, hi = float(d["Low"].min()), float(d["High"].max())
    span = hi - lo
    view_lo, view_hi = lo - 0.15 * span, hi + 0.15 * span
    x_end = len(d) - 1

    for side, color in (("supports", GREEN), ("resistances", RED)):
        for p, _s, conf in lv[side]:
            if view_lo <= p <= view_hi:
                ax.axhline(p, color=color, lw=2.6 if conf >= 2 else 1.0, alpha=0.85 if conf >= 2 else 0.6)

    trade = [("Giriş", res["entry"], BLUE), ("SL", res["sl"], RED),
             ("TP1", res["tp1"], GREEN), ("TP2", res["tp2"], GREEN)]
    shown = sorted((t for t in trade if view_lo <= t[1] <= view_hi), key=lambda t: t[1])
    # yakın etiketler çakışmasın: her etiketi bir öncekinden en az min_gap yukarı it
    min_gap = 0.05 * (view_hi - view_lo)
    label_y = None
    for name, p, color in shown:
        ax.axhline(p, color=color, ls="--", lw=1.2)
        label_y = p if label_y is None else max(p, label_y + min_gap)
        ax.text(x_end, label_y, f" {name} {fmt_price(p)} ", color=color, fontsize=8,
                va="center", ha="right",
                bbox={"facecolor": BG, "alpha": 0.75, "edgecolor": "none", "pad": 1})
        view_hi = max(view_hi, label_y + min_gap / 2)

    ax.set_ylim(view_lo, view_hi)
    ax.set_title(tf.upper(), color=TEXT, fontsize=11, loc="left")
    ax.set_ylabel("")


def _draw_netflow(ax, onchain: dict) -> None:
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=TEXT, labelsize=8)
    for s in ax.spines.values():
        s.set_color(GRID)
    daily = onchain.get("daily") or []
    if not onchain.get("available") or not daily:
        reason = onchain.get("reason", "on-chain yok")
        ax.text(0.5, 0.5, f"on-chain yok ({reason})" if reason != "on-chain yok" else reason,
                color=TEXT, ha="center", va="center", transform=ax.transAxes, fontsize=9)
        ax.set_xticks([])
        ax.set_yticks([])
        return
    labels = [d for d, _ in daily]
    vals = [v for _, v in daily]
    ax.bar(range(len(vals)), vals, color=[GREEN if v >= 0 else RED for v in vals])
    ax.axhline(0, color=GRID, lw=0.8)
    ax.set_xticks(range(len(vals)), labels)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt_usd(v)))
    ax.set_title("Günlük borsa netflow (çıkış − giriş)", color=TEXT, fontsize=9, loc="left")


def coin_chart(res: dict) -> bytes:
    """res: scanner.analyze çıktısı (frames, levels, onchain dahil)."""
    with _lock:
        fig = mpf.figure(style=STYLE, figsize=(16, 12), dpi=100)
        gs = fig.add_gridspec(2, 2, hspace=0.22, wspace=0.12, left=0.05, right=0.97, top=0.92, bottom=0.05)
        for tf, r, c in LAYOUT:
            if tf == "4h":
                sub = gs[r, c].subgridspec(2, 1, height_ratios=[3, 1], hspace=0.35)
                ax = fig.add_subplot(sub[0])
                _draw_netflow(fig.add_subplot(sub[1]), res.get("onchain", {}))
            else:
                ax = fig.add_subplot(gs[r, c])
            _draw_tf(ax, res["frames"][tf], tf, res["levels"][tf], res)

        color = {"AL": GREEN, "SAT": RED}.get(res["signal"], YELLOW)
        rr = f"R:R {res['rr']:.1f}" + ("  (R:R düşük!)" if res["rr_low"] else "")
        fig.suptitle(f"{res['symbol']} — {res['signal']} ({side_label(res)}) — Skor {res['score']:.0f} — {rr}",
                     color=color, fontsize=18, fontweight="bold")
        fig.text(0.97, 0.935, f"Fiyat {fmt_price(res['price'])}  ·  "
                 f"{datetime.now(TZ):%d.%m.%Y %H:%M}", color=TEXT, ha="right", fontsize=10)
        return _png(fig)


LIQ_BUFFER = 0.9  # teminatın %90'ı gidince borsa pozisyonu kapatır (bakım teminatı payı, yaklaşık)


def usd_exact(v: float) -> str:
    """+1.650 $ biçimi (Türkçe binlik ayırıcı)."""
    return ("+" if v >= 0 else "−") + f"{abs(v):,.0f}".replace(",", ".") + " $"


def trade_pnl(r: dict, price: float, margin: float, leverage: float) -> float:
    """Güncel fiyattan açılan pozisyonun `price`'ta kapanması halinde $ kâr/zarar (ücretler hariç)."""
    move = (price - r["entry"]) / r["entry"]
    return margin * leverage * (move if r["side"] == "long" else -move)


def summary_table(results: list[dict], title: str = "Moon or Doom — Sinyal Özeti",
                  margin: float = 1000, leverage: float = 10) -> bytes:
    headers = ["#", "Coin", "Sinyal", "Yön", "Skor", "Giriş", "SL", "TP1", "TP2", "R:R", "Netflow 24s",
               "TP1 kâr", "TP2 kâr", "SL zarar"]
    liq_loss = -margin * LIQ_BUFFER
    rows, liquidated = [], []
    for i, r in enumerate(results, 1):
        oc = r.get("onchain", {})
        sl_loss = trade_pnl(r, r["sl"], margin, leverage)
        liq = sl_loss <= liq_loss
        liquidated.append(liq)
        rows.append([
            str(i), r["symbol"], r["signal"], side_label(r), f"{r['score']:.0f}",
            fmt_price(r["entry"]), fmt_price(r["sl"]), fmt_price(r["tp1"]), fmt_price(r["tp2"]),
            f"{r['rr']:.1f}" + (" ⚠" if r["rr_low"] else ""),
            fmt_usd(oc.get("netflow_24h")) if oc.get("available") else "—",
            usd_exact(trade_pnl(r, r["tp1"], margin, leverage)),
            usd_exact(trade_pnl(r, r["tp2"], margin, leverage)),
            f"LİKİDE {usd_exact(-margin)}" if liq else usd_exact(sl_loss),
        ])

    with _lock:
        footer_h = 1.0
        height = 1.1 + 0.33 * (len(rows) + 1) + footer_h
        fig = plt.figure(figsize=(20, height), dpi=100, facecolor=BG)
        ax = fig.add_axes([0.01, footer_h / height, 0.98, 1 - (0.95 + footer_h) / height])
        ax.axis("off")
        tbl = ax.table(cellText=rows, colLabels=headers, loc="upper center", cellLoc="center",
                       colWidths=[0.03, 0.06, 0.06, 0.06, 0.045, 0.1, 0.1, 0.1, 0.1, 0.055, 0.08,
                                  0.07, 0.07, 0.1])
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(12)
        tbl.scale(1, 1.9)
        sig_color = {"AL": GREEN, "SAT": RED, "BEKLE": YELLOW}
        for (row, col), cell in tbl.get_celld().items():
            cell.set_edgecolor(GRID)
            cell.set_text_props(color=TEXT)
            if row == 0:
                cell.set_facecolor("#232937")
                cell.set_text_props(color=TEXT, fontweight="bold")
                continue
            cell.set_facecolor(PANEL if row % 2 else "#1b202a")
            r = results[row - 1]
            if col == 2:
                cell.set_text_props(color=sig_color[r["signal"]], fontweight="bold")
            elif col == 3:
                cell.set_text_props(color=GREEN if r["side"] == "long" else RED)
            elif col == 9 and r["rr_low"]:
                cell.set_text_props(color=ORANGE)
            elif col == 10 and r.get("onchain", {}).get("available"):
                nf = r["onchain"].get("netflow_24h") or 0
                cell.set_text_props(color=GREEN if nf >= 0 else RED)
            elif col in (11, 12):
                cell.set_text_props(color=GREEN, fontweight="bold")
            elif col == 13:
                cell.set_text_props(color=RED, fontweight="bold")
                if liquidated[row - 1]:
                    cell.set_facecolor("#4a1c1c")
        fig.text(0.5, 1 - 0.55 / height, f"{title}  ·  {datetime.now(TZ):%d.%m.%Y %H:%M} (İstanbul)",
                 color=TEXT, ha="center", va="center", fontsize=15, fontweight="bold")

        pos = margin * leverage
        liq_pct = 100 * LIQ_BUFFER / leverage
        usd = lambda v: f"{v:,.0f}".replace(",", ".") + " $"  # noqa: E731
        fig.text(0.012, (footer_h - 0.15) / height, "\n".join([
            f"Kâr/zarar hesabı: {usd(margin)} teminat × {leverage:g}x kaldıraç = {usd(pos)} pozisyon, "
            f"giriş güncel fiyattan. Fiyatın lehine her %1 hareketi ≈ +{usd(pos / 100)}, "
            f"aleyhine her %1 hareketi ≈ −{usd(pos / 100)}.",
            f"TP1/TP2 kâr = hedefe ulaşınca kazanç · SL zarar = stop olunca kayıp. "
            f"Fiyat yaklaşık %{liq_pct:.0f} ters giderse pozisyon LİKİDE olur ve teminatın tamamı "
            f"({usd(margin)}) gider; SL bundan uzaksa kırmızı 'LİKİDE' yazar.",
            "Komisyon ve fonlama ücreti dahil değildir. Yatırım tavsiyesi değildir.",
        ]), color=TEXT, fontsize=11, va="top", ha="left", linespacing=1.6, parse_math=False)
        return _png(fig)


def _style_ax(ax) -> None:
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=TEXT)
    for s in ax.spines.values():
        s.set_color(GRID)


def _acc_text(s: dict) -> str:
    return "—" if s["accuracy"] is None else f"%{s['accuracy']:.0f}"


def result_chart(summary: dict, title: str) -> bytes:
    """Dönem isabeti: genel pasta, grup bazlı çubuklar, gün gün doğruluk çizgisi, en iyi/kötü tahminler."""
    o = summary["overall"]
    with _lock:
        fig = plt.figure(figsize=(16, 11), dpi=100, facecolor=BG)
        gs = fig.add_gridspec(2, 2, width_ratios=[1, 1.5], hspace=0.35, wspace=0.2,
                              left=0.05, right=0.97, top=0.88, bottom=0.06)

        # 1) genel dağılım
        ax = fig.add_subplot(gs[0, 0])
        ax.set_facecolor(BG)
        vals = [o["tp"], o["sl"], o["open"]]
        if sum(vals):
            ax.pie(vals, colors=[GREEN, RED, "#607d8b"], startangle=90, counterclock=False,
                   wedgeprops={"width": 0.35, "edgecolor": BG})
        ax.text(0, 0.1, _acc_text(o), color=TEXT, ha="center", va="center", fontsize=30, fontweight="bold")
        ax.text(0, -0.2, "doğruluk", color=TEXT, ha="center", va="center", fontsize=11)
        ax.set_title(f"✓ Hedef {o['tp']}   ✗ Stop {o['sl']}   ○ Açık {o['open']}",
                     color=TEXT, fontsize=13)

        # 2) gruplar
        ax = fig.add_subplot(gs[0, 1])
        _style_ax(ax)
        names = list(summary["groups"])
        g = [summary["groups"][n] for n in names]
        y = range(len(names))[::-1]
        tp = [s["tp"] for s in g]
        sl = [s["sl"] for s in g]
        op = [s["open"] for s in g]
        ax.barh(y, tp, color=GREEN, label="Hedef (TP1)")
        ax.barh(y, sl, left=tp, color=RED, label="Stop (SL)")
        ax.barh(y, op, left=[a + b for a, b in zip(tp, sl)], color="#607d8b", label="Açık")
        ax.set_yticks(list(y), names, color=TEXT, fontsize=11)
        for yi, s in zip(y, g):
            ax.text(s["total"], yi, f"  {_acc_text(s)}  ({s['tp']}/{s['tp'] + s['sl']})",
                    color=TEXT, va="center", fontsize=11)
        ax.set_xlim(0, max([s["total"] for s in g] + [1]) * 1.3)
        ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, loc="lower right")
        ax.set_title("Gruplara göre sonuç (doğruluk = hedef ÷ (hedef + stop))", color=TEXT, fontsize=12, loc="left")

        # 3) gün gün doğruluk
        ax = fig.add_subplot(gs[1, 0])
        _style_ax(ax)
        days = [(d, s) for d, s in summary["by_day"] if s["accuracy"] is not None]
        if days:
            ax.plot([d for d, _ in days], [s["accuracy"] for _, s in days], color=BLUE, marker="o")
            ax.axhline(50, color=GRID, ls="--", lw=1)
            ax.set_ylim(0, 100)
            ax.tick_params(axis="x", labelrotation=45)
        else:
            ax.text(0.5, 0.5, "Henüz sonuçlanan tahmin yok", color=TEXT, ha="center", transform=ax.transAxes)
        ax.set_title("Günlere göre doğruluk %", color=TEXT, fontsize=12, loc="left")

        # 4) en iyi / en kötü
        ax = fig.add_subplot(gs[1, 1])
        ax.set_facecolor(BG)
        ax.axis("off")
        closed = sorted((i for i in summary["items"] if i["outcome"] != "OPEN"), key=lambda i: -i["pnl"])
        best, worst = closed[:6], [i for i in closed[::-1] if i["pnl"] < 0][:6]

        def line(i):
            mark = "✓" if i["outcome"] == "TP" else "✗"
            t = datetime.fromtimestamp(i["ts"], TZ).strftime("%d.%m %H:%M")
            tp2 = " (TP2)" if i["tp2_hit"] else ""
            return f"{mark} {i['symbol']:<6} {i['side'].upper():<5} {t} {i['pnl']:+.1f}%{tp2}"

        ax.text(0.0, 1.0, "En iyi sonuçlar", color=GREEN, fontsize=13, fontweight="bold", va="top")
        ax.text(0.0, 0.9, "\n".join(map(line, best)) or "—", color=TEXT, fontsize=11,
                va="top", family="monospace")
        ax.text(0.52, 1.0, "En kötü sonuçlar", color=RED, fontsize=13, fontweight="bold", va="top")
        ax.text(0.52, 0.9, "\n".join(map(line, worst)) or "—", color=TEXT, fontsize=11,
                va="top", family="monospace")

        fig.suptitle(title, color=TEXT, fontsize=20, fontweight="bold")
        fig.text(0.5, 0.925, f"{o['total']} tahmin · {summary['coins']} farklı coin · her tahmin 24 saat "
                 "izlendi: önce TP1 ✓, önce SL ✗, hiçbiri açık",
                 color=TEXT, ha="center", fontsize=11)
        return _png(fig)
