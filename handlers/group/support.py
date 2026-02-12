
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import settings
from database.database import get_session
from database.repository import UserRepository, ChatRepository, TrainingRepository
from services.ai_service import AIService
from locales.loader import get_text

router = Router()

@router.message(Command("ai"), F.chat.id == settings.SUPPORT_GROUP_ID)
async def activate_ai_in_thread(message: Message):
    thread_id = message.message_thread_id

    if not thread_id:
        await message.answer("⚠️ Эта команда работает только в топиках")
        return

    async with get_session() as session:
        from sqlalchemy import select
        from database.models import User

        result = await session.execute(
            select(User).where(User.thread_id == thread_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Пользователь не найден для этого топика")
            return

        chat_repo = ChatRepository(session)
        await chat_repo.activate_ai(user.id)

    await message.answer(
        f"✅ AI активирован для пользователя {user.first_name}\n"
        "Теперь бот снова будет автоматически отвечать."
    )

@router.callback_query(F.data.startswith("ai_reply_"), F.message.chat.id == settings.SUPPORT_GROUP_ID)
async def ai_reply_handler(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[2])

    async with get_session() as session:
        from sqlalchemy import select
        from database.models import User

        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return

        chat_repo = ChatRepository(session)
        training_repo = TrainingRepository(session)

        active_session = await chat_repo.get_active_session(user_id)
        if not active_session:
            await callback.answer("❌ Нет активной сессии", show_alert=True)
            return

        history = await chat_repo.get_session_history(active_session.id, limit=30)
        messages = [{"role": h.role, "content": h.content} for h in history if h.role in ["user", "assistant", "support"]]

        if len(messages) > 20:
            old_messages = messages[:len(messages)//2]
            recent_messages = messages[len(messages)//2:]
            old_summary = "Ранее обсуждались темы: "
            user_questions = [m["content"][:50] + "..." for m in old_messages if m["role"] == "user"]
            old_summary += "; ".join(user_questions[:5]) if user_questions else "различные вопросы"
            context_summary = old_summary
            messages = [{"role": "system", "content": old_summary}] + recent_messages
        else:
            context_summary = None

    ai_service = await AIService.get_service()
    if not ai_service:
        await callback.answer("❌ AI недоступен", show_alert=True)
        return

    await callback.answer("⏳ Генерирую ответ с помощью AI...")

    async with get_session() as session:
        training_repo = TrainingRepository(session)
        system_prompt = await ai_service.get_system_prompt(training_repo, user.language)

    response = await ai_service.get_response(messages, system_prompt)

    thread_id = user.thread_id
    if context_summary:
        await callback.message.bot.send_message(
            chat_id=settings.SUPPORT_GROUP_ID,
            message_thread_id=thread_id,
            text=f"📝 <b>Контекст (сжатый):</b>\n{context_summary}",
            parse_mode="HTML"
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔄 Направить в нейросеть обратно",
                callback_data=f"resend_to_ai_{user_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🚫 Заблокировать пользователя навсегда",
                callback_data=f"ban_user_{user_id}"
            )
        ]
    ])

    await callback.message.bot.send_message(
        chat_id=settings.SUPPORT_GROUP_ID,
        message_thread_id=thread_id,
        text=f"🤖 <b>Отправлено с помощью AI:</b>\n\n{response}",
        parse_mode="HTML",
        reply_markup=keyboard
    )

    support_text = get_text("support_response", user.language).format(text=response)
    try:
        await callback.message.bot.send_message(
            chat_id=user.id,
            text=support_text,
            parse_mode="HTML"
        )

        async with get_session() as session:
            chat_repo = ChatRepository(session)
            await chat_repo.add_message(
                user.id,
                "support",
                response,
                is_ai_handled=False
            )

    except Exception as e:
        await callback.message.answer(f"❌ Не удалось отправить сообщение пользователю: {e}")

@router.callback_query(F.data.startswith("resend_to_ai_"), F.message.chat.id == settings.SUPPORT_GROUP_ID)
async def resend_to_ai_handler(callback: CallbackQuery):
    async with get_session() as session:
        user_repo = UserRepository(session)
        admin = await user_repo.get_by_id(callback.from_user.id)

        if not admin or admin.role != "admin":
            await callback.answer("❌ Только администраторы могут использовать эту кнопку", show_alert=True)
            return

        user_id = int(callback.data.split("_")[3])

        from sqlalchemy import select
        from database.models import User

        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return

        chat_repo = ChatRepository(session)

        await chat_repo.activate_ai(user_id)

        thread_id = user.thread_id

        await callback.message.bot.send_message(
            chat_id=settings.SUPPORT_GROUP_ID,
            message_thread_id=thread_id,
            text=f"🤖 <b>Пользователь направлен в режим AI</b>\n\nАдминистратор {callback.from_user.first_name} включил автоматические ответы AI для пользователя.",
            parse_mode="HTML"
        )

    await callback.answer("✅ AI активирован для пользователя", show_alert=True)

@router.callback_query(F.data.startswith("ban_user_"), F.message.chat.id == settings.SUPPORT_GROUP_ID)
async def ban_user_handler(callback: CallbackQuery):
    async with get_session() as session:
        user_repo = UserRepository(session)
        admin = await user_repo.get_by_id(callback.from_user.id)

        if not admin or admin.role != "admin":
            await callback.answer("❌ Только администраторы могут использовать эту кнопку", show_alert=True)
            return

        user_id = int(callback.data.split("_")[2])

        from sqlalchemy import select
        from database.models import User

        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return

        await user_repo.ban_user(user_id, None)

        thread_id = user.thread_id
        await callback.message.bot.send_message(
            chat_id=settings.SUPPORT_GROUP_ID,
            message_thread_id=thread_id,
            text=f"🚫 <b>Пользователь заблокирован</b>\n\nПользователь {user.first_name} (ID: {user_id}) был заблокирован администратором {callback.from_user.first_name}.",
            parse_mode="HTML"
        )

        banned_text = get_text("banned", user.language)
        try:
            await callback.message.bot.send_message(
                chat_id=user_id,
                text=banned_text
            )
        except Exception:
            pass

        await callback.answer("✅ Пользователь заблокирован", show_alert=True)

@router.message(F.chat.id == settings.SUPPORT_GROUP_ID, F.message_thread_id, F.reply_to_message)
async def handle_support_message(message: Message):
    thread_id = message.message_thread_id

    if not thread_id:
        return

    if message.from_user.is_bot:
        return

    async with get_session() as session:
        from sqlalchemy import select
        from database.models import User

        user_repo = UserRepository(session)
        sender = await user_repo.get_by_id(message.from_user.id)

        if not sender or sender.role != "admin":
            return

        result = await session.execute(
            select(User).where(User.thread_id == thread_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return

        support_text = get_text("support_response", user.language).format(
            text=message.text or "[Медиафайл]"
        )

        try:
            await message.bot.send_message(
                chat_id=user.id,
                text=support_text,
                parse_mode="HTML"
            )

            chat_repo = ChatRepository(session)
            await chat_repo.add_message(
                user.id,
                "support",
                message.text or "[Media]",
                is_ai_handled=False
            )

        except Exception as e:
            await message.answer(f"❌ Не удалось отправить сообщение: {e}")
