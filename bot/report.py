"""Tarama sonucunu Telegram'a gönderme: özet tablo + 10'arlı grafik albümleri."""
import asyncio
import html
import logging
import time
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, MenuButtonWebApp, WebAppInfo
from telegram.constants import ParseMode

from bot import monitor
from core import chart, db, scanner, settings, strategy, tracker

TZ = ZoneInfo("Europe/Istanbul")

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
    """Sıra: işlem olayları (doldu/TP1/stop…) → özet → yeni adaylar → tablolar (sadece table_hours'ta)."""
    cfg = settings.all_settings()
    await set_calc_menu(bot, chat_id, cfg)
    try:
        pos = await monitor.check(bot, chat_id, cfg)
    except Exception:  # noqa: BLE001 — takip hatası raporu durdurmasın
        log.exception("pozisyon takibi hatası")
        pos = []
    active = [p for p in pos if p["state"] in monitor.ACTIVE]
    longs, shorts, failed = await scanner.scan()
    # kripto dışı piyasalar: hata olursa kripto raporunu bozmasın
    try:
        fixed, b_longs, b_shorts, t_failed = await scanner.scan_tradfi()
    except Exception as e:  # noqa: BLE001
        log.exception("altın/gümüş/BIST taraması hatası")
        fixed, b_longs, b_shorts, t_failed = [], [], [], [f"Altın/Gümüş/BIST ({e})"]

    everything = longs + shorts + fixed + b_longs + b_shorts
    try:
        regs = await scanner.regimes(fixed)
    except Exception:  # noqa: BLE001 — rejim bilinmiyorsa filtre uygulanmaz
        log.exception("rejim hesaplanamadı")
        regs = {}
    cands = strategy.select(everything, cfg, regs, active=active)
    for c in cands:
        c["candidate"] = True
    tracker.record(everything, cfg["entry_mode"])

    await send_summary(bot, chat_id, cfg, regs, pos, cands, title)
    if cands:
        await send_candidates(bot, chat_id, cands, cfg, regs)

    if not tables_due(cfg):
        if failed or t_failed:
            log.warning("veri alınamadı: %s", failed + t_failed)
        return
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


def tables_due(cfg: dict) -> bool:
    """Bilgi tabloları sadece table_hours'taki raporlarda (GitHub gecikmesine karşı rapor dilimine yuvarlanır)."""
    hour = datetime.now(TZ).hour
    past = [h for h in cfg["report_hours"] if h <= hour]
    slot = max(past) if past else max(cfg["report_hours"])
    return slot in cfg["table_hours"]


async def send_summary(bot: Bot, chat_id: int, cfg: dict, regs: dict, pos: list[dict], cands: list[dict],
                       title: str) -> None:
    now = int(time.time())
    esc = html.escape
    lines = [f"📋 <b>{esc(title)} — {datetime.now(TZ):%d.%m %H:%M}</b>"]
    if regs:
        lines.append("Piyasa: " + " · ".join(f"{name} {REGIME_TEXT[regs[k]]}"
                                             for k, name in (("crypto", "BTC"), ("bist", "BIST100")) if k in regs))
    active = [p for p in pos if p["state"] in monitor.ACTIVE]
    recent = [p for p in pos if p["state"] not in monitor.ACTIVE
              and max([ts for _, ts in p["events"]], default=0) >= now - 86400]
    lines.append(f"\n<b>İşlemler ({len(active)}/{cfg['max_open']} dolu)</b>")
    shown = monitor.position_lines(active + recent, now)
    lines.append("<pre>" + esc("\n".join(shown)) + "</pre>" if shown else "Açık ya da bekleyen işlem yok.")
    if cands:
        lines.append(f"\n🎯 <b>Yeni işlem adayı: {len(cands)}</b> — tablo aşağıda")
    elif len(active) >= cfg["max_open"]:
        lines.append("\n🎯 Yeni aday yok: işlem limiti dolu.")
    else:
        lines.append(f"\n🎯 Yeni aday yok (AL/SAT + R:R ≥ {cfg['cand_min_rr']:g} + trend yönü şartları sağlanmadı). "
                     "Beklemek de bir pozisyondur.")
    a = tracker.virtual_account(now, cfg["capital_usd"], cfg["risk_pct"], cfg["max_open"], cfg["max_same_dir_crypto"])
    exp = "—" if a["expectancy"] is None else f"{a['expectancy']:+.2f}R"
    lines.append(f"💼 Sanal hesap: {a['equity']:,.0f} $ · {a['trades']} kapanmış işlem · beklenti {exp}".replace(",", "."))
    if not tables_due(cfg):
        lines.append(f"<i>Piyasa tabloları {' ve '.join(f'{h:02d}:00' for h in cfg['table_hours'])} raporlarında.</i>")
    await bot.send_message(chat_id, "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=calc_buttons(cfg, []))


def calc_link(cfg: dict, r: dict | None = None) -> str:
    """Hesaplayıcı adresi; aday verilirse seviyeleri önceden doldurur."""
    if not r:
        return cfg["calc_url"]
    limit = cfg["entry_mode"] == "limit" and r["entry"] != r["price"]
    params = {"side": r["side"], "sym": r.get("name") or r["symbol"], "lev": f"{cfg['leverage']:g}",
              "mode": "limit" if limit else "market", "hz": cfg["horizon_h"],
              **{k: f"{r[k]:.10g}" for k in ("entry", "sl", "tp1", "tp2")}}
    return f"{cfg['calc_url']}?{urlencode(params)}"


def calc_buttons(cfg: dict, cands: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"🧮 Hesapla: {r.get('name') or r['symbol']} "
                                  f"({'LONG' if r['side'] == 'long' else 'SHORT'})",
                                  web_app=WebAppInfo(calc_link(cfg, r)))] for r in cands]
    return InlineKeyboardMarkup(rows or [[InlineKeyboardButton("🧮 Pozisyon hesaplayıcıyı aç",
                                                               web_app=WebAppInfo(calc_link(cfg)))]])


