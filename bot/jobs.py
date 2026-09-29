"""Zamanlanmış işler (İstanbul saati): günde 6 rapor, her gün 20:00 günlük (+ cumartesi haftalık,
ayın son günü aylık) isabet sonucu, opsiyonel SL/TP uyarıları."""
import logging
from datetime import time
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

from bot.auth import allowed_chat_id
from bot.report import send_report, send_result
from core import chart, data, db, settings, tracker

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Istanbul")
ALERT_INTERVAL = 900


def schedule_reports(app: Application) -> list[int]:
    jq = app.job_queue
    for job in jq.get_jobs_by_name("report"):
        job.schedule_removal()
    hours = settings.get("report_hours")
    for h in hours:
        jq.run_daily(report_job, time(hour=h, tzinfo=TZ), name="report")
    if not jq.get_jobs_by_name("results"):
        jq.run_daily(result_job, time(hour=settings.get("result_hour"), tzinfo=TZ), name="results")
    if not jq.get_jobs_by_name("alerts"):
        jq.run_repeating(alert_job, interval=ALERT_INTERVAL, first=60, name="alerts")
    log.info("Rapor saatleri (İstanbul): %s", hours)
    return hours


async def report_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = allowed_chat_id()
    if chat_id is None:
        return
    try:
        await send_report(ctx.bot, chat_id, title="Otomatik Rapor")
    except Exception as e:  # noqa: BLE001
        log.exception("rapor hatası")
        await ctx.bot.send_message(chat_id, f"⚠️ Otomatik rapor başarısız: {e}")


async def result_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = allowed_chat_id()
    if chat_id is None:
        return
    for period in tracker.due_periods():
        try:
            await send_result(ctx.bot, chat_id, period)
        except Exception as e:  # noqa: BLE001
            log.exception("sonuç raporu hatası")
            await ctx.bot.send_message(chat_id, f"⚠️ {period} sonuç raporu başarısız: {e}")


def _hit(plan: dict, price: float) -> str | None:
    long = plan["side"] == "long"
    if (price <= plan["sl"]) if long else (price >= plan["sl"]):
        return "SL"
    for tp in ("tp2", "tp1"):
        if (price >= plan[tp]) if long else (price <= plan[tp]):
            return tp.upper()
    return None


async def alert_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = allowed_chat_id()
    if chat_id is None or not settings.get("alerts"):
        return
    plans = db.kv_get("last_plans", [])
    if not plans:
        return
    try:
        prices = await data.tickers()
    except Exception:  # noqa: BLE001
        log.exception("uyarı için fiyat alınamadı")
        return
    changed = False
    for p in plans:
        price = prices.get(p["symbol"], {}).get("last")
        hit = _hit(p, price) if price else None
        if hit and hit not in p["hits"] and "SL" not in p["hits"]:
            p["hits"].append(hit)
            changed = True
            icon = "🛑" if hit == "SL" else "🎯"
            await ctx.bot.send_message(
                chat_id, f"{icon} {p['symbol']} ({p['signal']}) {hit} seviyesine değdi: "
                         f"{chart.fmt_price(price)} (hedef {chart.fmt_price(p[hit.lower()])})")
    if changed:
        db.kv_set("last_plans", plans)
