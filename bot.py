import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from database.database import (
    init_bot_db, init_shared_db, close_all_db,
    current_bot_db_url, current_support_group_id
)
from utils.logger import setup_logger
from middlewares.bot_db import BotDBMiddleware
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


def _build_dispatcher(db_url_map: dict) -> Dispatcher:
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    bot_db_middleware = BotDBMiddleware(db_url_map, settings.SUPPORT_GROUP_ID)
    dp.message.middleware(bot_db_middleware)
    dp.callback_query.middleware(bot_db_middleware)

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

    dp.include_router(support.router)

    dp.include_router(chat.router)
    dp.include_router(menu.router)
    dp.include_router(settings_handler.router)

    return dp


async def main():
    setup_logger()
    logger = logging.getLogger(__name__)

    await init_shared_db()
    logger.info("Shared database initialized")

    bot_configs = settings.bot_configs
    if not bot_configs:
        logger.error("No bot configurations found. Set BOT1_TOKEN in .env")
        return

    logger.info(f"Starting {len(bot_configs)} bot(s)...")

    for cfg in bot_configs:
        await init_bot_db(cfg)
        logger.info(f"Bot {cfg.index} database initialized")

    bots = [
        Bot(token=cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        for cfg in bot_configs
    ]

    db_url_map = {cfg.token: cfg.db_url for cfg in bot_configs}

    for bot, cfg in zip(bots, bot_configs):
        t_db = current_bot_db_url.set(cfg.db_url)
        t_sg = current_support_group_id.set(settings.SUPPORT_GROUP_ID)
        try:
            await PendingService.process_pending_requests(bot)
            logger.info(f"Bot {cfg.index}: pending requests processed")
        finally:
            current_bot_db_url.reset(t_db)
            current_support_group_id.reset(t_sg)

    dp = _build_dispatcher(db_url_map)

    logger.info(f"All bots started (group: {settings.SUPPORT_GROUP_ID})")

    try:
        await dp.start_polling(*bots, allowed_updates=dp.resolve_used_update_types())
    finally:
        for bot in bots:
            await bot.session.close()
        await close_all_db()
        logger.info("All bots stopped")


if __name__ == "__main__":
    asyncio.run(main())
