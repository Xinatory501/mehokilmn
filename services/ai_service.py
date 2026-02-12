
import logging
from typing import List, Dict, Optional, AsyncGenerator, Tuple
from openai import AsyncOpenAI, RateLimitError, APIError
from datetime import datetime, timedelta

from database.models import AIProvider, APIKey, AIModel
from database.repository import TrainingRepository, AIProviderRepository, APIKeyRepository, AIModelRepository, UserRepository
from database.database import get_session
from config import settings

logger = logging.getLogger(__name__)

class AIService:

    def __init__(self, provider: AIProvider, api_key: APIKey, model: AIModel):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.client = self._create_client()

    def _create_client(self) -> AsyncOpenAI:
        if self.provider.name == "groq":
            return AsyncOpenAI(
                api_key=self.api_key.api_key,
                base_url="https://api.groq.com/openai/v1"
            )
        elif self.provider.name == "openrouter":
            return AsyncOpenAI(
                api_key=self.api_key.api_key,
                base_url="https://openrouter.ai/api/v1"
            )
        elif self.provider.name == "openai":
            return AsyncOpenAI(api_key=self.api_key.api_key)
        else:
            return AsyncOpenAI(
                api_key=self.api_key.api_key,
                base_url=self.provider.base_url
            )

    @staticmethod
    async def get_service(provider_id: Optional[int] = None) -> Optional['AIService']:
        async with get_session() as session:
            ai_provider_repo = AIProviderRepository(session)
            api_key_repo = APIKeyRepository(session)
            model_repo = AIModelRepository(session)

            if provider_id:
                provider = await ai_provider_repo.get_by_id(provider_id)
            else:
                provider = await ai_provider_repo.get_default()

            if not provider:
                logger.error("No AI provider found")
                return None

            api_key = await api_key_repo.get_available_key(provider.id)
            if not api_key:
                logger.warning(f"No available API keys for provider {provider.name}")
                return None

            model = await model_repo.get_available_model(provider.id)
            if not model:
                logger.warning(f"No available models for provider {provider.name}")
                return None

            return AIService(provider, api_key, model)

    @staticmethod
    async def try_next_key_or_provider(exclude_provider_id: Optional[int] = None) -> Optional[Tuple['AIService', bool]]:
        async with get_session() as session:
            ai_provider_repo = AIProviderRepository(session)
            api_key_repo = APIKeyRepository(session)
            model_repo = AIModelRepository(session)

            providers = await ai_provider_repo.get_all_active()

            for provider in providers:
                if exclude_provider_id and provider.id == exclude_provider_id:
                    logger.info(f"Skipping provider {provider.name} (just failed)")
                    continue

                api_key = await api_key_repo.get_available_key(provider.id)
                if api_key:
                    model = await model_repo.get_available_model(provider.id)
                    if model:
                        logger.info(f"Switched to provider {provider.name} with key {api_key.name or api_key.id} and model {model.model_name}")
                        is_different = True
                        return AIService(provider, api_key, model), is_different

            logger.error("No available API keys/models across all providers")
            return None

    async def update_key_usage(self):
        async with get_session() as session:
            api_key_repo = APIKeyRepository(session)
            await api_key_repo.update_usage(self.api_key.id)

    async def record_error(self, error_message: str):
        async with get_session() as session:
            api_key_repo = APIKeyRepository(session)
            await api_key_repo.set_error(self.api_key.id, error_message[:500])

    async def record_model_error(self, error_message: str, bot=None):
        async with get_session() as session:
            model_repo = AIModelRepository(session)
            await model_repo.record_error(self.model.id, error_message[:500])

            if any(keyword in error_message.lower() for keyword in ['not found', 'model_not_found', 'invalid_model', 'не найден']):
                await model_repo.deactivate(self.model.id)
                logger.warning(f"Model {self.model.model_name} deactivated due to error: {error_message}")

                if bot:
                    await self._notify_all_admins(
                        bot,
                        f"⚠️ <b>МОДЕЛЬ НЕДОСТУПНА</b>\n\n"
                        f"Модель: <code>{self.model.model_name}</code>\n"
                        f"Провайдер: {self.provider.display_name}\n"
                        f"Ошибка: {error_message[:200]}\n\n"
                        f"Модель автоматически деактивирована и удалена из ротации."
                    )

    async def _notify_all_admins(self, bot, message: str):
        async with get_session() as session:
            user_repo = UserRepository(session)
            admins = await user_repo.get_all_admins()

            for admin in admins:
                try:
                    await bot.send_message(chat_id=admin.id, text=message)
                    logger.info(f"Sent model error notification to admin {admin.id}")
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin.id}: {e}")

    async def check_and_reset_limit(self):
        if self.api_key.limit_reset_at and self.api_key.limit_reset_at <= datetime.utcnow():
            async with get_session() as session:
                api_key_repo = APIKeyRepository(session)
                new_reset = datetime.utcnow() + timedelta(hours=24)
                await api_key_repo.reset_limit(self.api_key.id, new_reset)
                logger.info(f"Reset limit for key {self.api_key.id}")

    async def get_system_prompt(self, training_repo: TrainingRepository, language: str = "ru") -> str:
        training_messages = await training_repo.get_all_active()

        descriptions = {
            "ru": "CartaMe - это сервис, который помогает собрать все ваши дисконтные карты в один удобный QR-код.",
            "en": "CartaMe is a service that helps collect all your discount cards in one convenient QR code.",
            "uz": "CartaMe - bu barcha chegirma kartalaringizni bitta qulay QR-kodda jamlashga yordam beradigan xizmat.",
            "kz": "CartaMe - бұл барлық жеңілдік карталарыңызды бір ыңғайлы QR-кодқа жинауға көмектесетін қызмет."
        }

        company_description = descriptions.get(language, descriptions["en"])

        base_prompt = f"""You are a professional AI assistant for CartaMe company.

ABOUT CARTAME:
{company_description}

CRITICAL RULES - FOLLOW STRICTLY:
- Company name is ALWAYS "CartaMe" (not ChronoMe, Cartame, or anything else)
- NO EMOJIS - never use any emoji symbols in responses
- Write ONLY in {language} language - do NOT mix with English, Portuguese, or any other languages
- Use ONLY {language} words - no foreign words mixed in
- Write clean, grammatically correct text
- No corrupted text, no artifacts, no random characters
- Be professional and clear
- Never make up information - only answer based on what you know
- If you don't understand or can't help - say so clearly and suggest calling a human

TEXT QUALITY REQUIREMENTS:
- Every word must be a valid {language} word
- No mixed-language constructions like "Outrosполнялось"
- Proper grammar and sentence structure
- Complete, coherent sentences

SPECIAL COMMAND:
- If user asks for human support or you cannot help - include EXACTLY: "call_people"
- When using call_people, ask user to describe the situation for the support team.

RESPONSE LANGUAGE: {language}

"""
        for msg in training_messages:
            if msg.role == "system":
                base_prompt += f"\n{msg.content}\n"

        return base_prompt

    async def is_relevant_question(self, question: str) -> bool:
        relevance_messages = [
            {"role": "system", "content": """Ты - фильтр вопросов для CartaMe (приложение для магазинов и товаров).
Определи, относится ли вопрос к теме: магазины, товары, покупки, заказы, приложение, сервис.
Ответь ТОЛЬКО "yes" или "no"."""},
            {"role": "user", "content": f"Вопрос: {question}"}
        ]

        try:
            await self.check_and_reset_limit()
            completion = await self.client.chat.completions.create(
                model=self.model.model_name,
                messages=relevance_messages,
                temperature=0.3,
                max_tokens=10
            )
            await self.update_key_usage()
            answer = completion.choices[0].message.content.strip().lower()
            return "yes" in answer
        except:
            return True

    async def get_response_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        user_id: int = None,
        thread_id: int = None,
        bot = None
    ) -> AsyncGenerator[str, None]:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        try:
            await self.check_and_reset_limit()
            stream = await self.client.chat.completions.create(
                model=self.model.model_name,
                messages=full_messages,
                temperature=0.7,
                max_tokens=1024,
                stream=True
            )
            await self.update_key_usage()

            async with get_session() as session:
                model_repo = AIModelRepository(session)
                await model_repo.update_last_used(self.model.id)

            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except (RateLimitError, APIError) as e:
            error_str = str(e)
            logger.warning(f"API error: {error_str}")

            is_model_error = any(keyword in error_str.lower() for keyword in
                                ['not found', 'model_not_found', 'invalid_model', 'не найден', 'model does not exist'])

            if is_model_error:
                await self.record_model_error(error_str, bot)
                async with get_session() as session:
                    model_repo = AIModelRepository(session)
                    next_model = await model_repo.get_available_model(self.provider.id)
                    if next_model and next_model.id != self.model.id:
                        logger.info(f"Switching to next model: {next_model.model_name}")
                        self.model = next_model
                        async for chunk in self.get_response_stream(messages, system_prompt, user_id, thread_id, bot):
                            yield chunk
                        return

            await self.record_error(error_str)
            next_result = await AIService.try_next_key_or_provider(self.provider.id)
            if next_result:
                next_service, _ = next_result
                async for chunk in next_service.get_response_stream(messages, system_prompt, user_id, thread_id, bot):
                    yield chunk
            else:
                if bot and thread_id:
                    try:
                        await bot.send_message(
                            chat_id=settings.SUPPORT_GROUP_ID,
                            message_thread_id=thread_id,
                            text="⚠️ ЛИМИТ AI ЗАКОНЧИЛСЯ\n\nВсе API ключи и модели исчерпаны."
                        )
                    except:
                        pass
                yield "❌ Лимиты всех AI провайдеров исчерпаны. Администратор получил уведомление."

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            await self.record_error(str(e))
            yield "❌ Произошла ошибка при обращении к AI."

    async def get_response(self, messages: List[Dict[str, str]], system_prompt: str, bot=None) -> str:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        try:
            await self.check_and_reset_limit()
            completion = await self.client.chat.completions.create(
                model=self.model.model_name,
                messages=full_messages,
                temperature=0.7,
                max_tokens=1024
            )
            await self.update_key_usage()

            async with get_session() as session:
                model_repo = AIModelRepository(session)
                await model_repo.update_last_used(self.model.id)

            return completion.choices[0].message.content
        except (RateLimitError, APIError) as e:
            error_str = str(e)

            is_model_error = any(keyword in error_str.lower() for keyword in
                                ['not found', 'model_not_found', 'invalid_model', 'не найден', 'model does not exist'])

            if is_model_error:
                await self.record_model_error(error_str, bot)
                async with get_session() as session:
                    model_repo = AIModelRepository(session)
                    next_model = await model_repo.get_available_model(self.provider.id)
                    if next_model and next_model.id != self.model.id:
                        self.model = next_model
                        return await self.get_response(messages, system_prompt, bot)

            await self.record_error(error_str)
            next_result = await AIService.try_next_key_or_provider(self.provider.id)
            if next_result:
                next_service, _ = next_result
                return await next_service.get_response(messages, system_prompt, bot)
            return "❌ Лимиты исчерпаны."
        except Exception as e:
            await self.record_error(str(e))
            return "❌ Ошибка AI."

    async def cluster_questions(self, questions: List[str]) -> List[Dict]:
        if not questions:
            return []

        prompt = f"""Сгруппируй следующие вопросы по смыслу. Верни топ-20 категорий.
{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(questions[:100]))}"""

        try:
            await self.check_and_reset_limit()
            completion = await self.client.chat.completions.create(
                model=self.model.model_name,
                messages=[
                    {"role": "system", "content": "Ты - аналитик, группирующий вопросы."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=2048
            )
            await self.update_key_usage()
            response = completion.choices[0].message.content
            clusters = []
            for line in response.split('\n'):
                if line.strip():
                    clusters.append({"description": line.strip()})
            return clusters[:20]
        except Exception as e:
            await self.record_error(str(e))
            return []
