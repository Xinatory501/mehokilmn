from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.database import get_session
from database.repository import UserRepository, ConfigRepository
from keyboards.language import get_language_keyboard
from keyboards.menu import get_main_menu_keyboard
from locales.loader import get_text
from services.thread_service import ThreadService

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name

    async with get_session() as session:
        user_repo = UserRepository(session)
        config_repo = ConfigRepository(session)

        user = await user_repo.get_by_id(user_id)

        if not user:
            privacy_url = await config_repo.get("privacy_policy_url") or "https://cartame.com/privacy"

            welcome_text = (
                "👋 Welcome to CartaMe Support Bot!\n\n"
                f"Before we begin, please review our <a href='{privacy_url}'>Privacy Policy</a>.\n\n"
                "Please select your language:"
            )

            await message.answer(
                welcome_text,
                reply_markup=get_language_keyboard(),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        else:
            language = user.language
            greeting = get_text("greeting", language)

            await message.answer(
                greeting,
                reply_markup=get_main_menu_keyboard(language, has_history=True)
            )

@router.callback_query(F.data.startswith("lang_"))
async def choose_language(callback: CallbackQuery, state: FSMContext):
    language = callback.data.split("_")[1]
    user_id = callback.from_user.id
    username = callback.from_user.username
    first_name = callback.from_user.first_name
    last_name = callback.from_user.last_name

    bot = callback.bot

    async with get_session() as session:
        user_repo = UserRepository(session)

        user = await user_repo.get_by_id(user_id)

        if not user:
            user = await user_repo.create(user_id, username, first_name, last_name)

            thread_service = ThreadService(bot)
            await thread_service.create_thread_for_user(user_id, username, first_name, user_repo)

        await user_repo.update_language(user_id, language)

    greeting = get_text("greeting", language)

    await callback.message.edit_text(
        greeting,
        reply_markup=get_main_menu_keyboard(language, has_history=False)
    )
    await callback.answer()
