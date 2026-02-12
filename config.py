from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):

    BOT_TOKEN: str
    SUPPORT_GROUP_ID: int

    INITIAL_ADMIN_IDS: str = ""

    DATABASE_URL: str = "sqlite+aiosqlite:///data/cartame_bot.db"
    DEFAULT_LANGUAGE: str = "en"

    @property
    def admin_ids(self) -> List[int]:
        if not self.INITIAL_ADMIN_IDS:
            return []
        return [int(id.strip()) for id in self.INITIAL_ADMIN_IDS.split(',') if id.strip()]

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
