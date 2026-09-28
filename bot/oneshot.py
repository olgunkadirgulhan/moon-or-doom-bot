"""Tek seferlik rapor: tara, gönder, çık. GitHub Actions için: `python -m bot.oneshot`"""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from telegram import Bot  # noqa: E402

from bot.auth import allowed_chat_id  # noqa: E402
from bot.report import send_report  # noqa: E402
from core import data  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # istek URL'lerinde token var


async def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = allowed_chat_id()
    if not token or chat_id is None:
        sys.exit("TELEGRAM_BOT_TOKEN ve ALLOWED_CHAT_ID gerekli.")
    try:
        async with Bot(token) as bot:
            await send_report(bot, chat_id, title="Otomatik Rapor")
    finally:
        await data.close()


if __name__ == "__main__":
    asyncio.run(main())
