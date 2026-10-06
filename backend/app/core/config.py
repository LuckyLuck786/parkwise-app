from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (parkwise/), regardless of the process working directory.
# Keeps SQLite, seeds, tests and the smoke test pointed at the SAME database.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "parkwise.db"


class Settings(BaseSettings):
    DATABASE_URL: str = f"sqlite:///{DEFAULT_DB_PATH}"
    SECRET_KEY: str = 'dev-secret-change-me'
    JWT_ALGORITHM: str = 'HS256'
    JWT_EXPIRE_MINUTES: int = 480
    GRACE_PERIOD_MINUTES: int = 10
    TIER2_CUTOFF_HOUR: int = 10
    DEBUG: bool = True
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

settings = Settings()
