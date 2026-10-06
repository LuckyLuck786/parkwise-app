"""Public read endpoints: lots, bays, buildings, live snapshot.

Read-only live status is public (the gate display and any passer-by can check
availability); everything that changes state requires auth.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_optional_user
from app.db.database import get_db
from app.db.models import Building, Lot, User, Waitlist, WaitlistStatus
from app.services import live_service, lot_service
from app.services.clock_service import get_virtual_now

router = APIRouter(prefix="/api/v1", tags=["Live"])


@router.get("/lots")
def list_lots(db: Session = Depends(get_db)):
    """Occupancy + fill prediction per lot (public, read-only)."""
    return lot_service.all_lot_summaries(db)


@router.get("/lots/{lot_id}/bays")
def lot_bays(
    lot_id: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    """SVG grid payload for one lot. Plates are masked unless the viewer is
    admin/gate staff."""
    payload = lot_service.bays_payload(db, lot_id, user)
    if not payload:
        raise HTTPException(status_code=404, detail="Lot not found")
    return payload


@router.get("/buildings")
def list_buildings(db: Session = Depends(get_db)):
    return [
        {"id": b.id, "name": b.name, "lat": b.lat, "lng": b.lng}
        for b in db.query(Building).order_by(Building.name.asc()).all()
    ]


@router.get("/live/snapshot")
def live_snapshot(db: Session = Depends(get_db)):
    """Lightweight payload for the polling fallback: version + lot summaries."""
    state = live_service.current_state(db)
    waiting = (
        db.query(Waitlist).filter(Waitlist.status == WaitlistStatus.waiting).count()
    )
    return {
        "version": state.get("version", 0),
        "server_time": state["server_time"],
        "clock": get_virtual_now(db).isoformat(),
        "waitlist_length": waiting,
        "lots": lot_service.all_lot_summaries(db),
    }
