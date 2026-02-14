from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject

from database.database import current_bot_db_url, current_support_group_id


class BotDBMiddleware(BaseMiddleware):

    def __init__(self, db_url_map: Dict[str, str], support_group_id: int):
        self.db_url_map = db_url_map  # {bot_token: db_url}
        self.support_group_id = support_group_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        bot: Bot = data['bot']
        db_url = self.db_url_map.get(bot.token, '')

        token_db = current_bot_db_url.set(db_url)
        token_sg = current_support_group_id.set(self.support_group_id)
        data['support_group_id'] = self.support_group_id
        try:
            return await handler(event, data)
        finally:
            current_bot_db_url.reset(token_db)
            current_support_group_id.reset(token_sg)
