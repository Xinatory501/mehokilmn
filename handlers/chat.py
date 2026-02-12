from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from database.database import get_session
from database.repository import (
    UserRepository,
    ChatRepository,
    TrainingRepository,
    PendingRequestRepository
)
from locales.loader import get_text
from states.user_states import UserStates
from services.ai_service import AIService
from services.thread_service import ThreadService
from keyboards.menu import get_try_ai_again_keyboard, get_main_menu_keyboard
import re

router = Router()

def markdown_to_html(text: str) -> str:
    text = re.sub(r'\*\*([^\*]+?)\*\*', r'<b>\1</b>', text, flags=re.UNICODE)
    text = re.sub(r'\*([^\*]+?)\*', r'<i>\1</i>', text, flags=re.UNICODE)
    text = re.sub(r'`([^`]+?)`', r'<code>\1</code>', text, flags=re.UNICODE)
    text = re.sub(r'\[([^\]]+?)\]\(([^\)]+?)\)', r'<a href="\2">\1</a>', text, flags=re.UNICODE)
    return text

@router.message(UserStates.chatting, F.text)
async def handle_chat_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_message = message.text

    if user_message.startswith('/admin') or user_message.startswith('/start'):
        return

    async with get_session() as session:
        user_repo = UserRepository(session)
        chat_repo = ChatRepository(session)
        training_repo = TrainingRepository(session)

        user = await user_repo.get_by_id(user_id)
        language = user.language

        active_session = await chat_repo.get_active_session(user_id)
        if not active_session:
            await message.answer(get_text("no_active_session", language))
            return

        if not active_session.is_ai_active:
            await chat_repo.add_message(user_id, "user", user_message, message.message_id, is_ai_handled=False)
            if user.thread_id:
                thread_service = ThreadService(message.bot)
                await thread_service.send_to_thread(
                    user.thread_id,
                    user_message,
                    from_user=True,
                    user_id=user_id,
                    add_ai_button=True
                )
            return

    ai_service = await AIService.get_service()
    if not ai_service:
        await message.answer(
            "❌ Нет доступных AI ключей. Обратитесь к администратору.",
            reply_markup=get_try_ai_again_keyboard(language)
        )
        return

    async with get_session() as session:
        chat_repo = ChatRepository(session)
        training_repo = TrainingRepository(session)
        pending_repo = PendingRequestRepository(session)

        await chat_repo.add_message(user_id, "user", user_message, message.message_id)

        pending_request = await pending_repo.create(
            user_id=user_id,
            message_text=user_message,
            message_id=message.message_id,
            session_id=active_session.id
        )

        history = await chat_repo.get_session_history(active_session.id, limit=30)
        messages = [{"role": h.role, "content": h.content} for h in history if h.role in ["user", "assistant"]]

        if len(messages) > 20:
            old_messages = messages[:len(messages)//2]
            recent_messages = messages[len(messages)//2:]
            old_summary = "Ранее обсуждались темы: "
            user_questions = [m["content"][:50] + "..." for m in old_messages if m["role"] == "user"]
            old_summary += "; ".join(user_questions[:5]) if user_questions else "различные вопросы"
            messages = [{"role": "system", "content": old_summary}] + recent_messages

        system_prompt = await ai_service.get_system_prompt(training_repo, language)

    response_text = ""
    async for chunk in ai_service.get_response_stream(
        messages,
        system_prompt,
        user_id=user_id,
        thread_id=user.thread_id if user else None,
        bot=message.bot
    ):
        response_text += chunk

    if "call_people" in response_text.lower():
        async with get_session() as session:
            chat_repo = ChatRepository(session)
            await chat_repo.deactivate_ai(user_id)

        await state.set_state(UserStates.chatting)

        clean_response = response_text.replace("call_people", "").replace("CALL_PEOPLE", "").strip()
        html_response = markdown_to_html(clean_response)

        await message.answer(html_response, parse_mode="HTML")
        await message.answer("👤 <b>Человек вызван</b>\n\nНапишите ситуацию, она будет передана в группу поддержки.", parse_mode="HTML")

        async with get_session() as session:
            chat_repo = ChatRepository(session)
            pending_repo = PendingRequestRepository(session)
            await chat_repo.add_message(user_id, "assistant", clean_response, None)
            await pending_repo.mark_completed(pending_request.id)

        thread_service = ThreadService(message.bot)
        if not user.thread_id:
            async with get_session() as session:
                user_repo = UserRepository(session)
                thread_id = await thread_service.create_thread_for_user(
                    user_id,
                    message.from_user.username,
                    message.from_user.first_name,
                    user_repo
                )
                if thread_id:
                    user.thread_id = thread_id

        if user.thread_id:
            from config import settings
            await message.bot.send_message(
                chat_id=settings.SUPPORT_GROUP_ID,
                message_thread_id=user.thread_id,
                text=f"🚨 <b>ВЫЗВАН ЧЕЛОВЕК</b>\n\nПользователь запросил поддержку человека.\nОжидаем описание ситуации.",
                parse_mode="HTML"
            )
    else:
        html_response = markdown_to_html(response_text)
        response_msg = await message.answer(html_response, parse_mode="HTML")

        async with get_session() as session:
            chat_repo = ChatRepository(session)
            pending_repo = PendingRequestRepository(session)
            await chat_repo.add_message(user_id, "assistant", response_text, response_msg.message_id)
            await pending_repo.mark_completed(pending_request.id)

        thread_service = ThreadService(message.bot)
        if not user.thread_id:
            async with get_session() as session:
                user_repo = UserRepository(session)
                thread_id = await thread_service.create_thread_for_user(
                    user_id,
                    message.from_user.username,
                    message.from_user.first_name,
                    user_repo
                )
                if thread_id:
                    user.thread_id = thread_id

        if user.thread_id:
            await thread_service.send_to_thread(user.thread_id, user_message, from_user=True)
            await thread_service.send_to_thread(user.thread_id, response_text, from_user=False)

@router.message(UserStates.chatting)
async def handle_non_text_message(message: Message):
    user_id = message.from_user.id

    async with get_session() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(user_id)
        language = user.language

        await message.answer(get_text("text_only", language))

@router.callback_query(F.data == "try_ai_again")
async def try_ai_again(callback: CallbackQuery):
    user_id = callback.from_user.id

    async with get_session() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(user_id)
        language = user.language

    ai_service = await AIService.get_service()

    if ai_service:
        await callback.answer("✅ AI доступен! Можете продолжать общение.", show_alert=True)
        await callback.message.edit_text(
            "✅ AI снова доступен! Отправьте ваш вопрос.",
            reply_markup=None
        )
    else:
        await callback.answer("❌ AI все еще недоступен. Попробуйте позже.", show_alert=True)

@router.message(~StateFilter(UserStates.chatting), F.text)
async def handle_text_outside_chat(message: Message):
    # Игнорировать сообщения из группы поддержки
    from config import settings
    if message.chat.id == settings.SUPPORT_GROUP_ID:
        return

    user_id = message.from_user.id

    async with get_session() as session:
        user_repo = UserRepository(session)
        chat_repo = ChatRepository(session)

        user = await user_repo.get_by_id(user_id)

        if not user:
            return

        language = user.language

        has_history = False
        active_session = await chat_repo.get_active_session(user_id)
        if active_session:
            history = await chat_repo.get_session_history(active_session.id, limit=1)
            has_history = len(history) > 0

        await message.answer(
            get_text("not_in_chat_state", language),
            reply_markup=get_main_menu_keyboard(language, has_history)
        )
