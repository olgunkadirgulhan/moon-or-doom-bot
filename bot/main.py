"""Giriş noktası: `python -m bot.main`"""
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from telegram import BotCommand, Update  # noqa: E402
from telegram.ext import Application  # noqa: E402

from bot import handlers, jobs  # noqa: E402
from bot.auth import allowed_chat_id  # noqa: E402
from core import data  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("moon-or-doom")

COMMANDS = [
    BotCommand("scan", "Tüm listeyi tara"),
    BotCommand("coin", "Tek coin detayı (ör. /coin ETH)"),
    BotCommand("list", "İzleme listesi"),
    BotCommand("hesapla", "Pozisyon hesaplayıcı"),
    BotCommand("watch", "Listeye ekle/çıkar"),
    BotCommand("settings", "Ayarlar"),
    BotCommand("help", "Yardım"),
]


async def on_start(app: Application) -> None:
    jobs.schedule_reports(app)
    await app.bot.set_my_commands(COMMANDS)
    if allowed_chat_id() is None:
        log.warning("ALLOWED_CHAT_ID boş: bota /start yaz, konsolda görünen chat_id'yi .env'e ekle.")


async def on_stop(app: Application) -> None:
    await data.close()


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN .env içinde tanımlı değil.")
    app = (
        Application.builder()
        .token(token)
        .post_init(on_start)
        .post_shutdown(on_stop)
        .build()
    )
    handlers.register(app)
    log.info("Bot başlıyor…")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