async def set_calc_menu(bot: Bot, chat_id: int, cfg: dict) -> None:
    """Sohbetin menü butonunu hesaplayıcıya bağlar (Telegram'da kalıcı; her çalışmada yenilemek zararsız)."""
    try:
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonWebApp(
            "🧮 Hesapla", WebAppInfo(calc_link(cfg))))
    except Exception:  # noqa: BLE001 — menü butonu olmadan da rapor gitsin
        log.exception("menü butonu ayarlanamadı")


REGIME_TEXT = {"up": "📈 yükseliş (sadece long)", "down": "📉 düşüş (sadece short)", "neutral": "↔️ yatay (iki yön)"}


async def send_candidates(bot: Bot, chat_id: int, cands: list[dict], cfg: dict, regs: dict | None = None) -> None:
    reg_line = ""
    if regs and cfg.get("regime_filter"):
        reg_line = "\nPiyasa rejimi: " + " · ".join(
            f"{name} {REGIME_TEXT[regs[k]]}" for k, name in (("crypto", "BTC"), ("bist", "BIST100")) if k in regs)
    if not cands:
        await bot.send_message(
            chat_id,
            "🎯 İŞLEM ADAYI YOK — bu raporda strateji kurallarının hepsini geçen işlem çıkmadı.\n"
            f"(AL/SAT sinyali + R:R ≥ {cfg['cand_min_rr']:g} + stop likidasyondan güvenli uzaklıkta + trend yönünde)"
            f"{reg_line}\nBeklemek de bir pozisyondur; aşağıdaki tablolar sadece bilgi içindir.",
            reply_markup=calc_buttons(cfg, []))
        return
    png = await asyncio.to_thread(chart.candidates_table, cands, cfg, "Moon or Doom — İşlem Adayları")
    risk = cfg["capital_usd"] * cfg["risk_pct"] / 100
    await bot.send_photo(
        chat_id, png, write_timeout=SEND_TIMEOUT, reply_markup=calc_buttons(cfg, cands),
        caption=f"🎯 İŞLEM ADAYLARI — kuralların hepsini geçen {len(cands)} işlem (en güçlüsü üstte). "
                f"Her biri en fazla {risk:,.0f} $ risk (%{cfg['risk_pct']:g}). "
                + ("Girişler LİMİT emir: 12 saat içinde dolmazsa iptal et. " if cfg["entry_mode"] == "limit" else "")
                + f"İşlem en fazla {cfg['horizon_h']} saat tutulur. Önce 100 işlem sanal takip! "
                "Aşağıdaki butonla kendi sermayene göre hesapla."
                .replace(",", ".") + reg_line)


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
