
import logging
from datetime import datetime, timedelta
from typing import List, Dict
from database.repository import AdminRepository
from services.ai_service import AIService

logger = logging.getLogger(__name__)

class AnalyticsService:

    async def generate_report(
        self,
        admin_repo: AdminRepository,
        ai_service: AIService,
        start_date: datetime,
        end_date: datetime
    ) -> str:
        user_count = await admin_repo.get_user_count_by_period(start_date, end_date)
        questions_data = await admin_repo.get_top_questions(start_date, end_date, limit=100)

        questions = [q["content"] for q in questions_data]

        clusters = []
        if questions:
            clusters = await ai_service.cluster_questions(questions)

        report = f"""📊 <b>Отчет за период</b>

📅 Период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}

👥 <b>Статистика пользователей:</b>
• Новых пользователей: {user_count}
• Всего вопросов: {len(questions)}

"""

        if clusters:
            report += "\n📋 <b>Топ категорий вопросов:</b>\n\n"
            for i, cluster in enumerate(clusters, 1):
                report += f"{i}. {cluster['description']}\n"

        return report

    @staticmethod
    def get_period_dates(period: str) -> tuple[datetime, datetime]:
        now = datetime.utcnow()

        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif period == "week":
            start = now - timedelta(days=7)
            end = now
        elif period == "month":
            start = now - timedelta(days=30)
            end = now
        else:
            start = now - timedelta(days=7)
            end = now

        return start, end
