"""Tarama sonucunu Telegram'a gönderme: özet tablo + 10'arlı grafik albümleri."""
import asyncio
import logging

from telegram import Bot, InputMediaPhoto

from core import chart, db, scanner, settings, strategy, tracker

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
    """Sıra: işlem adayları → kripto LONG/SHORT → altın/gümüş/endeks → BIST100 LONG/SHORT."""
    cfg = settings.all_settings()
    longs, shorts, failed = await scanner.scan()
    # kripto dışı piyasalar: hata olursa kripto raporunu bozmasın
    try:
        fixed, b_longs, b_shorts, t_failed = await scanner.scan_tradfi()
    except Exception as e:  # noqa: BLE001
        log.exception("altın/gümüş/BIST taraması hatası")
        fixed, b_longs, b_shorts, t_failed = [], [], [], [f"Altın/Gümüş/BIST ({e})"]

    everything = longs + shorts + fixed + b_longs + b_shorts
    cands = strategy.select(everything, cfg)
    for c in cands:
        c["candidate"] = True
    tracker.record(everything)

    await send_candidates(bot, chat_id, cands, cfg)

    tables = [
        (longs, f"🟢 KRİPTO LONG — en güçlü {len(longs)} (skor yüksekten düşüğe)", f"{title} · Kripto LONG", "Coin"),
        (shorts, f"🔴 KRİPTO SHORT — en güçlü {len(shorts)} (skor düşükten yükseğe)", f"{title} · Kripto SHORT", "Coin"),
        (fixed, f"🥇 ALTIN · GÜMÜŞ · ENDEKS — sabit liste ({len(fixed)}): gram altın/gümüş ₺ ve $, altın ons, "
                "BIST 100, BIST 30", "Altın · Gümüş · Endeks", "Varlık"),
        (b_longs, f"🟢 BIST100 LONG — en güçlü {len(b_longs)} (skor yüksekten düşüğe)", "BIST100 · LONG", "Varlık"),
        (b_shorts, f"🔴 BIST100 SHORT — en güçlü {len(b_shorts)} (skor düşükten yükseğe)", "BIST100 · SHORT", "Varlık"),
    ]
    # tek tek gönder: albümde birden çok açıklama olunca Telegram sohbette hiçbirini göstermiyor
    for rows, note, table_title, label in tables:
        if not rows:
            continue
        png = await asyncio.to_thread(chart.summary_table, rows, f"Moon or Doom — {table_title}",
                                      cfg["margin_usd"], cfg["leverage"], label)
        await bot.send_photo(chat_id, png, caption=note, write_timeout=SEND_TIMEOUT)
    if failed or t_failed:
        await bot.send_message(chat_id, f"Veri alınamadı: {', '.join(failed + t_failed)}")

    actionable = [r for r in longs + shorts if r["signal"] != "BEKLE"]
    if cfg["charts"] and actionable:
        await send_charts(bot, chat_id, actionable)

    # raporlar arası SL/TP uyarıları için adayların planlarını sakla (yerel bot)
    db.kv_set("last_plans", [
        {k: r[k] for k in ("symbol", "signal", "side", "entry", "sl", "tp1", "tp2")} | {"hits": []}
        for r in cands
    ])


async def send_candidates(bot: Bot, chat_id: int, cands: list[dict], cfg: dict) -> None:
    if not cands:
        await bot.send_message(
            chat_id,
            "🎯 İŞLEM ADAYI YOK — bu raporda strateji kurallarının hepsini geçen işlem çıkmadı.\n"
            f"(AL/SAT sinyali + R:R ≥ {cfg['cand_min_rr']:g} + stop likidasyondan güvenli uzaklıkta)\n"
            "Beklemek de bir pozisyondur; aşağıdaki tablolar sadece bilgi içindir.")
        return
    png = await asyncio.to_thread(chart.candidates_table, cands, cfg, "Moon or Doom — İşlem Adayları")
    risk = cfg["capital_usd"] * cfg["risk_pct"] / 100
    await bot.send_photo(
        chat_id, png, write_timeout=SEND_TIMEOUT,
        caption=f"🎯 İŞLEM ADAYLARI — kuralların hepsini geçen {len(cands)} işlem (en güçlüsü üstte). "
                f"Her biri en fazla {risk:,.0f} $ risk (%{cfg['risk_pct']:g}). Önce 100 işlem sanal takip!"
                .replace(",", "."))


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
    a = summary["account"]
    exp = "—" if a["expectancy"] is None else f"{a['expectancy']:+.2f} R"
    note = (f"📊 {title}\n{o['total']} tahmin → ✓ {o['tp']} hedef, ✗ {o['sl']} stop, "
            f"○ {o['open']} açık. Doğruluk {acc}\n"
            f"💼 Sanal hesap (başlangıçtan beri): {a['equity']:,.0f} $ · {a['trades']} işlem · beklenti {exp} · "
            f"en büyük düşüş %{a['max_dd']:.1f}".replace(",", "."))
    await bot.send_photo(chat_id, png, caption=note, write_timeout=SEND_TIMEOUT)
