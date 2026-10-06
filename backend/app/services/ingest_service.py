"""Shared ingestion pipeline.

Every source — simulator, IR sensor, webcam edge agent, manual admin entry —
produces the same normalized event and passes through these functions. The
HTTP endpoints in api/ingest.py, the admin demo controls and the gate-scan
simulation all call this module: there is no special-case code path for the
simulator.

Normalization itself happens in app/adapters/* (SensorAdapter implementations);
by the time a payload reaches this module it is already normalized.
"""
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import (
    Allotment,
    AllotmentStatus,
    AuditLog,
    Bay,
    BayEvent,
    BayState,
    Device,
    EventSource,
    ScanDirection,
    ScanEvent,
    Vehicle,
    as_utc_naive,
    utcnow,
)
from app.schemas.allocation import AllocationDecision
from app.services.allocation_service import allocate_bay
from app.services.reconcile_service import reconcile_bay_event
from app.services.waitlist_service import promote_waitlist_head


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    return as_utc_naive(dt)


def process_bay_event(
    db: Session,
    device: Optional[Device],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Record one normalized bay_occupancy event and reconcile it."""
    ts = _naive(payload.get("ts")) or _naive(utcnow())
    bay_id = payload["bay_id"]

    bay = db.query(Bay).filter(Bay.id == bay_id).first()
    if bay is None:
        raise KeyError(f"Unknown bay_id {bay_id}")

    row = BayEvent(
        bay_id=bay_id,
        occupied=bool(payload["occupied"]),
        source=payload.get("source", EventSource.simulator),
        confidence=float(payload.get("confidence", 1.0)),
        ts=ts,
    )
    db.add(row)
    db.commit()

    conflict = reconcile_bay_event(
        db=db,
        bay_id=bay_id,
        sensor_occupied=bool(payload["occupied"]),
        sensor_confidence=float(payload.get("confidence", 1.0)),
        current_time=ts,
    )
    return {
        "event_id": row.id,
        "conflict": conflict,
    }


def process_gate_scan(
    db: Session,
    device: Optional[Device],
    payload: Dict[str, Any],
    actor: str = "gate",
) -> Dict[str, Any]:
    """Record one normalized gate_scan event; allocate on entry, release on exit."""
    ts = _naive(payload.get("ts")) or _naive(utcnow())
    tag = str(payload["vehicle_tag_id"])
    direction = payload.get("direction", ScanDirection.in_scan)
    if isinstance(direction, str):
        direction = ScanDirection(direction)

    vehicle = db.query(Vehicle).filter(Vehicle.plate_or_tag_id == tag).first()
    if vehicle is None:
        raise KeyError(f"Vehicle tag {tag} not registered")

    scan_event = ScanEvent(
        vehicle_id=vehicle.id,
        direction=direction,
        source=payload.get("source", EventSource.simulator),
        ts=ts,
    )
    db.add(scan_event)
    db.commit()

    result: Dict[str, Any] = {"event_id": scan_event.id}

    if direction == ScanDirection.in_scan:
        decision: AllocationDecision = allocate_bay(
            db=db,
            plate_or_tag_id=tag,
            destination_building_id=payload.get("destination_building_id"),
            lot_preference_id=payload.get("lot_preference_id"),
            current_time=ts,
            actor=actor,
        )
        result.update(
            {
                "success": decision.success,
                "message": decision.message,
                "allocation": decision.model_dump(),
            }
        )
        return result

    # ---------------------------------------------------------- exit scan ----
    active = (
        db.query(Allotment)
        .filter(
            Allotment.vehicle_id == vehicle.id,
            Allotment.status.in_([AllotmentStatus.allotted, AllotmentStatus.occupied]),
        )
        .first()
    )
    if active is None:
        result.update(
            {
                "success": True,
                "message": f"Vehicle {tag} scanned out (no open allotment).",
                "allocation": None,
            }
        )
        return result

    bay = active.bay
    active.status = AllotmentStatus.completed
    active.released_at = ts
    bay.state = BayState.free
    db.add(
        AuditLog(
            actor=actor,
            action="gate_scan_out",
            details={
                "vehicle_id": vehicle.id,
                "allotment_id": active.id,
                "bay_id": bay.id,
                "bay": bay.label,
            },
            ts=ts,
        )
    )
    db.commit()

    promoted = promote_waitlist_head(db, bay.id, ts)
    result.update(
        {
            "success": True,
            "message": (
                f"Vehicle {tag} checked out. Bay {bay.label} freed"
                + (" and offered to the waitlist." if promoted else ".")
            ),
            "allocation": None,
            "waitlist_promoted": promoted is not None,
        }
    )
    return result


def process_heartbeat(
    db: Session,
    device: Device,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    ts = _naive(payload.get("ts")) or _naive(utcnow())
    device.last_heartbeat = ts
    if payload.get("status"):
        device.status = payload["status"]
    if payload.get("metadata"):
        device.config = payload["metadata"]
    db.commit()
    return {
        "device_id": device.id,
        "status": device.status.value,
        "last_heartbeat": ts.isoformat(),
    }
