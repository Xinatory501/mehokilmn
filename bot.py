import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from database.database import init_db, close_db
from utils.logger import setup_logger
from middlewares.antiflood import AntiFloodMiddleware
from middlewares.ban_check import BanCheckMiddleware
from services.pending_service import PendingService

from handlers import start, menu, chat
from handlers import settings as settings_handler
from handlers.admin import (
    main as admin_main,
    api_keys,
    user_management,
    privacy_policy,
    training,
    database_backup,
    reports,
    antiflood_settings
)
from handlers.group import support

async def main():
    setup_logger()
    logger = logging.getLogger(__name__)

    await init_db()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.message.middleware(BanCheckMiddleware())
    dp.message.middleware(AntiFloodMiddleware())

    dp.include_router(start.router)
    dp.include_router(admin_main.router)

    dp.include_router(api_keys.router)
    dp.include_router(antiflood_settings.router)
    dp.include_router(user_management.router)
    dp.include_router(privacy_policy.router)
    dp.include_router(training.router)
    dp.include_router(database_backup.router)
    dp.include_router(reports.router)

    dp.include_router(chat.router)
    dp.include_router(menu.router)
    dp.include_router(settings_handler.router)

    dp.include_router(support.router)

    logger.info("Bot started successfully")

    await PendingService.process_pending_requests(bot)
    logger.info("Pending requests processed")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await close_db()
        await bot.session.close()
        logger.info("Bot stopped")

if __name__ == "__main__":
    asyncio.run(main())
