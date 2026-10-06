"""No-show release.

An allotted bay that was never occupied within the grace period returns to the
pool. The release is recorded (allotment status + audit log + driver
notification) and the bay is immediately offered to the head of the waitlist.

Grace comes from the `grace_period_minutes` rule, never a hardcoded constant.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db.models import (
    Allotment,
    AllotmentStatus,
    AuditLog,
    Bay,
    BayState,
    as_utc_naive,
    utcnow,
)
from app.services import notification_service
from app.services.rules_service import get_rule
from app.services.waitlist_service import expire_offer, promote_waitlist_head


def _naive(dt: datetime) -> datetime:
    return as_utc_naive(dt)


def check_and_release_noshows(
    db: Session,
    grace_minutes: Optional[int] = None,
    current_time: Optional[datetime] = None,
) -> List[Allotment]:
    if current_time is None:
        current_time = utcnow()
    current_time = _naive(current_time)
    if grace_minutes is None:
        grace_minutes = int(get_rule(db, "grace_period_minutes", 10))

    threshold = current_time - timedelta(minutes=grace_minutes)

    noshows = (
        db.query(Allotment)
        .filter(
            Allotment.status == AllotmentStatus.allotted,
            Allotment.allotted_at < threshold,
        )
        .all()
    )

    released: List[Allotment] = []
    for allotment in noshows:
        bay = allotment.bay
        if bay is None:
            continue

        allotment.status = AllotmentStatus.no_show_released
        allotment.released_at = current_time
        bay.state = BayState.free

        explanation = dict(allotment.explanation or {})
        explanation["release"] = {
            "reason": "no_show",
            "rule": "grace_period_minutes",
            "grace_minutes": grace_minutes,
            "allotted_at": _naive(allotment.allotted_at).isoformat(),
            "released_at": current_time.isoformat(),
        }
        allotment.explanation = explanation

        db.add(
            AuditLog(
                actor="system",
                action="no_show_release",
                details={
                    "allotment_id": allotment.id,
                    "bay_id": bay.id,
                    "bay": bay.label,
                    "vehicle_id": allotment.vehicle_id,
                    "grace_minutes": grace_minutes,
                },
                ts=current_time,
            )
        )
        db.commit()

        # Close any waitlist offer that pointed at this bay.
        expire_offer(db, bay.id, reason="no_show_release")

        # Tell the driver their hold lapsed.
        if allotment.vehicle is not None:
            notification_service.notify(
                db,
                allotment.vehicle.user_id,
                (
                    f"Your hold on bay {bay.label} expired after {grace_minutes} minutes "
                    f"without arrival. The bay returned to the pool."
                ),
                ts=current_time,
            )

        released.append(allotment)
        # Hand the bay to the head of the waitlist.
        promote_waitlist_head(db, bay.id, current_time)

    return released
