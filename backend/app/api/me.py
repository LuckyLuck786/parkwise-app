"""Driver's own view: parking status, notifications, waitlist, leave queue."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import (
    Allotment,
    AllotmentStatus,
    Building,
    User,
    Vehicle,
    Waitlist,
    WaitlistStatus,
)
from app.schemas.auth import UserOut
from app.services import live_service, notification_service
from app.services.distance_utils import estimate_walk_meters
from app.services.rules_service import get_rule
from app.services.waitlist_service import get_position

router = APIRouter(prefix="/api/v1", tags=["Me"])


class LeaveWaitlistRequest(BaseModel):
    waitlist_id: Optional[str] = None


def _open_allotment(db: Session, user: User) -> Optional[Allotment]:
    return (
        db.query(Allotment)
        .join(Vehicle, Allotment.vehicle_id == Vehicle.id)
        .filter(
            Vehicle.user_id == user.id,
            Allotment.status.in_([AllotmentStatus.allotted, AllotmentStatus.occupied]),
        )
        .first()
    )


@router.get("/me/status")
def my_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Everything the driver's home screen needs in one call."""
    vehicles = db.query(Vehicle).filter(Vehicle.user_id == user.id).all()
    active = next((v for v in vehicles if v.active_today), None)

    allotment = _open_allotment(db, user)
    current = None
    if allotment is not None:
        bay = allotment.bay
        dest = None
        if user.destination_building_id:
            dest = db.query(Building).filter(Building.id == user.destination_building_id).first()
        walk_m = estimate_walk_meters(bay, dest)
        current = {
            "allotment_id": allotment.id,
            "status": allotment.status.value,
            "bay": {
                "id": bay.id,
                "label": bay.label,
                "lot_id": bay.lot_id,
                "lot_name": bay.lot.name if bay.lot else None,
                "is_accessible": bay.is_accessible,
                "type": bay.type.value,
                "x": bay.x,
                "y": bay.y,
            },
            "allotted_at": allotment.allotted_at.isoformat() if allotment.allotted_at else None,
            "arrived_at": allotment.arrived_at.isoformat() if allotment.arrived_at else None,
            "destination": dest.name if dest else None,
            "walk_hint": {
                "meters_estimate": round(walk_m, 0),
                "minutes_estimate": max(1, round(walk_m / 80.0)),
                "text": (
                    f"Walk ~{round(walk_m, -1):.0f} m to {dest.name if dest else 'your destination'} "
                    f"(~{max(1, round(walk_m / 80.0))} min)"
                ),
                "note": "Estimated from the lot layout grid, not a routed path.",
            },
            "explanation": allotment.explanation,
        }

    waiting_entry = (
        db.query(Waitlist)
        .join(Vehicle, Waitlist.vehicle_id == Vehicle.id)
        .filter(Vehicle.user_id == user.id, Waitlist.status == WaitlistStatus.waiting)
        .first()
    )
    waitlist = None
    if waiting_entry is not None:
        pref = waiting_entry.lot_pref
        waitlist = {
            "id": waiting_entry.id,
            "position": get_position(db, waiting_entry.id),
            "joined_at": waiting_entry.created_at.isoformat() if waiting_entry.created_at else None,
            "preferred_lot": pref.name if pref else None,
        }

    unread = (
        db.query(notification_service.Notification)
        .filter(
            notification_service.Notification.user_id == user.id,
            notification_service.Notification.read.is_(False),
        )
        .count()
    )

    grace = int(get_rule(db, "grace_period_minutes", 10))
    return {
        "user": UserOut.model_validate(user).model_dump(),
        "active_vehicle": (
            {
                "id": active.id,
                "plate_or_tag_id": active.plate_or_tag_id,
                "type": active.type.value,
            }
            if active else None
        ),
        "vehicle_count": len(vehicles),
        "current_parking": current,
        "waitlist": waitlist,
        "unread_notifications": unread,
        "grace_minutes": grace,
        "destination_building_id": user.destination_building_id,
    }


@router.get("/me/notifications", response_model=List[dict])
def my_notifications(
    unread: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    notes = notification_service.list_notifications(db, user.id, limit=min(limit, 200))
    if unread:
        notes = [n for n in notes if not n.read]
    return [
        {
            "id": n.id,
            "message": n.message,
            "channel": n.channel.value,
            "ts": n.ts.isoformat() if n.ts else None,
            "read": n.read,
        }
        for n in notes
    ]


@router.post("/me/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ok = notification_service.mark_read(db, user.id, notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    live_service.bump(db, "notification")
    return {"success": True}


@router.post("/me/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = 0
    for n in notification_service.list_notifications(db, user.id, limit=500):
        if not n.read:
            n.read = True
            count += 1
    db.commit()
    live_service.bump(db, "notification")
    return {"success": True, "marked": count}


@router.get("/me/waitlist")
def my_waitlist(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    entries = (
        db.query(Waitlist)
        .join(Vehicle, Waitlist.vehicle_id == Vehicle.id)
        .filter(Vehicle.user_id == user.id)
        .order_by(Waitlist.created_at.desc())
        .all()
    )
    return [
        {
            "id": e.id,
            "status": e.status.value,
            "position": get_position(db, e.id) if e.status == WaitlistStatus.waiting else None,
            "preferred_lot": e.lot_pref.name if e.lot_pref else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "offered_at": e.offered_at.isoformat() if e.offered_at else None,
            "offered_bay": e.offered_bay.label if e.offered_bay else None,
        }
        for e in entries
    ]


@router.post("/waitlist/leave")
def leave_waitlist(
    payload: LeaveWaitlistRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Driver gives up their queue place."""
    from app.services.waitlist_service import leave_waitlist as _leave

    entry_id = payload.waitlist_id
    if not entry_id:
        waiting = (
            db.query(Waitlist)
            .join(Vehicle, Waitlist.vehicle_id == Vehicle.id)
            .filter(Vehicle.user_id == user.id, Waitlist.status == WaitlistStatus.waiting)
            .first()
        )
        if waiting is None:
            raise HTTPException(status_code=404, detail="You are not on a waitlist")
        entry_id = waiting.id

    if not _leave(db, entry_id, user.id):
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    live_service.bump(db, "waitlist")
    return {"success": True}
