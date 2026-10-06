"""Virtual demo clock.

Stored in the `app_state` table so it survives process restarts and does not
depend on in-process state (required for serverless deployment).

    virtual_now = virtual_ref + (real_now - real_ref) * speed

With speed = 1.0 and virtual_ref == real_ref the clock is plain UTC time.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.models import AppState, as_utc_naive, utcnow

KEY = "demo_clock"

DEFAULT_STATE: Dict[str, Any] = {"speed": 1.0, "real_ref": None, "virtual_ref": None}


def _naive(dt: datetime) -> datetime:
    return as_utc_naive(dt)


def _load(db: Session) -> Dict[str, Any]:
    row = db.query(AppState).filter(AppState.key == KEY).first()
    if row is None or not isinstance(row.value, dict) or "speed" not in row.value:
        return dict(DEFAULT_STATE)
    return {**DEFAULT_STATE, **row.value}


def _save(db: Session, state: Dict[str, Any]) -> None:
    row = db.query(AppState).filter(AppState.key == KEY).first()
    if row is None:
        db.add(AppState(key=KEY, value=state))
    else:
        row.value = state
    db.commit()


def get_virtual_now(db: Session) -> datetime:
    """Current demo time (naive UTC). Advances with real time × speed."""
    state = _load(db)
    real_now = _naive(utcnow())
    speed = float(state.get("speed", 1.0) or 1.0)
    real_ref = state.get("real_ref")
    virtual_ref = state.get("virtual_ref")
    if not real_ref or not virtual_ref:
        # Never configured -> plain UTC wall clock.
        return real_now
    real_ref_dt = _naive(datetime.fromisoformat(real_ref))
    virtual_ref_dt = _naive(datetime.fromisoformat(virtual_ref))
    elapsed = (real_now - real_ref_dt).total_seconds()
    return virtual_ref_dt + timedelta(seconds=elapsed * speed)


def set_clock(
    db: Session,
    speed: Optional[float] = None,
    set_time: Optional[datetime] = None,
    jump_minutes: Optional[float] = None,
) -> Dict[str, Any]:
    """Change speed, jump, or set the demo clock. Returns the new state."""
    state = _load(db)
    current = get_virtual_now(db)

    if set_time is not None:
        target = _naive(set_time)
    elif jump_minutes is not None:
        target = current + timedelta(minutes=float(jump_minutes))
    else:
        target = current

    new_speed = float(speed) if speed is not None else float(state.get("speed", 1.0) or 1.0)
    new_speed = max(0.0, min(new_speed, 100000.0))

    new_state = {
        "speed": new_speed,
        "real_ref": _naive(utcnow()).isoformat(),
        "virtual_ref": target.isoformat(),
    }
    _save(db, new_state)
    return {"speed": new_speed, "virtual_now": get_virtual_now(db).isoformat()}


def reset_clock(db: Session) -> Dict[str, Any]:
    _save(db, dict(DEFAULT_STATE))
    return {"speed": 1.0, "virtual_now": get_virtual_now(db).isoformat()}
