"""Lot / bay state serialization shared by the public map, admin dashboard
and the live snapshot."""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import (
    Allotment,
    AllotmentStatus,
    Bay,
    BayState,
    Building,
    Lot,
    User,
    UserRole,
    Vehicle,
)
from app.services import prediction_service
from app.services.reconcile_service import bay_confidence_map
from app.services.rules_service import get_rule
from app.services.clock_service import get_virtual_now


def _mask(plate: Optional[str]) -> Optional[str]:
    if not plate:
        return plate
    if "-" in plate:
        parts = plate.split("-")
        if len(parts) >= 3:
            return "-".join([parts[0]] + ["••"] * (len(parts) - 2) + [parts[-1]])
    if len(plate) <= 6:
        return "•" * len(plate)
    return f"{plate[:2]}{'•' * (len(plate) - 4)}{plate[-2:]}"


def _is_staff(user: Optional[User]) -> bool:
    if user is None:
        return False
    role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    return role in ("admin", "gate_operator")


def bay_counts(bays: List[Bay]) -> Dict[str, int]:
    counts = {s.value: 0 for s in BayState}
    for bay in bays:
        counts[bay.state.value] += 1
    counts["total"] = len(bays)
    counts["free"] = counts.get(BayState.free.value, 0)
    return counts


def lot_summary(db: Session, lot: Lot, with_prediction: bool = True) -> Dict[str, Any]:
    bays = db.query(Bay).filter(Bay.lot_id == lot.id).all()
    counts = bay_counts(bays)
    capacity = lot.capacity or len(bays)
    used = counts["allotted"] + counts["occupied"]
    occupancy_pct = round(used * 100.0 / capacity, 1) if capacity else 0.0

    conf = bay_confidence_map(db)
    low_confidence = sum(1 for b in bays if conf.get(b.id, {}).get("low_confidence"))

    summary: Dict[str, Any] = {
        "id": lot.id,
        "name": lot.name,
        "lat": lot.lat,
        "lng": lot.lng,
        "capacity": capacity,
        "counts": counts,
        "used": used,
        "free": counts["free"],
        "occupancy_pct": occupancy_pct,
        "low_confidence_bays": low_confidence,
        "is_full": counts["free"] == 0,
    }

    if with_prediction:
        now = get_virtual_now(db)
        pred = prediction_service.predict_lot_fill_time(db, lot.id, current_time=now)
        summary["prediction"] = pred
        warn_minutes = int(get_rule(db, "prediction_warning_minutes", 30))
        minutes = pred.get("minutes_until_full")
        summary["warning"] = {
            "active": bool(
                not pred.get("is_full_now")
                and minutes is not None
                and minutes <= warn_minutes
            ),
            "message": pred.get("warning_message"),
            "threshold_minutes": warn_minutes,
        }
    return summary


def all_lot_summaries(db: Session, with_prediction: bool = True) -> List[Dict[str, Any]]:
    lots = db.query(Lot).order_by(Lot.name.asc()).all()
    return [lot_summary(db, lot, with_prediction) for lot in lots]


def bays_payload(db: Session, lot_id: str, viewer: Optional[User] = None) -> Dict[str, Any]:
    lot = db.query(Lot).filter(Lot.id == lot_id).first()
    if lot is None:
        return {}

    bays = (
        db.query(Bay)
        .filter(Bay.lot_id == lot_id)
        .order_by(Bay.y.asc(), Bay.x.asc())
        .all()
    )
    conf = bay_confidence_map(db)
    staff = _is_staff(viewer)

    buildings = {b.id: b.name for b in db.query(Building).all()}

    active: Dict[str, Any] = {}
    if bays:
        open_allotments = (
            db.query(Allotment)
            .filter(
                Allotment.bay_id.in_([b.id for b in bays]),
                Allotment.status.in_([AllotmentStatus.allotted, AllotmentStatus.occupied]),
            )
            .all()
        )
    else:
        open_allotments = []
    for a in open_allotments:
        vehicle: Optional[Vehicle] = a.vehicle
        plate = vehicle.plate_or_tag_id if vehicle else None
        active[a.bay_id] = {
            "status": a.status.value,
            "tier": vehicle.user.priority_tier if vehicle and vehicle.user else None,
            "plate": plate if staff else _mask(plate),
        }

    payload = []
    for bay in bays:
        c = conf.get(bay.id, {})
        item = {
            "id": bay.id,
            "label": bay.label,
            "type": bay.type.value,
            "is_accessible": bay.is_accessible,
            "reserved_tier": bay.reserved_tier,
            "x": bay.x,
            "y": bay.y,
            "state": bay.state.value,
            "nearest_building_id": bay.nearest_building_id,
            "nearest_building": buildings.get(bay.nearest_building_id),
            "confidence": c.get("confidence", 1.0),
            "state_source": c.get("state_source", "initial"),
            "low_confidence": c.get("low_confidence", False),
            "last_sensor_ts": c.get("last_sensor_ts"),
            "allotment": active.get(bay.id),
        }
        payload.append(item)

    return {
        "lot": {
            "id": lot.id,
            "name": lot.name,
            "capacity": lot.capacity,
            "lat": lot.lat,
            "lng": lot.lng,
        },
        "bays": payload,
    }
