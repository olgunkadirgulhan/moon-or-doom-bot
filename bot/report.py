"""Tarama sonucunu Telegram'a gönderme: özet tablo + 10'arlı grafik albümleri."""
import asyncio
import logging

from telegram import Bot, InputMediaPhoto

from core import chart, db, scanner

log = logging.getLogger(__name__)
ICON = {"AL": "🟢", "SAT": "🔴", "BEKLE": "🟡"}
SEND_TIMEOUT = 120


def caption(rank: int | None, r: dict) -> str:
    f = chart.fmt_price
    head = f"{rank}. " if rank else ""
    lines = [
        f"{head}{ICON[r['signal']]} {r['symbol']} — {r['signal']} — Skor {r['score']:.0f}",
        f"Fiyat {f(r['price'])} | Giriş {f(r['entry'])} | SL {f(r['sl'])}",
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


async def send_report(bot: Bot, chat_id: int, only_signals: bool = False, title: str = "Sinyal Özeti") -> None:
    """only_signals=True → /scan (sadece AL/SAT grafikleri), False → otomatik rapor (hepsi)."""
    top, failed = await scanner.scan()
    table = await asyncio.to_thread(chart.summary_table, top, f"Moon or Doom — {title}")
    note = f"{len(top)} coin, skora göre azalan sıralı."
    if failed:
        note += f"\nVeri alınamadı: {', '.join(failed)}"
    await bot.send_photo(chat_id, table, caption=note, write_timeout=SEND_TIMEOUT)

    ranked = list(enumerate(top, 1))
    if only_signals:
        ranked = [(i, r) for i, r in ranked if r["signal"] != "BEKLE"]
        if not ranked:
            await bot.send_message(chat_id, "Şu an AL/SAT eşiğini geçen coin yok (hepsi BEKLE).")
    if ranked:
        await send_charts(bot, chat_id, [r for _, r in ranked], [i for i, _ in ranked])

    # raporlar arası SL/TP uyarıları için planları sakla
    db.kv_set("last_plans", [
        {k: r[k] for k in ("symbol", "signal", "side", "entry", "sl", "tp1", "tp2")} | {"hits": []}
        for r in top if r["signal"] != "BEKLE"
    ])
