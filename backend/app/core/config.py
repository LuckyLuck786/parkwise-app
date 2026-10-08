import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (parkwise/), regardless of the process working directory.
# Keeps SQLite, seeds, tests and the smoke test pointed at the SAME database.
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _pick_sqlite_path() -> Path:
    """Where the SQLite file lives when DATABASE_URL is not set.

    Priority: PARKWISE_DB_PATH env override -> repo root -> /tmp.
    The /tmp fallback exists for serverless hosts (Vercel) where the project
    directory is read-only; there it becomes an ephemeral demo database.
    """
    override = os.environ.get("PARKWISE_DB_PATH")
    if override:
        return Path(override)
    for candidate in (PROJECT_ROOT / "parkwise.db", Path("/tmp") / "parkwise.db"):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            with open(candidate, "a"):
                pass
            return candidate
        except OSError:
            continue
    return Path("/tmp") / "parkwise.db"


DEFAULT_DB_PATH = _pick_sqlite_path()


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

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def _point_postgres_at_psycopg(cls, url: str) -> str:
        """Send bare postgres:// URLs to psycopg 3 — the only driver we ship.

        Neon/Render/Supabase hand out `postgresql://user:pass@host/db?sslmode=...`
        and SQLAlchemy would look for psycopg2 (also possible, but not installed).
        SQLite URLs are untouched.
        """
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


settings = Settings()
