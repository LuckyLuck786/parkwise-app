"""Vercel entrypoint — the SAME FastAPI app as a single serverless function.

Vercel's Python runtime detects a FastAPI instance named `app` in api/index.py
(zero-config). Nothing here is Vercel-specific business logic:

* sys.path is adjusted so `app.*` (backend/) and `scripts.*` import.
* A tiny middleware strips a possible `/api/index` mount prefix, so FastAPI
  sees the original `/api/v1/...` path no matter how the rewrite arrives.
* On cold start the idempotent seed runs if the database is empty, so a fresh
  (ephemeral) SQLite file on a serverless host is usable immediately.

Set DATABASE_URL (e.g. Neon Postgres) for persistent storage; without it the
app falls back to SQLite (repo root locally, /tmp on serverless).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.main import app  # noqa: E402,F401  (Vercel looks for `app`)


@app.middleware("http")
async def _strip_function_mount_prefix(request, call_next):
    """If the request reached us as /api/index[/...], drop that mount prefix."""
    path = request.url.path
    for prefix in ("/api/index.py", "/api/index"):
        if path.startswith(prefix):
            remaining = path[len(prefix):] or "/"
            request.scope["path"] = remaining
            request.scope["raw_path"] = remaining.encode()
            break
    return await call_next(request)


def _cold_start_seed() -> None:
    """Idempotent: create tables and seed demo data only if the DB is empty."""
    from app.db.database import SessionLocal, create_tables

    create_tables()
    db = SessionLocal()
    try:
        from app.db.models import User

        if db.query(User).count() == 0:
            from scripts.seed import seed

            seed()
    finally:
        db.close()


_cold_start_seed()
