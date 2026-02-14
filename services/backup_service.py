
import shutil
import os
from datetime import datetime


def _current_db_path() -> str:
    from database.database import current_bot_db_url
    url = current_bot_db_url.get()
    if url:
        return url.replace("sqlite+aiosqlite:///", "")
    return "data/bot1.db"


class BackupService:

    def __init__(self, db_path: str = None):
        self.db_path = db_path or _current_db_path()

    async def create_backup(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"backup_{timestamp}.db"

        shutil.copy2(self.db_path, backup_path)
        return backup_path

    async def restore_backup(self, backup_path: str):
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, self.db_path)
