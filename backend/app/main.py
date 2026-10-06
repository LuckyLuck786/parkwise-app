"""ParkWise FastAPI application (Phase 1 skeleton: data model + health)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.database import create_tables

# Import models so metadata is complete before create_all().
from app.db import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title="ParkWise API",
    description="Priority-based campus parking allocation system.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/api/v1/health")
def health_check():
    return {"status": "ok", "service": "parkwise", "version": app.version}
