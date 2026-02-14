
import logging
from typing import Optional
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError

from database.repository import UserRepository
from database.database import current_support_group_id

logger = logging.getLogger(__name__)

class ThreadService:

    def __init__(self, bot: Bot, support_group_id: int = None):
        self.bot = bot
        self.support_group_id = support_group_id if support_group_id is not None else current_support_group_id.get()

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
        """Отправка сообщения в топик. Если топик не существует - НЕ отправляет."""
        if not thread_id:
            logger.warning(f"Thread ID is None for user {user_id}, skipping message")
            return False

        try:
            prefix = "👤 <b>Пользователь:</b>\n" if from_user else "🤖 <b>AI ответ:</b>\n"
            full_text = prefix + text

            keyboard = None
            if from_user and user_id:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="Заблокировать пользователя навсегда",
                        callback_data=f"ban_user_{user_id}"
                    )]
                ])
            elif add_ai_button and user_id:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="Ответить с AI",
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
            return True
        except TelegramAPIError as e:
            error_msg = str(e).lower()
                                                                                
            if any(keyword in error_msg for keyword in ['thread not found', 'topic closed', 'topic not found', 'message thread not found']):
                logger.warning(f"Thread {thread_id} not found or deleted, clearing thread_id for user {user_id}")
                if user_id:
                    await self._clear_user_thread(user_id)
            else:
                logger.error(f"Failed to send to thread {thread_id}: {e}")
            return False

    async def notify_human_needed(self, thread_id: int, user_id: int = None):
        """Уведомление о необходимости поддержки. Если топик не существует - НЕ отправляет."""
        if not thread_id:
            logger.warning(f"Thread ID is None for user {user_id}, skipping notification")
            return False

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
            return True
        except TelegramAPIError as e:
            error_msg = str(e).lower()
                                                                                
            if any(keyword in error_msg for keyword in ['thread not found', 'topic closed', 'topic not found', 'message thread not found']):
                logger.warning(f"Thread {thread_id} not found or deleted, clearing thread_id for user {user_id}")
                if user_id:
                    await self._clear_user_thread(user_id)
            else:
                logger.error(f"Failed to notify in thread {thread_id}: {e}")
            return False

    async def _clear_user_thread(self, user_id: int):
        """Очищает thread_id у пользователя если топик удалён"""
        try:
            from database.database import get_session
            async with get_session() as session:
                user_repo = UserRepository(session)
                await user_repo.update_thread_id(user_id, None)
                logger.info(f"Cleared thread_id for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to clear thread_id for user {user_id}: {e}")

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
