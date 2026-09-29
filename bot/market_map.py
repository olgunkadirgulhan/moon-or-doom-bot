"""Piyasa haritası: önemli varlıklar için destek/direnç bölgeleri, hazır işlem planı ve "neden şu an işlem yok".

Aday olmasa bile kullanıcı "nerede alınır, nerede satılır" sorusunun cevabını görsün diye her raporda gönderilir.
"""
import asyncio
import html

from telegram import Bot
from telegram.constants import ParseMode

from core import chart, signal, strategy

TF_TR = {"1h": "1s", "4h": "4s", "8h": "8s", "1d": "1g"}
TF_ORDER = ["1h", "4h", "8h", "1d"]
ICON = {"BTC": "₿", "ETH": "Ξ", "ALTIN_GR_TL": "🥇", "GUMUS_GR_TL": "🥈", "BIST100": "🏛"}


def unit(res: dict) -> str:
    name = res.get("name") or res["symbol"]
    if "₺" in name:
        return " ₺"
    if "$" in name or res.get("market") == "crypto":
        return " $"
    return " TL" if res.get("market") == "bist" else ""


def key_levels(res: dict, n: int = 3) -> tuple[list[dict], list[dict]]:
    """Tüm zaman dilimlerindeki seviyeleri birleştirir: (destekler yakından uzağa, dirençler yakından uzağa)."""
    price, tol = res["price"], 0.5 * res["atr"]
    pts = sorted((p, s, tf) for tf, lv in res["levels"].items() for side in ("supports", "resistances")
                 for p, s, _c in lv[side])
    groups: list[list] = []
    for pt in pts:
        if groups and pt[0] - groups[-1][-1][0] <= tol:
            groups[-1].append(pt)
        else:
            groups.append([pt])
    levels = [{"price": sum(p for p, _, _ in g) / len(g), "tfs": sorted({tf for _, _, tf in g}, key=TF_ORDER.index),
               "strength": max(s for _, s, _ in g)} for g in groups]
    for lv in levels:
        lv["strong"] = len(lv["tfs"]) >= 2  # birden çok zaman diliminde görülen seviye

    def pick(side: list[dict]) -> list[dict]:
        near = side[:n]
        major = next((lv for lv in side if lv["strong"]), None)
        if major and not any(lv["strong"] for lv in near):
            near = near + [{**major, "major": True}]  # yakınlarda güçlü yoksa en yakın ana seviyeyi ekle
        return near

    sup = pick(sorted((lv for lv in levels if lv["price"] < price), key=lambda lv: -lv["price"]))
    res_ = pick(sorted((lv for lv in levels if lv["price"] > price), key=lambda lv: lv["price"]))
    return sup, res_


def _level_text(lv: dict, price: float, u: str) -> str:
    pct = f"{100 * (lv['price'] / price - 1):+.1f}%".replace(".", ",")
    tfs = "+".join(TF_TR[t] for t in lv["tfs"])
    text = f"{chart.fmt_price_tr(lv['price'])}{u} ({pct} · {tfs}" + (", güçlü" if lv["strong"] else "") + ")"
    return f"<b>ana seviye {text}</b>" if lv.get("major") else text


def _why_not(r: dict, cfg: dict, regs: dict, active_keys: set) -> str:
    if (r.get("market"), r["symbol"]) in active_keys:
        return "📂 Bu varlıkta zaten takipte bir işlem var."
    reason = strategy.rejection(r, cfg, regs)
    if reason is None:
        return "✅ Kurallara uyuyor → fırsatlar listesinde."
    if reason == "BEKLE":
        need = f"{cfg['buy_threshold']}+ gerekli" if r["side"] == "long" else f"{cfg['sell_threshold']} altı gerekli"
        return f"⏸ Şimdilik işlem yok: sinyal gücü {r['score']:.0f}/100 ({need})."
    if reason == "R:R düşük":
        rr, need = f"{r['rr']:.1f}".replace(".", ","), f"{cfg['cand_min_rr']:g}".replace(".", ",")
        return f"⏸ Şimdilik işlem yok: kazanç/risk {rr} (en az {need} gerekli). Fiyat bölgeye yaklaşınca oran iyileşir."
    if reason == "stop likidasyona yakın":
        return "⏸ Şimdilik işlem yok: zarar-kes çok uzakta, kaldıraçla riskli."
    if reason == "BIST kapalı":
        return "⏸ Borsa kapalı; seans açılınca tekrar bakılır."
    return "⏸ Şimdilik işlem yok: trende ters yön."


