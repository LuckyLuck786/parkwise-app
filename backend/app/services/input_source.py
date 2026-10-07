"""Admin input-source toggle — the demo-day failure plan's one switch.

Modes (stored in `app_state`, so the value survives restarts and stays
serverless-safe — no in-process globals):

    live            default: every source (simulator, ir_sensor, webcam,
                    manual) is accepted by the ingestion pipeline.
    simulated_only  hardware sources (ir_sensor, webcam) are rejected with a
                    clear error so a misbehaving device cannot corrupt a live
                    demo; the simulator and manual admin overrides keep
                    working, which is exactly the documented fallback.

This gates *ingestion only* — no code path changes. The hardware, simulator
and manual inputs still all POST to the same /api/v1/ingest endpoints; the
toggle decides whether hardware-sourced events are accepted right now.
"""
from typing import Dict

from sqlalchemy.orm import Session

from app.db.models import AppState, AuditLog, EventSource, as_utc_naive, utcnow

KEY = "input_source"
DEFAULT_MODE = "live"
MODES = ("live", "simulated_only")
HARDWARE_SOURCES = {EventSource.ir_sensor, EventSource.webcam}


def get_mode(db: Session) -> str:
    row = db.query(AppState).filter(AppState.key == KEY).first()
    if row is None or not isinstance(row.value, dict):
        return DEFAULT_MODE
    mode = str(row.value.get("mode", DEFAULT_MODE))
    return mode if mode in MODES else DEFAULT_MODE


def set_mode(db: Session, mode: str, actor: str) -> str:
    if mode not in MODES:
        raise ValueError(f"Unknown input-source mode: {mode!r}")
    row = db.query(AppState).filter(AppState.key == KEY).first()
    value: Dict[str, object] = {"mode": mode, "updated_by": actor}
    if row is None:
        db.add(AppState(key=KEY, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
    db.add(
        AuditLog(
            actor=actor,
            action="input_source_changed",
            details={"mode": mode},
            ts=as_utc_naive(utcnow()),
        )
    )
    db.commit()
    return mode


def source_allowed(db: Session, source) -> bool:
    """True when events from `source` may change bay occupancy right now."""
    if get_mode(db) == "live":
        return True
    try:
        src = EventSource(source)
    except ValueError:
        return True  # unknown sources are validated by the schema anyway
    return src not in HARDWARE_SOURCES
