from dataclasses import dataclass, field
from pydantic_settings import BaseSettings
from typing import List, Optional


@dataclass
class BotConfig:
    index: int
    token: str

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///data/bot{self.index}.db"


class Settings(BaseSettings):

    BOT1_TOKEN: str

    BOT2_TOKEN: Optional[str] = None

    BOT3_TOKEN: Optional[str] = None

    ADMIN_IDS: str = ""
    SUPPORT_GROUP_ID: int = 0
    SHARED_DATABASE_URL: str = "sqlite+aiosqlite:///data/shared.db"
    DEFAULT_LANGUAGE: str = "en"

    @property
    def admin_ids(self) -> List[int]:
        if not self.ADMIN_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_IDS.split(',') if x.strip()]

    @property
    def bot_configs(self) -> List[BotConfig]:
        configs = []
        for i in range(1, 4):
            token = getattr(self, f"BOT{i}_TOKEN", None)
            if not token:
                continue
            configs.append(BotConfig(index=i, token=token))
        return configs

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
