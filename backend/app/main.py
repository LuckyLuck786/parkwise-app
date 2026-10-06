"""ParkWise FastAPI application."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.database import create_tables

# Import models so metadata is complete before create_all().
from app.db import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title="ParkWise API",
    description=(
        "Priority-based campus parking allocation system: tier quotas, "
        "full-lot alerts, waitlist, predictive warnings and an auditable, "
        "explainable allocation engine. All device input arrives through the "
        "same /api/v1/ingest pipeline (simulator, IR, webcam or manual)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api import admin, auth, events, gate, ingest, lots, me, metrics, users  # noqa: E402

for router in (auth.router, users.router, lots.router, events.router,
               me.router, gate.router, admin.router, metrics.router, ingest.router):
    app.include_router(router)


@app.get("/api/v1/health")
def health_check():
    return {"status": "ok", "service": "parkwise", "version": app.version}


@app.get("/")
def root():
    return {
        "service": "ParkWise API",
        "docs": "/docs",
        "health": "/api/v1/health",
        "live": ["/api/v1/lots", "/api/v1/events/stream", "/api/v1/events/poll"],
    }
