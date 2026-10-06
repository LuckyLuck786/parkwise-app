"""Live-state version counter.

A single integer in `app_state` that every mutation bumps. Clients either
stream it over SSE or poll GET /api/v1/events/poll — same payload either way,
so the app degrades gracefully to polling on serverless hosts that cannot hold
a long-lived connection.

No in-process state: the version lives in the database.
"""
import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.models import AppState, as_utc_naive, utcnow

KEY = "state_version"

# Event kinds that imply a client should refresh a given view.
EVENT_HINTS = {
    "bay": ["live", "lots"],
    "allocation": ["live", "lots", "me", "gate"],
    "waitlist": ["me", "admin"],
    "notification": ["me"],
    "rules": ["rules", "live"],
    "device": ["admin"],
    "conflict": ["admin"],
}


def get_version(db: Session) -> int:
    row = db.query(AppState).filter(AppState.key == KEY).first()
    if row is None or not isinstance(row.value, dict):
        return 0
    try:
        return int(row.value.get("version", 0))
    except (TypeError, ValueError):
        return 0


def bump(db: Session, kind: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> int:
    """Increment the version and remember the last event kind."""
    row = db.query(AppState).filter(AppState.key == KEY).first()
    current = get_version(db)
    value: Dict[str, Any] = {"version": current + 1, "ts": as_utc_naive(utcnow()).isoformat()}
    if kind:
        value["last_kind"] = kind
        if payload:
            value["last_payload"] = payload
    if row is None:
        db.add(AppState(key=KEY, value=value))
    else:
        row.value = value
        row.updated_at = as_utc_naive(utcnow())
    db.commit()
    return current + 1


def current_state(db: Session) -> Dict[str, Any]:
    row = db.query(AppState).filter(AppState.key == KEY).first()
    data = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
    data.setdefault("version", 0)
    data["server_time"] = as_utc_naive(utcnow()).isoformat()
    return data


def poll(db: Session, since: int) -> Dict[str, Any]:
    state = current_state(db)
    return {
        "version": state.get("version", 0),
        "changed": state.get("version", 0) != since,
        "since": since,
        "server_time": state["server_time"],
        "last_kind": state.get("last_kind"),
    }
