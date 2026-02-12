
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_language_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
        ],
        [
            InlineKeyboardButton(text="🇺🇿 O'zbek", callback_data="lang_uz"),
            InlineKeyboardButton(text="🇰🇿 Қазақ", callback_data="lang_kz"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