def card(res: dict, cfg: dict, regs: dict, active_keys: set) -> str:
    esc, f = html.escape, chart.fmt_price_tr
    u, price = unit(res), res["price"]
    name = res.get("name") or res["symbol"]
    market_reg = {"crypto": regs.get("crypto"), "bist": regs.get("bist")}.get(res.get("market"))
    if res["symbol"] == "BIST100":
        market_reg = regs.get("bist")
    trend = {"up": "📈 yükseliş trendi", "down": "📉 düşüş trendi", "neutral": "↔️ yatay"}.get(
        market_reg or strategy.regime(res["frames"]["1d"]), "")
    sup, rst = key_levels(res)
    lines = [f"{ICON.get(res['symbol'], '•')} <b>{esc(name)}</b> · {f(price)}{u} · {trend}",
             "🟩 Destek (alış bölgesi): " + (" · ".join(_level_text(lv, price, u) for lv in sup) or "yakında yok"),
             "🟥 Direnç (satış bölgesi): " + (" · ".join(_level_text(lv, price, u) for lv in rst) or "yakında yok")]

    # yön: kripto/hisse rejime göre; sabit liste (altın, endeks) kendi trendine göre, yataysa ikisi
    reg = market_reg or strategy.regime(res["frames"]["1d"])
    sides = {"up": ["long"], "down": ["short"]}.get(reg, ["long", "short"])
    for side in sides:
        r = signal.with_side(res, side, cfg)
        long = side == "long"
        verb = "alış" if long else "satış"
        lines.append(
            f"{'📥' if long else '📤'} <b>{verb.capitalize()} planı</b>: <code>{f(r['entry'])}</code>'den limit {verb} · "
            f"zarar-kes <code>{f(r['sl'])}</code> · hedef <code>{f(r['tp1'])}</code> / <code>{f(r['tp2'])}</code> · "
            + f"kazanç/risk {r['rr']:.1f}".replace(".", ","))
        lines.append(esc(_why_not(r, cfg, regs, active_keys)))
    return "\n".join(lines)


def find(key: str, crypto: dict, fixed: list[dict]) -> dict | None:
    if key in crypto:
        return crypto[key]
    return next((r for r in fixed if r["symbol"] == key), None)


async def send(bot: Bot, chat_id: int, cfg: dict, regs: dict, crypto: dict, fixed: list[dict],
               active: list[dict], with_charts: bool, send_timeout: int = 120) -> None:
    assets = [a for a in (find(k, crypto, fixed) for k in cfg["key_assets"]) if a]
    if not assets:
        return
    active_keys = {(p["market"], p["symbol"]) for p in active}
    head = ("🗺️ <b>Piyasa haritası: nerede alınır, nerede satılır?</b>\n"
            "<i>Destek = fiyatın düşüşte tutunduğu bölge (alış için), direnç = yükselişte zorlandığı bölge (satış için). "
            "Parantezde: şimdiki fiyata uzaklık · görüldüğü zaman dilimleri (s = saatlik grafik, g = günlük).</i>")
    await bot.send_message(chat_id, head + "\n\n" + "\n\n".join(card(a, cfg, regs, active_keys) for a in assets),
                           parse_mode=ParseMode.HTML)
    if with_charts:
        for a in assets:
            reg = regs.get("crypto") if a.get("market") == "crypto" else regs.get("bist") if a["symbol"] == "BIST100" else None
            side = {"up": "long", "down": "short"}.get(reg or strategy.regime(a["frames"]["1d"]),
                                                       "long" if a["raw_score"] >= 50 else "short")
            r = signal.with_side(a, side, cfg)
            png = await asyncio.to_thread(chart.coin_chart, {**r, "symbol": a.get("name") or a["symbol"]})
            await bot.send_photo(chat_id, png, write_timeout=send_timeout,
                                 caption=f"{a.get('name') or a['symbol']}: yeşil çizgiler destek, kırmızılar direnç; "
                                         "kesikli çizgiler plan (mavi = emir, kırmızı = zarar-kes, yeşil = hedefler).")
