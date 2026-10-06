"""Demo controls: virtual clock, morning-rush scenario, fault injection and
reset. Everything here goes through the normal ingestion pipeline — there is
no demo-only write path that bypasses reconciliation."""
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import (
    Allotment,
    AllotmentStatus,
    AuditLog,
    Bay,
    BayState,
    Building,
    Device,
    DeviceStatus,
    EventSource,
    Lot,
    User,
    Vehicle,
    Waitlist,
    as_utc_naive,
    utcnow,
)
from app.services import ingest_service, live_service, notification_service
from app.services.clock_service import get_virtual_now, reset_clock, set_clock
from app.services.noshow_service import check_and_release_noshows
from app.services.rules_service import get_rule


def demo_state(db: Session) -> Dict[str, Any]:
    active = (
        db.query(Allotment)
        .filter(Allotment.status.in_([AllotmentStatus.allotted, AllotmentStatus.occupied]))
        .count()
    )
    waiting = (
        db.query(Waitlist).filter(Waitlist.status == "waiting").count()
    )
    row_free = db.query(Bay).filter(Bay.state == BayState.free).count()
    return {
        "clock": {
            "virtual_now": get_virtual_now(db).isoformat(),
            "real_now": as_utc_naive(utcnow()).isoformat(),
        },
        "counts": {
            "free_bays": row_free,
            "active_allotments": active,
            "waitlist": waiting,
            "notifications": db.query(notification_service.Notification).count(),
        },
        "version": live_service.get_version(db),
    }


def set_demo_clock(
    db: Session,
    speed: Optional[float] = None,
    set_time: Optional[datetime] = None,
    jump_minutes: Optional[float] = None,
    reset: bool = False,
) -> Dict[str, Any]:
    if reset:
        out = reset_clock(db)
    else:
        out = set_clock(db, speed=speed, set_time=set_time, jump_minutes=jump_minutes)
    db.add(
        AuditLog(
            actor="admin",
            action="demo_clock_changed",
            details=out,
            ts=as_utc_naive(utcnow()),
        )
    )
    db.commit()
    live_service.bump(db, "clock")
    return out


def run_rush(
    db: Session,
    count: int = 20,
    dest_building_id: Optional[str] = None,
    lot_id: Optional[str] = None,
    start_minute_offset: float = 0.0,
    gap_seconds: float = 30.0,
    occupy: bool = True,
) -> Dict[str, Any]:
    """Morning rush: `count` vehicles through the normal scan pipeline.

    Timestamps are spaced along the virtual demo clock, so speeding the clock
    up makes the rush play out faster end-to-end.
    """
    vehicles = (
        db.query(Vehicle)
        .join(User, Vehicle.user_id == User.id)
        .filter(User.role == "driver")
        .all()
    )
    if not vehicles:
        return {"success": False, "message": "No driver vehicles seeded", "results": []}

    rng = random.Random(7)
    roster = list(vehicles)
    rng.shuffle(roster)
    roster = roster[: max(1, count)]

    base = get_virtual_now(db) + timedelta(minutes=start_minute_offset)
    buildings = db.query(Building).all()
    dest_id = dest_building_id or (buildings[0].id if buildings else None)

    results: List[Dict[str, Any]] = []
    for i, vehicle in enumerate(roster):
        ts = base + timedelta(seconds=gap_seconds * i)
        result = ingest_service.process_gate_scan(
            db,
            device=None,
            payload={
                "vehicle_tag_id": vehicle.plate_or_tag_id,
                "direction": "in_scan",
                "source": EventSource.simulator,
                "destination_building_id": dest_id,
                "lot_preference_id": lot_id,
                "ts": ts,
            },
            actor="demo:morning_rush",
        )
        entry: Dict[str, Any] = {
            "tag": vehicle.plate_or_tag_id,
            "success": result.get("success"),
            "message": result.get("message"),
            "allocation": result.get("allocation"),
        }
        alloc = result.get("allocation") or {}
        bay = alloc.get("bay") if isinstance(alloc, dict) else None
        if occupy and bay:
            # The IR/webcam layer observes the arrival a little later.
            ingest_service.process_bay_event(
                db,
                device=None,
                payload={
                    "bay_id": bay["id"],
                    "occupied": True,
                    "source": EventSource.simulator,
                    "confidence": 0.98,
                    "ts": ts + timedelta(seconds=gap_seconds * 0.6),
                },
            )
        results.append(entry)

    live_service.bump(db, "allocation", {"scenario": "morning_rush"})
    allotted = sum(1 for r in results if r["success"])
    waitlisted = sum(
        1 for r in results
        if (r.get("allocation") or {}).get("status") == "waitlisted"
    )
    return {
        "success": True,
        "count": len(results),
        "allotted": allotted,
        "waitlisted": waitlisted,
        "window_start": base.isoformat(),
        "gap_seconds": gap_seconds,
        "results": results,
    }


