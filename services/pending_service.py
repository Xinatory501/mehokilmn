import logging
from aiogram import Bot

from database.database import get_session, current_support_group_id
from database.repository import (
    PendingRequestRepository,
    ChatRepository,
    TrainingRepository,
    UserRepository
)
from services.ai_service import AIService
from services.thread_service import ThreadService
from locales.loader import get_text
import re

logger = logging.getLogger(__name__)

def markdown_to_html(text: str) -> str:
    text = re.sub(r'\*\*([^\*]+?)\*\*', r'<b>\1</b>', text, flags=re.UNICODE)
    text = re.sub(r'\*([^\*]+?)\*', r'<i>\1</i>', text, flags=re.UNICODE)
    text = re.sub(r'`([^`]+?)`', r'<code>\1</code>', text, flags=re.UNICODE)
    text = re.sub(r'\[([^\]]+?)\]\(([^\)]+?)\)', r'<a href="\2">\1</a>', text, flags=re.UNICODE)
    return text

class PendingService:

    @staticmethod
    async def process_pending_requests(bot: Bot):
        logger.info("Starting to process pending requests...")

        async with get_session() as session:
            pending_repo = PendingRequestRepository(session)
            pending_requests = await pending_repo.get_all_pending()

            if not pending_requests:
                logger.info("No pending requests found")
                return

            logger.info(f"Found {len(pending_requests)} pending requests")

            for request in pending_requests:
                try:
                    await pending_repo.mark_started(request.id)
                    logger.info(f"Processing pending request {request.id} from user {request.user_id}")

                    await PendingService._process_single_request(bot, request)

                    async with get_session() as new_session:
                        new_pending_repo = PendingRequestRepository(new_session)
                        await new_pending_repo.mark_completed(request.id)

                    logger.info(f"Successfully completed pending request {request.id}")

                except Exception as e:
                    logger.error(f"Error processing pending request {request.id}: {e}")
                    async with get_session() as new_session:
                        new_pending_repo = PendingRequestRepository(new_session)
                        await new_pending_repo.mark_failed(request.id)

    @staticmethod
    async def _process_single_request(bot: Bot, request):
        ai_service = await AIService.get_service()
        if not ai_service:
            logger.warning(f"No AI service available for pending request {request.id}")
            return

        async with get_session() as session:
            user_repo = UserRepository(session)
            chat_repo = ChatRepository(session)
            training_repo = TrainingRepository(session)

            user = await user_repo.get_by_id(request.user_id)
            if not user:
                logger.warning(f"User {request.user_id} not found for pending request {request.id}")
                return

            language = user.language

            active_session = await chat_repo.get_active_session(request.user_id)
            if not active_session:
                logger.warning(f"No active session for user {request.user_id}")
                return

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
            user_id=request.user_id,
            thread_id=user.thread_id if user else None,
            bot=bot
        ):
            response_text += chunk

        if not response_text or response_text.strip() == "":
            logger.warning(f"AI returned empty response for pending request {request.id}")
            return

        if "ignore_offtopic" in response_text.lower():
            logger.info(f"Pending request {request.id} marked as offtopic, skipping")
            return

        if "call_people" in response_text.lower():
            async with get_session() as session:
                chat_repo = ChatRepository(session)
                await chat_repo.deactivate_ai(request.user_id)

            clean_response = response_text.replace("call_people", "").replace("CALL_PEOPLE", "").replace("ignore_offtopic", "").replace("IGNORE_OFFTOPIC", "").strip()

            if clean_response:
                html_response = markdown_to_html(clean_response)
                await bot.send_message(
                    chat_id=request.user_id,
                    text=html_response,
                    parse_mode="HTML"
                )

            await bot.send_message(
                chat_id=request.user_id,
                text=get_text("human_called", language),
                parse_mode="HTML"
            )

            async with get_session() as session:
                chat_repo = ChatRepository(session)
                if clean_response:
                    await chat_repo.add_message(request.user_id, "assistant", clean_response, None)

            if user.thread_id:
                thread_service = ThreadService(bot)
                await bot.send_message(
                    chat_id=current_support_group_id.get(),
                    message_thread_id=user.thread_id,
                    text=f"🚨 <b>ВЫЗВАН ЧЕЛОВЕК</b>\n\nПользователь запросил поддержку человека.\nОжидаем описание ситуации.",
                    parse_mode="HTML"
                )
        else:
                                                
            clean_text = response_text.replace("ignore_offtopic", "").replace("IGNORE_OFFTOPIC", "").strip()

            if not clean_text:
                logger.warning(f"AI response became empty after cleaning for pending request {request.id}")
                return

            html_response = markdown_to_html(clean_text)
            response_msg = await bot.send_message(
                chat_id=request.user_id,
                text=html_response,
                parse_mode="HTML"
            )

            async with get_session() as session:
                chat_repo = ChatRepository(session)
                await chat_repo.add_message(request.user_id, "assistant", clean_text, response_msg.message_id)

            if user.thread_id:
                thread_service = ThreadService(bot)
                await thread_service.send_to_thread(user.thread_id, request.message_text, from_user=True, user_id=request.user_id)
                await thread_service.send_to_thread(user.thread_id, clean_text, from_user=False, user_id=request.user_id)
