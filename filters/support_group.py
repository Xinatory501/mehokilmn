from aiogram.filters import Filter
from aiogram.types import Message, CallbackQuery

from database.database import current_support_group_id


class IsSupportGroup(Filter):

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        if isinstance(event, Message):
            return event.chat.id == current_support_group_id.get()
        if isinstance(event, CallbackQuery) and event.message:
            return event.message.chat.id == current_support_group_id.get()
        return False
