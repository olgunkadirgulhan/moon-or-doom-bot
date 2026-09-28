"""Sadece ALLOWED_CHAT_ID'ye cevap veren decorator."""
import logging
import os
from functools import wraps

log = logging.getLogger(__name__)


def allowed_chat_id() -> int | None:
    v = os.getenv("ALLOWED_CHAT_ID", "").strip()
    return int(v) if v.lstrip("-").isdigit() else None


def restricted(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        chat = update.effective_chat
        allowed = allowed_chat_id()
        if allowed is None and chat is not None:
            # kurulum yardımı: chat_id'yi sadece konsola yaz, kullanıcıya cevap verme
            log.warning("ALLOWED_CHAT_ID boş. Gelen chat_id=%s → .env dosyasına yaz.", chat.id)
        if chat is None or allowed is None or chat.id != allowed:
            return None
        return await func(update, context, *args, **kwargs)

    return wrapper
