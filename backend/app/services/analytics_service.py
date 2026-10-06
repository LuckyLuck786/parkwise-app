"""Admin analytics: occupancy, utilization, queue, conflicts, no-show rate,
device health and the audit trail — all computed from the database."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    Allotment,
    AllotmentStatus,
    AuditLog,
    Device,
    DeviceStatus,
    Lot,
    User,
    Vehicle,
    Waitlist,
    WaitlistStatus,
    as_utc_naive,
    utcnow,
)
from app.services import lot_service
from app.services.clock_service import get_virtual_now
from app.services.reconcile_service import get_active_conflicts


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    return as_utc_naive(dt)


def no_show_stats(db: Session) -> Dict[str, Any]:
    """No-show rate = released / (completed + released + cancelled)."""
    counts = dict(
        db.query(Allotment.status, func.count(Allotment.id))
        .group_by(Allotment.status)
        .all()
    )
    completed = counts.get(AllotmentStatus.completed, 0)
    released = counts.get(AllotmentStatus.no_show_released, 0)
    cancelled = counts.get(AllotmentStatus.cancelled, 0)
    denominator = completed + released + cancelled
    rate = round(released * 100.0 / denominator, 1) if denominator else 0.0
    return {
        "no_show_released": released,
        "completed": completed,
        "cancelled": cancelled,
        "open": counts.get(AllotmentStatus.allotted, 0) + counts.get(AllotmentStatus.occupied, 0),
        "no_show_rate_pct": rate,
        "definition": "no_show_released / (completed + no_show_released + cancelled), all time",
    }


def utilization_series(db: Session, days: int = 14) -> List[Dict[str, Any]]:
    """Occupied bay-minutes per day / capacity, from historical allotments."""
    now = _naive(utcnow())
    start_day = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    capacity = db.query(Lot).count() and sum(
        l.capacity for l in db.query(Lot).all()
    )
    if not capacity:
        return []

    rows = (
        db.query(Allotment.arrived_at, Allotment.released_at, Allotment.allotted_at)
        .filter(
            Allotment.status.in_([
                AllotmentStatus.completed,
                AllotmentStatus.occupied,
                AllotmentStatus.no_show_released,
            ])
        )
        .all()
    )

    buckets: Dict[str, float] = {}
    for arrived, released, allotted in rows:
        start = _naive(arrived) or _naive(allotted)
        end = _naive(released) or now
        if start is None or start < start_day:
            start = start_day
        if end <= start:
            continue
        cursor = start
        while cursor < end:
            day_key = cursor.strftime("%Y-%m-%d")
            day_end = datetime(cursor.year, cursor.month, cursor.day) + timedelta(days=1)
            overlap = (min(end, day_end) - cursor).total_seconds() / 60.0
            buckets[day_key] = buckets.get(day_key, 0.0) + max(0.0, overlap)
            cursor = day_end

    out = []
    day = start_day
    while day <= now:
        key = day.strftime("%Y-%m-%d")
        occupied = buckets.get(key, 0.0)
        out.append(
            {
                "date": key,
                "occupied_bay_minutes": round(occupied, 1),
                "utilization_pct": round(occupied * 100.0 / (capacity * 1440.0), 1),
            }
        )
        day = day + timedelta(days=1)
    return out


def devices_payload(db: Session) -> List[Dict[str, Any]]:
    from app.services.rules_service import get_rule

    timeout = int(get_rule(db, "heartbeat_timeout_seconds", 120))
    now = _naive(utcnow())
    out = []
    for dev in db.query(Device).order_by(Device.name.asc()).all():
        last = _naive(dev.last_heartbeat)
        age = int((now - last).total_seconds()) if last else None
        out.append(
            {
                "id": dev.id,
                "name": dev.name,
                "kind": dev.kind.value if dev.kind else None,
                "status": dev.status.value,
                "last_heartbeat": last.isoformat() if last else None,
                "heartbeat_age_seconds": age,
                "timeout_seconds": timeout,
                "reachable": dev.status == DeviceStatus.online and (age is None or age <= timeout),
            }
        )
    return out


def tier_summary(db: Session) -> Dict[str, Any]:
    """How many allotments each tier got today (computed, not modelled)."""
    today = _naive(utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(User.priority_tier, func.count(Allotment.id))
        .join(Vehicle, Allotment.vehicle_id == Vehicle.id)
        .join(User, Vehicle.user_id == User.id)
        .filter(Allotment.allotted_at >= today)
        .group_by(User.priority_tier)
        .all()
    )
    return {f"tier_{tier}": count for tier, count in rows}


def audit_trail(db: Session, limit: int = 50) -> List[Dict[str, Any]]:
    logs = db.query(AuditLog).order_by(AuditLog.ts.desc()).limit(limit).all()
    return [
        {
            "id": log.id,
            "actor": log.actor,
            "action": log.action,
            "details": log.details,
            "ts": _naive(log.ts).isoformat() if log.ts else None,
        }
        for log in logs
    ]


def dashboard(db: Session) -> Dict[str, Any]:
    waiting = (
        db.query(Waitlist).filter(Waitlist.status == WaitlistStatus.waiting).count()
    )
    conflicts = get_active_conflicts(db, limit=25)
    lots = lot_service.all_lot_summaries(db)

    return {
        "generated_at": get_virtual_now(db).isoformat(),
        "lots": lots,
        "queue_length": waiting,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "no_show": no_show_stats(db),
        "utilization_series": utilization_series(db),
        "devices": devices_payload(db),
        "tier_summary_today": tier_summary(db),
        "audit": audit_trail(db),
        "totals": {
            "users": db.query(User).count(),
            "vehicles": db.query(Vehicle).count(),
            "bays": sum(l["capacity"] for l in lots),
            "allotments_all_time": db.query(Allotment).count(),
        },
    }
