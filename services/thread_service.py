
import logging
from typing import Optional
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError

from config import settings
from database.repository import UserRepository

logger = logging.getLogger(__name__)

class ThreadService:

    def __init__(self, bot: Bot):
        self.bot = bot
        self.support_group_id = settings.SUPPORT_GROUP_ID

    async def create_thread_for_user(
        self,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        user_repo: UserRepository
    ) -> Optional[int]:
        try:
            user_display = first_name or f"User {user_id}"
            thread_name = f"🆘 {user_display}"

            forum_topic = await self.bot.create_forum_topic(
                chat_id=self.support_group_id,
                name=thread_name
            )

            thread_id = forum_topic.message_thread_id

            await user_repo.update_thread_id(user_id, thread_id)

            welcome_msg = f"""
📋 <b>Новый пользователь</b>

👤 User ID: <code>{user_id}</code>
👤 Username: {f'@{username}' if username else 'Не указан'}
👤 Имя: {first_name or 'Не указано'}

🤖 AI активен. Все сообщения дублируются сюда.
💬 Чтобы ответить пользователю, напишите в этот топик.
🔄 Чтобы вернуть AI: отправьте /ai
"""
            await self.bot.send_message(
                chat_id=self.support_group_id,
                message_thread_id=thread_id,
                text=welcome_msg,
                parse_mode="HTML"
            )

            logger.info(f"Created thread {thread_id} for user {user_id}")
            return thread_id

        except TelegramAPIError as e:
            logger.error(f"Failed to create thread for user {user_id}: {e}")

            if "not enough rights" in str(e).lower():
                await self._notify_admins_about_permissions()

            return None

    async def send_to_thread(self, thread_id: int, text: str, from_user: bool = True, user_id: int = None, add_ai_button: bool = False):
        try:
            prefix = "👤 <b>Пользователь:</b>\n" if from_user else "🤖 <b>AI ответ:</b>\n"
            full_text = prefix + text

            keyboard = None
            if from_user and user_id:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🚫 Заблокировать пользователя навсегда",
                        callback_data=f"ban_user_{user_id}"
                    )]
                ])
            elif add_ai_button and user_id:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🤖 Ответить с AI",
                        callback_data=f"ai_reply_{user_id}"
                    )]
                ])

            await self.bot.send_message(
                chat_id=self.support_group_id,
                message_thread_id=thread_id,
                text=full_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except TelegramAPIError as e:
            logger.error(f"Failed to send to thread {thread_id}: {e}")

    async def notify_human_needed(self, thread_id: int):
        try:
            text = """
🚨 <b>ТРЕБУЕТСЯ ПОДДЕРЖКА</b>

Пользователь запросил помощь человека.
AI ответы приостановлены.

💬 Ответьте на сообщение пользователя в этом топике.
🔄 Чтобы вернуть AI: отправьте /ai
"""
            await self.bot.send_message(
                chat_id=self.support_group_id,
                message_thread_id=thread_id,
                text=text,
                parse_mode="HTML"
            )
        except TelegramAPIError as e:
            logger.error(f"Failed to notify in thread {thread_id}: {e}")

    async def _notify_admins_about_permissions(self):
        try:
            text = """
⚠️ <b>ВНИМАНИЕ: Недостаточно прав</b>

Бот не может создавать топики в супергруппе.
Пожалуйста, выдайте боту права на управление топиками.

Права → Управление темами → Включить
"""
            await self.bot.send_message(
                chat_id=self.support_group_id,
                text=text,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to notify admins about permissions: {e}")
