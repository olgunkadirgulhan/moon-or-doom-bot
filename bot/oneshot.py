"""Tek seferlik iş, sonra çık. GitHub Actions için:
`python -m bot.oneshot report|weekly|monthly`
monthly sadece ayın son günü çalışır (FORCE=1 ile her gün).
"""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from telegram import Bot  # noqa: E402

from bot.auth import allowed_chat_id  # noqa: E402
from bot.report import send_report, send_result  # noqa: E402
from core import data, tracker  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # istek URL'lerinde token var


async def main(mode: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = allowed_chat_id()
    if not token or chat_id is None:
        sys.exit("TELEGRAM_BOT_TOKEN ve ALLOWED_CHAT_ID gerekli.")
    if mode == "monthly" and not tracker.is_last_day_of_month() and os.getenv("FORCE") != "1":
        logging.info("Ayın son günü değil, aylık sonuç atlandı.")
        return
    try:
        async with Bot(token) as bot:
            if mode in ("weekly", "monthly"):
                await send_result(bot, chat_id, mode)
            else:
                await send_report(bot, chat_id, title="Otomatik Rapor")
    finally:
        await data.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "report"))
