import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncGenerator, Dict

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from database.models import Base
from database.shared_models import SharedBase

logger = logging.getLogger(__name__)

current_bot_db_url: ContextVar[str] = ContextVar('current_bot_db_url', default='')
current_support_group_id: ContextVar[int] = ContextVar('current_support_group_id', default=0)

_engines: Dict[str, AsyncEngine] = {}
_session_makers: Dict[str, async_sessionmaker] = {}

_shared_engine: AsyncEngine = None
_shared_session_maker: async_sessionmaker = None


def _get_engine(db_url: str) -> AsyncEngine:
    if db_url not in _engines:
        _engines[db_url] = create_async_engine(db_url, echo=False, future=True)
    return _engines[db_url]


def _get_session_maker(db_url: str) -> async_sessionmaker:
    if db_url not in _session_makers:
        _session_makers[db_url] = async_sessionmaker(
            _get_engine(db_url),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_makers[db_url]


def _get_shared_engine() -> AsyncEngine:
    global _shared_engine
    if _shared_engine is None:
        _shared_engine = create_async_engine(
            settings.SHARED_DATABASE_URL, echo=False, future=True
        )
    return _shared_engine


def _get_shared_session_maker() -> async_sessionmaker:
    global _shared_session_maker
    if _shared_session_maker is None:
        _shared_session_maker = async_sessionmaker(
            _get_shared_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _shared_session_maker


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    db_url = current_bot_db_url.get()
    if not db_url:
        raise RuntimeError("current_bot_db_url is not set — BotDBMiddleware not applied")
    session_maker = _get_session_maker(db_url)
    async with session_maker() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()


@asynccontextmanager
async def get_shared_session() -> AsyncGenerator[AsyncSession, None]:
    session_maker = _get_shared_session_maker()
    async with session_maker() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()


async def init_bot_db(bot_config) -> None:
    db_url = bot_config.db_url
    engine = _get_engine(db_url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info(f"Bot {bot_config.index} database initialized: {db_url}")

    await _init_bot_defaults(bot_config)


async def _init_bot_defaults(bot_config) -> None:
    from database.repository import ConfigRepository, UserRepository

    db_url = bot_config.db_url
    token = current_bot_db_url.set(db_url)
    try:
        async with get_session() as session:
            config_repo = ConfigRepository(session)
            user_repo = UserRepository(session)

            if not await config_repo.get("privacy_policy_url"):
                await config_repo.set(
                    "privacy_policy_url",
                    "https://cartame.com/privacy",
                    "URL политики конфиденциальности"
                )

            if not await config_repo.get("antiflood_threshold"):
                await config_repo.set("antiflood_threshold", "1", "Порог антифлуда")
            if not await config_repo.get("antiflood_time_window"):
                await config_repo.set("antiflood_time_window", "3", "Временное окно антифлуда (сек)")
            if not await config_repo.get("autoban_duration"):
                await config_repo.set("autoban_duration", "900", "Длительность автобана (сек)")

            for admin_id in settings.admin_ids:
                existing_user = await user_repo.get_by_id(admin_id)
                if not existing_user:
                    await user_repo.create(
                        user_id=admin_id,
                        username=None,
                        first_name=None,
                        last_name=None
                    )
                    await user_repo.set_role(admin_id, "admin")
                    logger.info(f"Bot {bot_config.index}: Created admin user {admin_id}")
                elif existing_user.role != "admin":
                    await user_repo.set_role(admin_id, "admin")
                    logger.info(f"Bot {bot_config.index}: Set admin role for {admin_id}")
    finally:
        current_bot_db_url.reset(token)


async def init_shared_db() -> None:
    engine = _get_shared_engine()

    async with engine.begin() as conn:
        await conn.run_sync(SharedBase.metadata.create_all)

    logger.info("Shared database initialized")

    await _init_shared_defaults()


async def _init_shared_defaults() -> None:
    from database.repository import AIProviderRepository, APIKeyRepository, AIModelRepository

    async with get_shared_session() as session:
        ai_provider_repo = AIProviderRepository(session)
        api_key_repo = APIKeyRepository(session)
        model_repo = AIModelRepository(session)

        all_providers = await ai_provider_repo.get_all()
        if not all_providers:
            openrouter = await ai_provider_repo.create(
                name="openrouter",
                display_name="OpenRouter",
                base_url="https://openrouter.ai/api/v1",
                is_default=True
            )
            await api_key_repo.create(
                provider_id=openrouter.id,
                api_key="your_openrouter_api_key_here",
                name="Ключ 1"
            )
            await model_repo.create(openrouter.id, "deepseek/deepseek-r1-0528:free", "DeepSeek R1 Free", is_default=True)
            await model_repo.create(openrouter.id, "openai/gpt-3.5-turbo", "GPT-3.5 Turbo", is_default=False)
            logger.info("OpenRouter provider created")

            groq = await ai_provider_repo.create(
                name="groq",
                display_name="Groq",
                base_url="https://api.groq.com/openai/v1",
                is_default=False
            )
            await api_key_repo.create(
                provider_id=groq.id,
                api_key="your_groq_api_key_here",
                name="Ключ 1"
            )
            await model_repo.create(groq.id, "llama-3.1-8b-instant", "Llama 3.1 8B", is_default=True)
            await model_repo.create(groq.id, "mixtral-8x7b-32768", "Mixtral 8x7B", is_default=False)
            logger.info("Groq provider created")

            openai_p = await ai_provider_repo.create(
                name="openai",
                display_name="OpenAI",
                base_url=None,
                is_default=False
            )
            await api_key_repo.create(
                provider_id=openai_p.id,
                api_key="your_openai_api_key_here",
                name="Ключ 1"
            )
            await model_repo.create(openai_p.id, "gpt-3.5-turbo", "GPT-3.5 Turbo", is_default=True)
            await model_repo.create(openai_p.id, "gpt-4", "GPT-4", is_default=False)
            logger.info("Default AI providers created in shared DB")


async def close_all_db() -> None:
    global _shared_engine, _shared_session_maker

    for db_url, engine in list(_engines.items()):
        await engine.dispose()
    _engines.clear()
    _session_makers.clear()

    if _shared_engine is not None:
        await _shared_engine.dispose()
        _shared_engine = None
    _shared_session_maker = None

    logger.info("All database connections closed")
