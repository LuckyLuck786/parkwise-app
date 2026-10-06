"""Predictions and live-update endpoints (SSE stream + polling fallback)."""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.database import SessionLocal, get_db
from app.db.models import Lot
from app.services import live_service, prediction_service
from app.services.clock_service import get_virtual_now
from app.services.rules_service import get_rule

router = APIRouter(prefix="/api/v1", tags=["Predictions & Live"])


@router.get("/predictions")
def predictions(db: Session = Depends(get_db)):
    """Per-lot fill-time prediction.

    Heuristic, not AI: an empirical hourly arrival profile computed from the
    last 14 days of history, projected forward from the current occupancy.
    The payload labels the method and confidence explicitly.
    """
    now = get_virtual_now(db)
    warn_minutes = int(get_rule(db, "prediction_warning_minutes", 30))
    out = prediction_service.predict_all_lots(db, current_time=now)
    for item in out:
        minutes = item.get("minutes_until_full")
        item["within_warning_window"] = bool(
            not item.get("is_full_now") and minutes is not None and minutes <= warn_minutes
        )
    return {
        "generated_at": now.isoformat(),
        "warning_threshold_minutes": warn_minutes,
        "disclaimer": (
            "Statistical heuristic built from historical arrival patterns — "
            "not a machine-learning model and not a guarantee."
        ),
        "predictions": out,
    }


@router.get("/events/poll")
def events_poll(
    since: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Polling fallback for hosts that cannot hold an SSE connection."""
    return live_service.poll(db, since)


@router.get("/events/stream")
async def events_stream(request: Request):
    """Server-Sent Events: emits `{"type":"state","version":N}` whenever the
    database state version changes, plus a heartbeat every ~15s.

    Falls back to GET /api/v1/events/poll when the connection drops.
    """

    async def generator():
        yield ": connected\n\n"
        last_version: Optional[int] = None
        ticks = 0
        while True:
            if await request.is_disconnected():
                break
            db = SessionLocal()
            try:
                state = live_service.current_state(db)
            finally:
                db.close()
            version = state.get("version", 0)
            if version != last_version:
                payload = {
                    "type": "state",
                    "version": version,
                    "server_time": state.get("server_time"),
                    "last_kind": state.get("last_kind"),
                }
                yield f"data: {json.dumps(payload)}\n\n"
                last_version = version
            ticks += 1
            if ticks % 5 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(2.0)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
