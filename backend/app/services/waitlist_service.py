"""Waitlist: ordering, promotion, offer holds and notifications.

Ordering rule: priority tier (1 first), then arrival time. For a specific lot,
entries that named that lot are considered before entries that named another.

When a bay frees, the head of the eligible queue is offered the bay. The bay is
held as a normal allotment, so the standard grace period applies: if the driver
never arrives the no-show release frees it again.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.db.models import (
    Allotment,
    AllotmentStatus,
    Bay,
    BayState,
    User,
    Vehicle,
    Waitlist,
    WaitlistStatus,
    utcnow,
)
from app.services import notification_service
from app.services.rules_service import get_rule


def add_to_waitlist(
    db: Session,
    vehicle_id: str,
    lot_pref_id: Optional[str] = None,
    current_time: Optional[datetime] = None,
) -> Waitlist:
    """Add (or return the existing) waiting entry for this vehicle."""
    existing = (
        db.query(Waitlist)
        .filter(
            Waitlist.vehicle_id == vehicle_id,
            Waitlist.status == WaitlistStatus.waiting,
        )
        .first()
    )
    if existing:
        return existing

    entry = Waitlist(
        vehicle_id=vehicle_id,
        lot_pref_id=lot_pref_id,
        status=WaitlistStatus.waiting,
        created_at=current_time or utcnow(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_waitlist_queue(db: Session, lot_id: Optional[str] = None) -> List[Waitlist]:
    """Waiting entries in priority order: tier asc, then arrival time asc.

    When `lot_id` is given, entries that prefer that lot come first, then
    entries with no preference, then entries preferring another lot.
    """
    query = db.query(Waitlist).join(Vehicle).join(User).filter(
        Waitlist.status == WaitlistStatus.waiting
    )
    order = [User.priority_tier.asc(), Waitlist.created_at.asc()]
    if lot_id:
        pref_rank = case(
            (Waitlist.lot_pref_id == lot_id, 0),
            (Waitlist.lot_pref_id.is_(None), 1),
            else_=2,
        )
        order = [pref_rank] + order
    return query.order_by(*order).all()


def get_position(db: Session, waitlist_id: str) -> Optional[int]:
    """1-based position of an entry in the global queue."""
    queue = get_waitlist_queue(db)
    for idx, entry in enumerate(queue, start=1):
        if entry.id == waitlist_id:
            return idx
    return None


def eligible_for_bay(db: Session, entry: Waitlist, bay: Bay, current_time: datetime) -> Optional[str]:
    """Return None if `entry` may take `bay`, else the reason it may not."""
    vehicle = entry.vehicle
    if vehicle is None:
        return "vehicle_missing"
    if vehicle.type != bay.type:
        return f"vehicle_type_mismatch ({vehicle.type.value} vs {bay.type.value})"

    user = vehicle.user
    if user is None:
        return "user_missing"

    active = (
        db.query(Allotment)
        .join(Vehicle, Allotment.vehicle_id == Vehicle.id)
        .filter(
            Vehicle.user_id == user.id,
            Allotment.status.in_([AllotmentStatus.allotted, AllotmentStatus.occupied]),
        )
        .first()
    )
    if active:
        return "driver_already_holds_a_bay"

    if bay.is_accessible and get_rule(db, "accessible_reserved_for_tier1", True):
        if user.priority_tier != 1 and not user.needs_accessible:
            return "accessible_bay_reserved_for_tier1"

    if bay.reserved_tier == 2:
        cutoff = int(get_rule(db, "tier2_cutoff_hour", 10))
        if user.priority_tier not in (1, 2) and current_time.hour < cutoff:
            return f"bay_reserved_for_tier2_until_{cutoff:02d}:00"

    return None


def promote_waitlist_head(
    db: Session,
    freed_bay_id: str,
    current_time: Optional[datetime] = None,
) -> Optional[Allotment]:
    """Offer a just-freed bay to the highest-priority eligible driver.

    The bay is held with a normal allotment (so the grace period applies) and
    the driver is notified in-app.
    """
    if current_time is None:
        current_time = utcnow()

    bay = db.query(Bay).filter(Bay.id == freed_bay_id).first()
    if bay is None or bay.state != BayState.free:
        return None

    queue = get_waitlist_queue(db, bay.lot_id)
    skipped = []
    for entry in queue:
        reason = eligible_for_bay(db, entry, bay, current_time)
        if reason is not None:
            skipped.append({"waitlist_id": entry.id, "reason": reason})
            continue

        grace = int(get_rule(db, "grace_period_minutes", 10))
        entry.status = WaitlistStatus.offered
        entry.offered_at = current_time
        entry.offered_bay_id = bay.id

        explanation = {
            "rule_applied": "waitlist_promotion",
            "ordering_rule": "priority_tier_then_arrival_time",
            "user_tier": entry.vehicle.user.priority_tier,
            "bay": bay.label,
            "lot": bay.lot.name if bay.lot else None,
            "hold_minutes": grace,
            "skipped_entries": skipped,
        }

        allotment = Allotment(
            vehicle_id=entry.vehicle_id,
            bay_id=bay.id,
            status=AllotmentStatus.allotted,
            allotted_at=current_time,
            explanation=explanation,
        )
        db.add(allotment)
        bay.state = BayState.allotted

        notification_service.notify(
            db,
            entry.vehicle.user_id,
            (
                f"A bay freed up: {bay.label} in {bay.lot.name if bay.lot else 'the lot'} is "
                f"held for you for {grace} minutes. Drive in before it is released."
            ),
            ts=current_time,
        )
        db.commit()
        db.refresh(allotment)
        return allotment

    return None


def expire_offer(db: Session, bay_id: str, reason: str = "bay_released_before_arrival") -> None:
    """Close out an offer whose bay got taken back (no-show release)."""
    entries = (
        db.query(Waitlist)
        .filter(
            Waitlist.offered_bay_id == bay_id,
            Waitlist.status == WaitlistStatus.offered,
        )
        .all()
    )
    for entry in entries:
        entry.status = WaitlistStatus.expired
    if entries:
        db.commit()


def fulfill_offer(db: Session, bay_id: str) -> None:
    """Mark the offer as fulfilled once the vehicle actually occupies the bay."""
    entries = (
        db.query(Waitlist)
        .filter(
            Waitlist.offered_bay_id == bay_id,
            Waitlist.status == WaitlistStatus.offered,
        )
        .all()
    )
    for entry in entries:
        entry.status = WaitlistStatus.fulfilled
    if entries:
        db.commit()


def leave_waitlist(db: Session, waitlist_id: str, user_id: str) -> bool:
    """Driver leaves the queue voluntarily."""
    entry = (
        db.query(Waitlist)
        .join(Vehicle, Waitlist.vehicle_id == Vehicle.id)
        .filter(Waitlist.id == waitlist_id, Vehicle.user_id == user_id)
        .first()
    )
    if entry is None or entry.status != WaitlistStatus.waiting:
        return False
    entry.status = WaitlistStatus.cancelled
    db.commit()
    return True
