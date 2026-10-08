from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if IS_SQLITE else {}

engine_kwargs: dict = {"connect_args": connect_args}
if not IS_SQLITE:
    # Serverless (Vercel) + a pooled Postgres proxy idles connections out, so every
    # instance keeps a tiny pool and drops stale sockets instead of erroring.
    engine_kwargs.update(pool_pre_ping=True, pool_recycle=280,
                         pool_size=2, max_overflow=2)

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Additive, idempotent schema migrations for pre-existing databases.
# (create_all() creates missing tables but never adds missing columns.)
MIGRATIONS = [
    ("users", "destination_building_id TEXT", "destination_building_id"),
]


def run_migrations():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, ddl, column in MIGRATIONS:
            if table not in existing_tables:
                continue
            columns = {c["name"] for c in inspector.get_columns(table)}
            if column not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def create_tables():
    Base.metadata.create_all(bind=engine)
    run_migrations()