def release_nows(db: Session) -> Dict[str, Any]:
    """Run the no-show sweep at the virtual demo clock."""
    now = get_virtual_now(db)
    released = check_and_release_noshows(db, current_time=now)
    live_service.bump(db, "waitlist")
    return {
        "released": len(released),
        "at": now.isoformat(),
        "allotment_ids": [a.id for a in released],
    }


def inject_fault(
    db: Session,
    fault: str,
    bay_id: Optional[str] = None,
    device_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Demo faults. Sensor faults and bay faults change state the same way a
    real operator or the reconcile layer would — no fake history."""
    now = get_virtual_now(db)
    details: Dict[str, Any] = {"fault": fault, "bay_id": bay_id, "device_id": device_id}

    if fault == "sensor_offline":
        device = db.query(Device).filter(Device.id == device_id).first() if device_id else db.query(Device).first()
        if device is None:
            return {"success": False, "message": "No device to take offline"}
        device.status = DeviceStatus.offline
        device.last_heartbeat = as_utc_naive(utcnow()) - timedelta(hours=1)
        details.update({"device": device.name, "status": "offline"})
        action = "fault_sensor_offline"

    elif fault == "sensor_online":
        device = db.query(Device).filter(Device.id == device_id).first() if device_id else db.query(Device).first()
        if device is None:
            return {"success": False, "message": "No device found"}
        device.status = DeviceStatus.online
        device.last_heartbeat = as_utc_naive(utcnow())
        details.update({"device": device.name, "status": "online"})
        action = "fault_sensor_online"

    elif fault == "bay_blocked":
        bay = db.query(Bay).filter(Bay.id == bay_id).first() if bay_id else db.query(Bay).filter(Bay.state == BayState.free).first()
        if bay is None:
            return {"success": False, "message": "No bay found to block"}
        bay.state = BayState.blocked
        details.update({"bay": bay.label, "state": "blocked"})
        action = "fault_bay_blocked"

    elif fault == "bay_unblock":
        bay = db.query(Bay).filter(Bay.id == bay_id).first() if bay_id else db.query(Bay).filter(Bay.state == BayState.blocked).first()
        if bay is None:
            return {"success": False, "message": "No blocked bay found"}
        bay.state = BayState.free
        details.update({"bay": bay.label, "state": "free"})
        action = "fault_bay_unblocked"

    elif fault in ("wrong_bay", "unauthorized"):
        # Feed a real observation through the ingestion pipeline so the
        # reconcile layer decides what it is (and raises the conflict).
        target = None
        if bay_id:
            target = db.query(Bay).filter(Bay.id == bay_id).first()
        if target is None:
            target = db.query(Bay).filter(Bay.state == BayState.free).first()
        if target is None:
            return {"success": False, "message": "No free bay available for the fault"}
        if fault == "wrong_bay":
            has_pending = (
                db.query(Allotment)
                .join(Bay, Allotment.bay_id == Bay.id)
                .filter(Bay.lot_id == target.lot_id, Allotment.status == AllotmentStatus.allotted)
                .first()
            )
            if has_pending is None:
                return {
                    "success": False,
                    "message": "No scanned-in-but-not-arrived vehicle in a lot — run a rush first",
                }
        result = ingest_service.process_bay_event(
            db,
            device=None,
            payload={
                "bay_id": target.id,
                "occupied": True,
                "source": EventSource.manual,
                "confidence": 0.7,
                "ts": now,
            },
        )
        details.update({"bay": target.label, "conflict": result["conflict"]})
        action = "fault_injected"

    else:
        return {"success": False, "message": f"Unknown fault {fault!r}"}

    db.add(AuditLog(actor="admin", action=action, details=details, ts=as_utc_naive(utcnow())))
    db.commit()
    live_service.bump(db, "conflict" if fault in ("wrong_bay", "unauthorized") else "device")
    return {"success": True, "action": action, "details": details}


def reset_demo(db: Session) -> Dict[str, Any]:
    """Return the live state to a clean slate without touching users, rules or
    the 14 days of history the predictor needs."""
    now = as_utc_naive(utcnow())
    cancelled = 0
    for allotment in (
        db.query(Allotment)
        .filter(Allotment.status.in_([AllotmentStatus.allotted, AllotmentStatus.occupied]))
        .all()
    ):
        allotment.status = AllotmentStatus.cancelled
        allotment.released_at = now
        cancelled += 1

    db.query(Bay).update({"state": BayState.free})
    db.query(Waitlist).delete()
    db.query(notification_service.Notification).delete()
    from app.db.models import BayEvent, ScanEvent

    bay_events = db.query(BayEvent).delete()
    db.query(ScanEvent).filter(ScanEvent.ts >= now - timedelta(days=1)).delete()

    db.add(
        AuditLog(
            actor="admin",
            action="demo_reset",
            details={
                "cancelled_allotments": cancelled,
                "bay_events_deleted": bay_events,
                "kept": "users, vehicles, rules, history (predictor input)",
            },
            ts=now,
        )
    )
    db.commit()
    reset_clock(db)
    live_service.bump(db, "bay")
    return {"success": True, "cancelled_allotments": cancelled}
