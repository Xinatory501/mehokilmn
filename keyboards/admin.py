
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from locales.loader import get_text

def get_admin_menu_keyboard(language: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(
            text=get_text("manage_api_keys", language),
            callback_data="admin_api_keys"
        )],
        [InlineKeyboardButton(
            text="⚡ Настройки антифлуда",
            callback_data="admin_antiflood"
        )],
        [InlineKeyboardButton(
            text=get_text("manage_privacy", language),
            callback_data="admin_privacy"
        )],
        [InlineKeyboardButton(
            text=get_text("manage_training", language),
            callback_data="admin_training"
        )],
        [InlineKeyboardButton(
            text=get_text("manage_database", language),
            callback_data="admin_database"
        )],
        [InlineKeyboardButton(
            text=get_text("user_info", language),
            callback_data="admin_user_info"
        )],
        [InlineKeyboardButton(
            text=get_text("reports", language),
            callback_data="admin_reports"
        )],
        [InlineKeyboardButton(
            text=get_text("back_to_menu", language),
            callback_data="menu_back"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_user_actions_keyboard(language: str, user_id: int, is_banned: bool, is_admin: bool) -> InlineKeyboardMarkup:
    keyboard = []

    if is_banned:
        keyboard.append([InlineKeyboardButton(
            text="✅ Разбанить",
            callback_data=f"admin_unban_{user_id}"
        )])
    else:
        keyboard.append([InlineKeyboardButton(
            text="❌ Забанить",
            callback_data=f"admin_ban_{user_id}"
        )])

    if is_admin:
        keyboard.append([InlineKeyboardButton(
            text="👤 Снять админа",
            callback_data=f"admin_revoke_{user_id}"
        )])
    else:
        keyboard.append([InlineKeyboardButton(
            text="👨‍💼 Дать админа",
            callback_data=f"admin_grant_{user_id}"
        )])

    keyboard.append([InlineKeyboardButton(
        text=get_text("back", language),
        callback_data="admin_menu"
    )])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
