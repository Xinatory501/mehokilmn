
import shutil
import os
from datetime import datetime

class BackupService:

    def __init__(self, db_path: str = "cartame_bot.db"):
        self.db_path = db_path

    async def create_backup(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"backup_{timestamp}.db"

        shutil.copy2(self.db_path, backup_path)
        return backup_path

    async def restore_backup(self, backup_path: str):
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, self.db_path)
