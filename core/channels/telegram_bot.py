from __future__ import annotations

import asyncio
import logging
import threading

import requests

from config import TELEGRAM_BOT_TOKEN
# Telegram bot delivers Pulse private memory intel, raised findings, and 🛡️ Shield security alerts to users (fresh notification coordination)
# New: telegram now consumes Pulse private memory for Shield alerts (additional telegram spot)
# Pulse private memory + Shield (telegram bot surface)
from core.app_preferences import (
    get_local_api_host,
    get_local_api_port,
    get_telegram_allowed_chat_ids,
    is_local_api_enabled,
    is_telegram_bot_feature_enabled,
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


def telegram_bot_available(db: DatabaseManager | None = None) -> tuple[bool, str]:
    d = db or DatabaseManager()
    if not is_local_api_enabled(d):
        return False, "Local API is disabled in Settings."
    if not is_telegram_bot_feature_enabled(d):
        return False, "Telegram bot is disabled in Settings."
    if Bot is None or Dispatcher is None:
        return False, "aiogram is not installed."
    if not TELEGRAM_BOT_TOKEN:
        return False, "Telegram bot token is not set in config/.env (NAVI_TELEGRAM_BOT_TOKEN)."
    return True, "available"


def _api_base(db: DatabaseManager | None = None) -> str:
    d = db or DatabaseManager()
    return f"http://{get_local_api_host(d)}:{int(get_local_api_port(d))}"


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
        db = DatabaseManager()
        allowed = get_telegram_allowed_chat_ids(db)
        if allowed and chat_id not in allowed:
            return

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
                f"{_api_base(db)}/chat/main-turn",
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
