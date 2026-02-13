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
from states.admin_states import AdminStates
from services.ai_service import AIService
from services.thread_service import ThreadService
from keyboards.menu import get_try_ai_again_keyboard, get_main_menu_keyboard
import re
import logging

logger = logging.getLogger(__name__)
router = Router()

HUMAN_REQUEST_KEYWORDS = [
    "call people", "call person", "call operator", "call human", "call support",
    "call_people", "connect me", "speak with human", "talk to human",
    "позвать человека", "позови человека", "вызови человека", "вызвать человека",
    "нужен оператор", "нужен человек", "хочу оператора", "хочу человека",
    "соедини с оператором", "свяжи с оператором", "оператор", "operator",
    "please call", "please connect", "connect human", "human please",
    "call peple", "call pepole", "call poeple",            
]

def is_direct_human_request(text: str) -> bool:
    text_lower = text.lower().strip()
    return any(keyword in text_lower for keyword in HUMAN_REQUEST_KEYWORDS)

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

    if is_direct_human_request(user_message):
        async with get_session() as session:
            chat_repo = ChatRepository(session)
            await chat_repo.deactivate_ai(user_id)
            await chat_repo.add_message(user_id, "user", user_message, message.message_id)

        await state.set_state(UserStates.chatting)
        await message.answer(get_text("human_called", language), parse_mode="HTML")

        if user.thread_id:
            from config import settings
            from aiogram.exceptions import TelegramAPIError
            try:
                await message.bot.send_message(
                    chat_id=settings.SUPPORT_GROUP_ID,
                    message_thread_id=user.thread_id,
                    text="🚨 <b>ВЫЗВАН ЧЕЛОВЕК</b>\n\nПользователь запросил поддержку человека.\nОжидаем описание ситуации.",
                    parse_mode="HTML"
                )
            except TelegramAPIError as e:
                error_msg = str(e).lower()
                if any(k in error_msg for k in ['thread not found', 'topic closed', 'topic not found', 'message thread not found']):
                    async with get_session() as session:
                        user_repo = UserRepository(session)
                        await user_repo.update_thread_id(user_id, None)
        return

    ai_service = await AIService.get_service()
    if not ai_service:
        await message.answer(
            "❌ Нет доступных AI ключей. Обратитесь к администратором.",
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

    if not response_text or response_text.strip() == "":
        logger.warning(f"AI returned empty response for user {user_id}")
        await message.answer("Извините, произошла ошибка. Попробуйте переформулировать вопрос.")
        async with get_session() as session:
            pending_repo = PendingRequestRepository(session)
            await pending_repo.mark_completed(pending_request.id)
        return

    if "ignore_offtopic" in response_text.lower():
        logger.info(f"Вопрос пользователя {user_id} определён как offtopic")
        await message.answer(get_text("off_topic", language))
        async with get_session() as session:
            pending_repo = PendingRequestRepository(session)
            await pending_repo.mark_completed(pending_request.id)
        return

    if "call_people" in response_text.lower():
        async with get_session() as session:
            chat_repo = ChatRepository(session)
            await chat_repo.deactivate_ai(user_id)

        await state.set_state(UserStates.chatting)

        clean_response = response_text.replace("call_people", "").replace("CALL_PEOPLE", "").replace("ignore_offtopic", "").replace("IGNORE_OFFTOPIC", "").strip()

        if clean_response:
            html_response = markdown_to_html(clean_response)
            await message.answer(html_response, parse_mode="HTML")

        await message.answer(get_text("human_called", language), parse_mode="HTML")

        async with get_session() as session:
            chat_repo = ChatRepository(session)
            pending_repo = PendingRequestRepository(session)
                                                                      
            if clean_response:
                await chat_repo.add_message(user_id, "assistant", clean_response, None)
            await pending_repo.mark_completed(pending_request.id)

        if user.thread_id:
            from config import settings
            from aiogram.exceptions import TelegramAPIError
            try:
                await message.bot.send_message(
                    chat_id=settings.SUPPORT_GROUP_ID,
                    message_thread_id=user.thread_id,
                    text=f"🚨 <b>ВЫЗВАН ЧЕЛОВЕК</b>\n\nПользователь запросил поддержку человека.\nОжидаем описание ситуации.",
                    parse_mode="HTML"
                )
            except TelegramAPIError as e:
                error_msg = str(e).lower()
                                                                     
                if any(keyword in error_msg for keyword in ['thread not found', 'topic closed', 'topic not found', 'message thread not found']):
                    logger.warning(f"Thread {user.thread_id} deleted, clearing thread_id for user {user_id}")
                    async with get_session() as session:
                        user_repo = UserRepository(session)
                        await user_repo.update_thread_id(user_id, None)
                else:
                    logger.error(f"Failed to send human call notification to thread: {e}")
    else:
                                                                                             
        clean_text = response_text.replace("ignore_offtopic", "").replace("IGNORE_OFFTOPIC", "").strip()

        if not clean_text:
            logger.warning(f"AI response became empty after cleaning for user {user_id}")
            await message.answer("Извините, произошла ошибка. Попробуйте переформулировать вопрос.")
            async with get_session() as session:
                pending_repo = PendingRequestRepository(session)
                await pending_repo.mark_completed(pending_request.id)
            return

        html_response = markdown_to_html(clean_text)
        response_msg = await message.answer(html_response, parse_mode="HTML")

        async with get_session() as session:
            chat_repo = ChatRepository(session)
            pending_repo = PendingRequestRepository(session)
            await chat_repo.add_message(user_id, "assistant", clean_text, response_msg.message_id)
            await pending_repo.mark_completed(pending_request.id)

        if user.thread_id:
            thread_service = ThreadService(message.bot)
            await thread_service.send_to_thread(user.thread_id, user_message, from_user=True, user_id=user_id)
            await thread_service.send_to_thread(user.thread_id, clean_text, from_user=False, user_id=user_id)

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
async def handle_text_outside_chat(message: Message, state: FSMContext):
    from config import settings
    if message.chat.id == settings.SUPPORT_GROUP_ID:
        return

    current_state = await state.get_state()
    if current_state and current_state.startswith("AdminStates:"):
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
