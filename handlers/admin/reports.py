
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database.database import get_session
from database.repository import AdminRepository, AIProviderRepository
from services.analytics_service import AnalyticsService
from services.ai_service import AIService

router = Router()

@router.callback_query(F.data == "admin_reports")
async def show_reports_menu(callback: CallbackQuery):
    text = """📊 <b>Отчеты и аналитика</b>

Выберите период для генерации отчета:
"""

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сегодня", callback_data="report_today")],
        [InlineKeyboardButton(text="Последние 7 дней", callback_data="report_week")],
        [InlineKeyboardButton(text="Последние 30 дней", callback_data="report_month")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_menu")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("report_"))
async def generate_report(callback: CallbackQuery):
    period = callback.data.split("_")[1]

    await callback.answer("⏳ Генерирую отчет...", show_alert=True)

    try:
        analytics = AnalyticsService()
        start_date, end_date = analytics.get_period_dates(period)

        async with get_session() as session:
            admin_repo = AdminRepository(session)
            ai_provider_repo = AIProviderRepository(session)

            ai_provider = await ai_provider_repo.get_default()

            if ai_provider:
                ai_service = AIService(ai_provider)
                report = await analytics.generate_report(
                    admin_repo,
                    ai_service,
                    start_date,
                    end_date
                )
            else:
                user_count = await admin_repo.get_user_count_by_period(start_date, end_date)
                report = f"""📊 <b>Отчет за период</b>

📅 Период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}

👥 <b>Статистика:</b>
• Новых пользователей: {user_count}
"""

        await callback.message.answer(report, parse_mode="HTML")

    except Exception as e:
        await callback.answer(f"❌ Ошибка генерации отчета: {e}", show_alert=True)
