from __future__ import annotations

import asyncio
import logging
import threading

import requests

from config import (
    LOCAL_API_ENABLED,
    LOCAL_API_HOST,
    LOCAL_API_PORT,
    TELEGRAM_ALLOWED_CHAT_IDS,
    TELEGRAM_BOT_TOKEN,
)
from core.db import DatabaseManager

logger = logging.getLogger(__name__)

try:
    from aiogram import Bot, Dispatcher
    from aiogram.types import Message
except Exception:  # pragma: no cover - depends on optional install
    Bot = None
    Dispatcher = None
    Message = None


def telegram_bot_available() -> tuple[bool, str]:
    if not LOCAL_API_ENABLED:
        return False, "Local API is disabled."
    if Bot is None or Dispatcher is None:
        return False, "aiogram is not installed."
    if not TELEGRAM_BOT_TOKEN:
        return False, "Telegram bot token is not configured."
    return True, "available"


def _api_base() -> str:
    return f"http://{LOCAL_API_HOST}:{int(LOCAL_API_PORT)}"


class TelegramBotService:
    def __init__(self):
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self._thread is not None:
            return True
        ok, reason = telegram_bot_available()
        if not ok:
            logger.warning("Telegram bot unavailable: %s", reason)
            return False

        def _run():
            asyncio.run(self._poll())

        self._thread = threading.Thread(target=_run, name="navi-telegram-bot", daemon=True)
        self._thread.start()
        logger.info("Telegram bot polling thread started.")
        return True

    def stop(self) -> None:
        # Polling runs on a daemon thread; process shutdown stops it.
        self._thread = None

    async def _poll(self) -> None:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        dp = Dispatcher()
        dp.message.register(self._handle_message)
        try:
            await dp.start_polling(bot)
        finally:
            await bot.session.close()

    async def _handle_message(self, message: Message) -> None:
        text = str(getattr(message, "text", "") or "").strip()
        if not text:
            return
        chat_id = str(message.chat.id)
        if TELEGRAM_ALLOWED_CHAT_IDS and chat_id not in TELEGRAM_ALLOWED_CHAT_IDS:
            return

        db = DatabaseManager()
        binding = db.channel_binding_get(channel_name="telegram", external_chat_id=chat_id)
        session_id = str((binding or {}).get("session_id") or f"telegram_{chat_id}").strip()
        db.channel_binding_upsert(
            channel_name="telegram",
            external_chat_id=chat_id,
            session_id=session_id,
            metadata_json={"chat_title": getattr(message.chat, "title", None)},
        )

        try:
            response = requests.post(
                f"{_api_base()}/chat/main-turn",
                json={"message": text, "session_id": session_id},
                timeout=180,
            )
            response.raise_for_status()
            payload = response.json()
            reply = str(payload.get("response") or "").strip() or "(no response)"
        except Exception as exc:
            logger.exception("Telegram bot local API call failed: %s", exc)
            reply = f"Local API error: {exc}"

        for chunk in _chunk_text(reply):
            await message.answer(chunk)


def _chunk_text(text: str, *, limit: int = 3500) -> list[str]:
    value = str(text or "").strip()
    if not value:
        return [""]
    chunks: list[str] = []
    remaining = value
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks or [value]


_telegram_bot_service: TelegramBotService | None = None


def get_telegram_bot_service() -> TelegramBotService:
    global _telegram_bot_service
    if _telegram_bot_service is None:
        _telegram_bot_service = TelegramBotService()
    return _telegram_bot_service
