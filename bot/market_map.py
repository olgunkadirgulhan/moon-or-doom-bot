"""Piyasa haritası: önemli varlıklar için destek/direnç bölgeleri, hazır işlem planı ve "neden şu an işlem yok".

Aday olmasa bile kullanıcı "nerede alınır, nerede satılır" sorusunun cevabını görsün diye her raporda gönderilir.
"""
import asyncio
import html

from telegram import Bot, InputMediaPhoto
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


SHORT_STATUS = {None: "✓ FIRSAT", "BEKLE": "Güç yetersiz", "R:R düşük": "Kazanç/risk düşük",
                "stop likidasyona yakın": "Zarar-kes çok uzak", "BIST kapalı": "Borsa kapalı"}
MARKET_LABEL = {"crypto": "Kripto", "tradfi": "Emtia/Endeks", "bist": "BIST"}


def plan_side(res: dict, regs: dict) -> str:
    """Varlığın gösterilecek yönü: kripto/hisse piyasa rejimine, diğerleri kendi günlük trendine/skoruna göre."""
    reg = regs.get("crypto") if res.get("market") == "crypto" else regs.get("bist") if res.get("market") == "bist" \
        or res["symbol"] == "BIST100" else None
    reg = reg or strategy.regime(res["frames"]["1d"])
    return {"up": "long", "down": "short"}.get(reg, "long" if res["raw_score"] >= 50 else "short")


def board_rows(items: list[dict], cfg: dict, regs: dict, cand_keys: set, active_keys: set) -> list[dict]:
    rows = []
    for r in items:
        key = (r.get("market"), r["symbol"])
        if key in active_keys:
            status = "Takipte (işlem var)"
        elif key in cand_keys:
            status = "✓ FIRSAT"
        else:
            reason = strategy.rejection(r, cfg, regs)
            status = SHORT_STATUS.get(reason, "Trende ters") if reason else "Kurala uygun"
        rows.append({"name": (r.get("name") or r["symbol"])[:14], "market_label": MARKET_LABEL.get(r.get("market"), ""),
                     "side": r["side"], "score": r["score"], "price": r["price"], "entry": r["entry"], "sl": r["sl"],
                     "tp1": r["tp1"], "tp2": r["tp2"], "rr": r["rr"], "status": status, "ok": key in cand_keys})
    return rows


async def send_board(bot: Bot, chat_id: int, cfg: dict, regs: dict, crypto_all: dict, fixed: list[dict],
                     ranked: dict[str, list[dict]], cands: list[dict], active: list[dict], with_charts: bool,
                     send_timeout: int = 120) -> None:
    """Piyasa başına bir pano (kripto, BIST, altın/gümüş): ALIŞ sonra SATIŞ bölümü, fırsatlar en üstte."""
    cand_keys = {(c.get("market"), c["symbol"]) for c in cands}
    active_keys = {(p["market"], p["symbol"]) for p in active}
    picked: dict[tuple, dict] = {}

    def add(r):
        picked.setdefault((r.get("market"), r["symbol"], r["side"]), r)

    for c in cands:
        add(c)
    for k in cfg["key_assets"] + [r["symbol"] for r in fixed]:
        a = find(k, crypto_all, fixed)
        if a:
            add(signal.with_side(a, plan_side(a, regs), cfg))
    for name, n in (("crypto_long", 10), ("crypto_short", 10), ("bist_long", 5), ("bist_short", 5)):
        for r in ranked.get(name, [])[:n]:
            add(r)

    # her piyasa kendi içinde: kendi panosu + hemen ardından kendi grafikleri (albüm)
    for grp, label in GROUPS:
        items = [r for r in picked.values() if group_of(r) == grp]
        if not items:
            continue

        def order(side):
            rows = [r for r in items if r["side"] == side]
            strength = (lambda r: -r["score"]) if side == "long" else (lambda r: r["score"])
            return sorted(rows, key=lambda r: ((r.get("market"), r["symbol"]) not in cand_keys, strength(r)))

        sections = [("▲ ALIŞ (long) — fiyat yükselirse kazanır · en güçlüsü üstte",
                     board_rows(order("long"), cfg, regs, cand_keys, active_keys)),
                    ("▼ SATIŞ (short) — fiyat düşerse kazanır · en güçlüsü üstte",
                     board_rows(order("short"), cfg, regs, cand_keys, active_keys))]
        png = await asyncio.to_thread(chart.board, sections, f"Moon or Doom — {label} Panosu")
        reg = {"crypto": ("crypto", "BTC"), "bist": ("bist", "BIST100")}.get(grp)
        trend = {"up": "📈 yükselişte", "down": "📉 düşüşte", "neutral": "↔️ yatay"}.get(regs.get(reg[0])) if reg else None
        await bot.send_photo(chat_id, png, write_timeout=send_timeout,
                             caption=f"🗺️ {label} panosu" + (f" · {reg[1]} {trend}" if trend else "") +
                                     "\nYeşil satırlar kurallara uyan fırsatlar; ayrıntılı rakamlar ayrı mesajda.")
        if not with_charts:
            continue
        media = []
        for k in cfg["key_assets"]:
            a = find(k, crypto_all, fixed)
            if not a or group_of(a) != grp:
                continue
            r = signal.with_side(a, plan_side(a, regs), cfg)
            media.append(await asyncio.to_thread(chart.coin_chart, {**r, "symbol": a.get("name") or a["symbol"]}))
        if not media:
            continue
        # albümde tek açıklama: birden çok açıklama olunca Telegram sohbette hiçbirini göstermiyor
        note = (f"📈 {label} grafikleri: yeşil çizgiler destek, kırmızılar direnç; kesikli çizgiler plan "
                "(mavi = emir, kırmızı = zarar-kes, yeşil = hedefler).")
        if len(media) == 1:
            await bot.send_photo(chat_id, media[0], caption=note, write_timeout=send_timeout)
        else:
            await bot.send_media_group(chat_id, [InputMediaPhoto(m, caption=note if i == 0 else None)
                                                 for i, m in enumerate(media)], write_timeout=send_timeout)


GROUPS = [("crypto", "₿ Kripto"), ("bist", "🏛 BIST"), ("metal", "🥇 Altın · Gümüş")]


def group_of(r: dict) -> str:
    """Telegram'da ayrı gönderilen piyasa grubu: kripto, BIST (hisseler + BIST 100/30 endeksi), altın/gümüş."""
    if r.get("market") == "crypto":
        return "crypto"
    if r.get("market") == "bist" or r["symbol"].startswith("BIST"):
        return "bist"
    return "metal"


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
