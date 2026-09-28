"""Telegram komutları: /scan /coin /list /watch /settings /help"""
import json
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot import jobs
from bot.auth import restricted
from bot.report import caption, send_charts, send_report
from core import chart, data, db, onchain, scanner, settings

HELP = (
    "🌕 Moon or Doom — kişisel sinyal botu\n\n"
    "/scan — tüm listeyi tara: özet tablo + AL/SAT grafikleri\n"
    "/coin ETH — tek coin detay grafiği\n"
    "/list — izleme listesi\n"
    "/watch add PEPE · /watch rm PEPE — listeyi düzenle\n"
    "/settings — ayarları göster\n"
    "/settings <anahtar> <değer> — ayar değiştir\n"
    "   ör: buy_threshold 70 · min_rr 2 · report_hours 0,6,12,18\n"
    "       weights.onchain 10 · alerts on · top_n 12\n\n"
    "⚠️ Yatırım tavsiyesi değildir; bot emir göndermez."
)


@restricted
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP)


@restricted
async def scan_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("🔎 Taranıyor…")
    try:
        await send_report(ctx.bot, update.effective_chat.id, only_signals=True, title="Manuel Tarama")
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Tarama başarısız: {e}")
    finally:
        await msg.delete()


@restricted
async def coin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Kullanım: /coin ETH")
        return
    symbol = scanner._normalize(ctx.args[0])
    if not await data.is_listed(symbol):
        await update.message.reply_text(f"{symbol}/USDT borsada bulunamadı.")
        return
    msg = await update.message.reply_text(f"🔎 {symbol} analiz ediliyor…")
    try:
        r = await scanner.analyze(symbol)
        await send_charts(ctx.bot, update.effective_chat.id, [r])
        await update.message.reply_text(_detail(r))
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ {symbol} analiz edilemedi: {e}")
    finally:
        await msg.delete()


def _detail(r: dict) -> str:
    comp = r["components"]
    w = settings.get("weights")
    parts = [caption(None, r), "", "Bileşenler (−1…+1 × ağırlık):"]
    parts += [f"  {k}: {v:+.2f} × {w[k]}" for k, v in comp.items()]
    oc = r["onchain"]
    if oc.get("available"):
        parts.append(f"\nGiriş 24s {chart.fmt_usd(-oc['inflow_24h'])} · Çıkış 24s {chart.fmt_usd(oc['outflow_24h'])}")
        for wh in oc["whales"]:
            arrow = "borsadan çıkış" if wh["dir"] == "out" else "borsaya giriş"
            parts.append(f"  🐋 {chart.fmt_usd(wh['usd'])[1:]} {arrow} ({wh['exchange']})")
    else:
        parts.append(f"\nOn-chain: yok ({oc.get('reason')})")
    return "\n".join(parts)


@restricted
async def list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    syms = await scanner.universe()
    added = set(db.kv_get("watch_add", [])) | set(onchain.manual_coins())
    removed = db.kv_get("watch_rm", [])
    text = f"İzleme listesi ({len(syms)} coin, ✚ = manuel):\n" + ", ".join(
        f"{s}✚" if s in added else s for s in syms)
    if removed:
        text += f"\n\nÇıkarılanlar: {', '.join(removed)}"
    await update.message.reply_text(text)


@restricted
async def watch_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) != 2 or ctx.args[0] not in ("add", "rm"):
        await update.message.reply_text("Kullanım: /watch add PEPE  veya  /watch rm PEPE")
        return
    action, symbol = ctx.args[0], scanner._normalize(ctx.args[1])
    if action == "add":
        if not await data.is_listed(symbol):
            await update.message.reply_text(f"{symbol}/USDT borsada bulunamadı.")
            return
        scanner.watch_add(symbol)
        await update.message.reply_text(f"✅ {symbol} listeye eklendi.")
    else:
        scanner.watch_rm(symbol)
        await update.message.reply_text(f"🗑 {symbol} listeden çıkarıldı.")


@restricted
async def settings_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) >= 2:
        key, raw = ctx.args[0], "".join(ctx.args[1:])
        try:
            settings.set_value(key, raw)
        except KeyError:
            await update.message.reply_text(f"Bilinmeyen ayar: {key}")
            return
        except ValueError as e:
            await update.message.reply_text(f"Geçersiz değer: {e}")
            return
        if key == "report_hours":
            jobs.schedule_reports(ctx.application)
        await update.message.reply_text(f"✅ {key} güncellendi.")
    text = json.dumps(settings.all_settings(), ensure_ascii=False, indent=2)
    await update.message.reply_text(f"Ayarlar:\n{text}\n\nDeğiştir: /settings <anahtar> <değer>")


async def _error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    logging.getLogger(__name__).error("handler hatası", exc_info=ctx.error)


def register(app: Application) -> None:
    for name, fn in [("start", help_cmd), ("help", help_cmd), ("scan", scan_cmd), ("coin", coin_cmd),
                     ("list", list_cmd), ("watch", watch_cmd), ("settings", settings_cmd)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_error_handler(_error)
