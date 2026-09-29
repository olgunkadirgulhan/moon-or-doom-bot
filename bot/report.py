"""Tarama sonucunu Telegram'a gönderme: özet tablo + 10'arlı grafik albümleri."""
import asyncio
import logging

from telegram import Bot, InputMediaPhoto

from core import chart, db, scanner, settings, tracker

log = logging.getLogger(__name__)
ICON = {"AL": "🟢", "SAT": "🔴", "BEKLE": "🟡"}
SEND_TIMEOUT = 120


def caption(rank: int | None, r: dict) -> str:
    f = chart.fmt_price
    head = f"{rank}. " if rank else ""
    lines = [
        f"{head}{ICON[r['signal']]} {r['symbol']} — {r['signal']} ({chart.side_label(r)}) — Skor {r['score']:.0f}",
        f"Giriş (güncel fiyat) {f(r['entry'])} | SL {f(r['sl'])}",
        f"TP1 {f(r['tp1'])} | TP2 {f(r['tp2'])} | R:R {r['rr']:.1f}" + (" ⚠️ R:R düşük" if r["rr_low"] else ""),
    ]
    oc = r.get("onchain", {})
    if oc.get("available"):
        lines.append(f"Netflow 24s {chart.fmt_usd(oc['netflow_24h'])} · balina: {len(oc['whales'])}")
    return "\n".join(lines)


async def send_charts(bot: Bot, chat_id: int, results: list[dict], ranks: list[int] | None = None) -> None:
    ranks = ranks or [None] * len(results)
    media = []
    for rank, r in zip(ranks, results):
        png = await asyncio.to_thread(chart.coin_chart, r)
        media.append(InputMediaPhoto(png, caption=caption(rank, r)))
    for i in range(0, len(media), 10):
        chunk = media[i: i + 10]
        if len(chunk) == 1:
            await bot.send_photo(chat_id, chunk[0].media, caption=chunk[0].caption, write_timeout=SEND_TIMEOUT)
        else:
            await bot.send_media_group(chat_id, chunk, write_timeout=SEND_TIMEOUT)


async def send_report(bot: Bot, chat_id: int, title: str = "Sinyal Özeti") -> None:
    """İki sıralama tablosu (LONG, SHORT); `charts` ayarı açıksa ardından AL/SAT grafikleri."""
    longs, shorts, failed = await scanner.scan()
    tracker.record(longs + shorts)
    tables = [
        (longs, f"🟢 LONG — en güçlü {len(longs)} (skor yüksekten düşüğe)", f"{title} · LONG"),
        (shorts, f"🔴 SHORT — en güçlü {len(shorts)} (skor düşükten yükseğe)", f"{title} · SHORT"),
    ]
    for rows, note, table_title in tables:
        png = await asyncio.to_thread(chart.summary_table, rows, f"Moon or Doom — {table_title}",
                                      settings.get("margin_usd"), settings.get("leverage"))
        await bot.send_photo(chat_id, png, caption=note, write_timeout=SEND_TIMEOUT)
    if failed:
        await bot.send_message(chat_id, f"Veri alınamadı: {', '.join(failed)}")

    actionable = [r for r in longs + shorts if r["signal"] != "BEKLE"]
    if settings.get("charts") and actionable:
        await send_charts(bot, chat_id, actionable)

    # raporlar arası SL/TP uyarıları için planları sakla (yerel bot)
    db.kv_set("last_plans", [
        {k: r[k] for k in ("symbol", "signal", "side", "entry", "sl", "tp1", "tp2")} | {"hits": []}
        for r in actionable
    ])

    # kripto dışı piyasalar ayrı albüm; hata olursa kripto raporunu bozmasın
    try:
        await send_tradfi(bot, chat_id, title)
    except Exception as e:  # noqa: BLE001
        log.exception("altın/gümüş/BIST raporu hatası")
        await bot.send_message(chat_id, f"⚠️ Altın/Gümüş/BIST tablosu alınamadı: {e}")


async def send_tradfi(bot: Bot, chat_id: int, title: str) -> None:
    """Altın/gümüş/endeks sabit listesi + BIST100 en iyi LONG ve SHORT — 3 tablo tek albüm."""
    fixed, longs, shorts, failed = await scanner.scan_tradfi()
    tracker.record(fixed + longs + shorts)
    margin, lev = settings.get("margin_usd"), settings.get("leverage")
    tables = [
        (fixed, f"🥇 Altın · Gümüş · Endeks — {title}", "Altın · Gümüş · Endeks"),
        (longs, f"🟢 BIST100 LONG — en güçlü {len(longs)}", "BIST100 · LONG"),
        (shorts, f"🔴 BIST100 SHORT — en güçlü {len(shorts)}", "BIST100 · SHORT"),
    ]
    media = []
    for rows, note, table_title in tables:
        if not rows:
            continue
        png = await asyncio.to_thread(chart.summary_table, rows, f"Moon or Doom — {table_title}", margin, lev, "Varlık")
        media.append(InputMediaPhoto(png, caption=note))
    if media:
        await bot.send_media_group(chat_id, media, write_timeout=SEND_TIMEOUT)
    if failed:
        await bot.send_message(chat_id, f"Veri alınamadı: {', '.join(failed)}")


async def send_result(bot: Bot, chat_id: int, period: str) -> None:
    """period: daily/weekly/monthly/3m/6m/9m/12m isabet grafiği; özet tracking/results.csv'ye kaydedilir."""
    since, until, title = tracker.period_bounds(period)
    summary = await tracker.evaluate(since, until)
    o = summary["overall"]
    if not o["total"]:
        await bot.send_message(chat_id, f"📊 {title}: bu dönemde kayıtlı tahmin yok.")
        return
    tracker.save_result(period, title, summary)
    png = await asyncio.to_thread(chart.result_chart, summary, title)
    acc = "—" if o["accuracy"] is None else f"%{o['accuracy']:.0f}"
    note = (f"📊 {title}\n{o['total']} tahmin → ✓ {o['tp']} hedef, ✗ {o['sl']} stop, "
            f"○ {o['open']} açık. Doğruluk {acc}")
    await bot.send_photo(chat_id, png, caption=note, write_timeout=SEND_TIMEOUT)
