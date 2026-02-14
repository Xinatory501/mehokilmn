
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from database.database import get_session
from database.repository import UserRepository
from keyboards.admin import get_admin_menu_keyboard
from filters.admin import AdminFilter

router = Router()

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    user_id = message.from_user.id

    async with get_session() as session:
        user_repo = UserRepository(session)
        if not await user_repo.is_admin(user_id):
            await message.answer("❌ У вас нет прав администратора.")
            return

    async with get_session() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(user_id)

        if not user:
            user = await user_repo.create(
                user_id=user_id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )
            await user_repo.set_role(user_id, "admin")
            language = "ru"
        else:
            language = user.language

        if user.role != "admin":
            await user_repo.set_role(user_id, "admin")

    admin_text = "👨‍💼 <b>Панель администратора</b>\n\nВыберите раздел:"

    await message.answer(
        admin_text,
        reply_markup=get_admin_menu_keyboard(language),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "admin_menu")
async def back_to_admin_menu(callback: CallbackQuery):
    user_id = callback.from_user.id

    async with get_session() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(user_id)
        language = user.language if user else "en"

    admin_text = "👨‍💼 <b>Панель администратора</b>\n\nВыберите раздел:"

    await callback.message.edit_text(
        admin_text,
        reply_markup=get_admin_menu_keyboard(language),
        parse_mode="HTML"
    )
    await callback.answer()
