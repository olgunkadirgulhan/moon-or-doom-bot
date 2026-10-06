"""Tek seferlik iş, sonra çık. GitHub Actions için:
`python -m bot.oneshot report|monitor|results|trend|daily|weekly|monthly`
results: bugün gereken tüm sonuçlar (günlük + cumartesi haftalık + ay sonu aylık).
"""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from telegram import Bot  # noqa: E402

from bot.auth import allowed_chat_id  # noqa: E402
from bot import monitor, trend_job  # noqa: E402
from bot.report import send_report, send_result  # noqa: E402
from core import data, settings, tracker  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # istek URL'lerinde token var


async def main(mode: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = allowed_chat_id()
    if not token or chat_id is None:
        sys.exit("TELEGRAM_BOT_TOKEN ve ALLOWED_CHAT_ID gerekli.")
    try:
        async with Bot(token) as bot:
            if mode == "trend":
                # günlük kapanıştan sonra: trend kırılımı sinyalleri + açık trend pozisyonlarının stopları
                await trend_job.run(bot, chat_id)
            elif mode == "monitor":
                # raporlar arası: sadece işlem olayları (doldu, TP1, stop, süre) — tarama yok
                await monitor.check(bot, chat_id, settings.all_settings())
            elif mode == "results":
                # akşam çalışması: her gün günlük, cumartesi haftalık, ayın son günü aylık
                for period in tracker.due_periods():
                    await send_result(bot, chat_id, period)
            elif mode in ("daily", "weekly", "monthly"):
                await send_result(bot, chat_id, mode)
            else:
                await send_report(bot, chat_id, title="Otomatik Rapor")
    finally:
        await data.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "report"))
