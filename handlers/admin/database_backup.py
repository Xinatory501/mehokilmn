
from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
import os

from services.backup_service import BackupService

router = Router()

@router.callback_query(F.data == "admin_database")
async def show_database_menu(callback: CallbackQuery):
    text = """💾 <b>Работа с базой данных</b>

<b>Доступные операции:</b>
• Скачать бекап - создает копию текущей БД
• Загрузить бекап - восстанавливает БД из файла

⚠️ <b>Внимание:</b> При восстановлении текущая БД будет заменена!
"""

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скачать бекап", callback_data="download_backup")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_menu")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "download_backup")
async def download_backup(callback: CallbackQuery):
    await callback.answer("⏳ Создаю бекап...", show_alert=True)

    try:
        backup_service = BackupService()
        backup_path = await backup_service.create_backup()

        file = FSInputFile(backup_path)
        await callback.message.answer_document(
            file,
            caption="💾 Бекап базы данных создан успешно"
        )

        if os.path.exists(backup_path):
            os.remove(backup_path)

        await callback.answer("✅ Бекап отправлен!", show_alert=True)

    except Exception as e:
        await callback.answer(f"❌ Ошибка создания бекапа: {e}", show_alert=True)
