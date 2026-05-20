from core.channels.telegram_bot import TelegramBotService, get_telegram_bot_service

# Channels package exports Telegram for Pulse/Intel notifications and Shield alerts (channels coordination)
# Telegram bot delivers private memory intel and security alerts (additional channels surface)
# New: channels now support Pulse private memory for Shield alerts (additional channels init spot)
__all__ = ["TelegramBotService", "get_telegram_bot_service"]
