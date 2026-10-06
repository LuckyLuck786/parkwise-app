"""Admin endpoints: rules, bay editor, audit, conflicts, devices, analytics,
demo controls and metric runs. Everything is role-protected and audit-logged."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import require_admin, require_staff
from app.db.database import get_db
from app.db.models import (
    AuditLog,
    Bay,
    BayState,
    Building,
    Device,
    Lot,
    User,
    UserRole,
    Vehicle,
    VehicleType,
    as_utc_naive,
    utcnow,
)
from app.schemas.auth import UserOut
from app.services import analytics_service, demo_service, live_service, lot_service
from app.services.reconcile_service import (
    check_device_heartbeats,
    get_active_conflicts,
    resolve_conflict,
)
from app.services.rules_service import get_rules, set_rules
from app.services.simulation_service import run_comparison

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
@router.get("/rules")
def read_rules(db: Session = Depends(get_db)):
    from app.services.rules_service import DESCRIPTIONS, DEFAULTS

    values = get_rules(db)
    return {
        key: {
            "value": value,
            "description": DESCRIPTIONS.get(key, ""),
            "default": DEFAULTS.get(key),
        }
        for key, value in sorted(values.items())
    }


class RulesUpdate(BaseModel):
    updates: Dict[str, Any] = Field(default_factory=dict)


@router.put("/rules")
def write_rules(payload: RulesUpdate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if not payload.updates:
        raise HTTPException(status_code=400, detail="No updates supplied")
    allowed = set(get_rules(db).keys())
    unknown = [k for k in payload.updates if k not in allowed]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown rules: {unknown}")
    updated = set_rules(db, payload.updates, actor=user.email)
    live_service.bump(db, "rules")
    return {k: updated[k] for k in payload.updates}


# --------------------------------------------------------------------------- #
# Audit, conflicts, devices
# --------------------------------------------------------------------------- #
@router.get("/audit")
def audit_log(limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db)):
    return analytics_service.audit_trail(db, limit=limit)


@router.get("/conflicts")
def conflicts(db: Session = Depends(get_db)):
    return get_active_conflicts(db)


@router.post("/conflicts/{audit_id}/resolve")
def resolve(audit_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if not resolve_conflict(db, audit_id, actor=user.email):
        raise HTTPException(status_code=404, detail="Conflict not found")
    live_service.bump(db, "conflict")
    return {"success": True}


@router.get("/devices")
def devices(db: Session = Depends(get_db)):
    return analytics_service.devices_payload(db)


@router.post("/devices/check-heartbeats")
def heartbeat_sweep(db: Session = Depends(get_db)):
    alerts = check_device_heartbeats(db)
    if alerts:
        live_service.bump(db, "device")
    return {"alerts": alerts, "checked_at": as_utc_naive(utcnow()).isoformat()}


# --------------------------------------------------------------------------- #
# Analytics + roster
# --------------------------------------------------------------------------- #
@router.get("/analytics")
def analytics(db: Session = Depends(get_db)):
    return analytics_service.dashboard(db)


@router.get("/users")
def users_list(db: Session = Depends(get_db)):
    return [
        {
            **UserOut.model_validate(u).model_dump(),
            "vehicle_count": len(u.vehicles),
        }
        for u in db.query(User).order_by(User.priority_tier.asc(), User.name.asc()).all()
    ]


@router.get("/vehicles")
def vehicles_roster(
    vehicle_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Full roster with unmasked plates (admin only; used by the rush
    simulator and the gate kiosk)."""
    query = db.query(Vehicle).join(User, Vehicle.user_id == User.id)
    if vehicle_type:
        query = query.filter(Vehicle.type == VehicleType(vehicle_type))
    out = []
    for v in query.order_by(Vehicle.created_at.asc()).all():
        out.append(
            {
                "id": v.id,
                "plate_or_tag_id": v.plate_or_tag_id,
                "type": v.type.value,
                "active_today": v.active_today,
                "owner": v.user.name if v.user else None,
                "owner_id": v.user_id,
                "tier": v.user.priority_tier if v.user else None,
                "needs_accessible": v.user.needs_accessible if v.user else False,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Bay editor
# --------------------------------------------------------------------------- #
class BayIn(BaseModel):
    lot_id: str
    label: str = Field(min_length=1, max_length=24)
    type: VehicleType
    x: int = Field(ge=0, le=200)
    y: int = Field(ge=0, le=200)
    is_accessible: bool = False
    reserved_tier: Optional[int] = Field(default=None, ge=1, le=3)
    nearest_building_id: Optional[str] = None
    state: Optional[str] = None


class BayPatch(BaseModel):
    label: Optional[str] = None
    type: Optional[VehicleType] = None
    x: Optional[int] = None
    y: Optional[int] = None
    is_accessible: Optional[bool] = None
    reserved_tier: Optional[int] = None
    nearest_building_id: Optional[str] = None
    state: Optional[str] = None
    lot_id: Optional[str] = None


def _serialize_bay(bay: Bay) -> Dict[str, Any]:
    return {
        "id": bay.id,
        "lot_id": bay.lot_id,
        "label": bay.label,
        "type": bay.type.value,
        "x": bay.x,
        "y": bay.y,
        "is_accessible": bay.is_accessible,
        "reserved_tier": bay.reserved_tier,
        "nearest_building_id": bay.nearest_building_id,
        "state": bay.state.value,
    }


def _audit_bay(db: Session, actor: str, action: str, details: Dict[str, Any]) -> None:
    db.add(AuditLog(actor=actor, action=action, details=details, ts=as_utc_naive(utcnow())))


@router.get("/bays")
def bays_editor(db: Session = Depends(get_db)):
    """Layout for the bay editor (all lots)."""
    return [_serialize_bay(b) for b in db.query(Bay).order_by(Bay.lot_id, Bay.y, Bay.x).all()]


@router.post("/bays", status_code=201)
def create_bay(payload: BayIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if db.query(Lot).filter(Lot.id == payload.lot_id).first() is None:
        raise HTTPException(status_code=404, detail="Lot not found")
    if db.query(Bay).filter(Bay.lot_id == payload.lot_id, Bay.label == payload.label).first():
        raise HTTPException(status_code=409, detail="Label already used in this lot")
    if payload.nearest_building_id and db.query(Building).filter(Building.id == payload.nearest_building_id).first() is None:
        raise HTTPException(status_code=404, detail="Building not found")
    bay = Bay(
        lot_id=payload.lot_id,
        label=payload.label,
        type=payload.type,
        x=payload.x,
        y=payload.y,
        is_accessible=payload.is_accessible,
        reserved_tier=payload.reserved_tier,
        nearest_building_id=payload.nearest_building_id,
        state=BayState(payload.state) if payload.state else BayState.free,
    )
    db.add(bay)
    _audit_bay(db, user.email, "bay_created", {"label": bay.label, "lot_id": bay.lot_id})
    db.commit()
    db.refresh(bay)
    live_service.bump(db, "bay")
    return _serialize_bay(bay)


@router.patch("/bays/{bay_id}")
def update_bay(bay_id: str, payload: BayPatch, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    bay = db.query(Bay).filter(Bay.id == bay_id).first()
    if bay is None:
        raise HTTPException(status_code=404, detail="Bay not found")
    before = _serialize_bay(bay)
    data = payload.model_dump(exclude_unset=True)
    if "state" in data and data["state"] is not None:
        try:
            data["state"] = BayState(data["state"])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid state {data['state']!r}")
    for key, value in data.items():
        setattr(bay, key, value)
    _audit_bay(db, user.email, "bay_updated", {"before": before, "after": _serialize_bay(bay)})
    db.commit()
    db.refresh(bay)
    live_service.bump(db, "bay")
    return _serialize_bay(bay)


@router.delete("/bays/{bay_id}", status_code=204)
def delete_bay(bay_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    bay = db.query(Bay).filter(Bay.id == bay_id).first()
    if bay is None:
        raise HTTPException(status_code=404, detail="Bay not found")
    from app.db.models import Allotment, AllotmentStatus

    holding = (
        db.query(Allotment)
        .filter(
            Allotment.bay_id == bay.id,
            Allotment.status.in_([AllotmentStatus.allotted, AllotmentStatus.occupied]),
        )
        .first()
    )
    if holding:
        raise HTTPException(status_code=409, detail="Bay has an open allotment")
    label = bay.label
    lot_id = bay.lot_id
    db.delete(bay)
    _audit_bay(db, user.email, "bay_deleted", {"label": label, "lot_id": lot_id})
    db.commit()
    live_service.bump(db, "bay")


class BayLayoutRequest(BaseModel):
    """Upsert a whole lot layout (mirrors what the Bay Editor shows — used to
    mirror the thermocol model layout later)."""
    bays: List[BayIn] = Field(default_factory=list)


@router.put("/bays/layout/{lot_id}")
def upsert_layout(lot_id: str, payload: BayLayoutRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if db.query(Lot).filter(Lot.id == lot_id).first() is None:
        raise HTTPException(status_code=404, detail="Lot not found")
    created, updated = 0, 0
    for item in payload.bays:
        if item.lot_id != lot_id:
            raise HTTPException(status_code=400, detail="All bays must belong to the target lot")
        existing = db.query(Bay).filter(Bay.lot_id == lot_id, Bay.label == item.label).first()
        if existing:
            existing.type = item.type
            existing.x = item.x
            existing.y = item.y
            existing.is_accessible = item.is_accessible
            existing.reserved_tier = item.reserved_tier
            existing.nearest_building_id = item.nearest_building_id
            updated += 1
        else:
            db.add(
                Bay(
                    lot_id=lot_id, label=item.label, type=item.type, x=item.x, y=item.y,
                    is_accessible=item.is_accessible, reserved_tier=item.reserved_tier,
                    nearest_building_id=item.nearest_building_id,
                )
            )
            created += 1
    _audit_bay(db, user.email, "bay_layout_upserted", {"lot_id": lot_id, "created": created, "updated": updated})
    db.commit()
    live_service.bump(db, "bay")
    return {"created": created, "updated": updated}


# --------------------------------------------------------------------------- #
# Demo controls
# --------------------------------------------------------------------------- #
@router.get("/demo")
def demo_overview(db: Session = Depends(get_db)):
    return demo_service.demo_state(db)


class ClockRequest(BaseModel):
    speed: Optional[float] = Field(default=None, ge=0, le=10000)
    set_time: Optional[datetime] = None
    jump_minutes: Optional[float] = None
    reset: bool = False


@router.post("/demo/clock")
def demo_clock(payload: ClockRequest, db: Session = Depends(get_db)):
    return demo_service.set_demo_clock(
        db,
        speed=payload.speed,
        set_time=payload.set_time,
        jump_minutes=payload.jump_minutes,
        reset=payload.reset,
    )


class RushRequest(BaseModel):
    count: int = Field(default=15, ge=1, le=200)
    dest_building_id: Optional[str] = None
    lot_id: Optional[str] = None
    start_minute_offset: float = 0.0
    gap_seconds: float = Field(default=30.0, ge=0, le=3600)
    occupy: bool = True


@router.post("/demo/rush")
def demo_rush(payload: RushRequest, db: Session = Depends(get_db)):
    return demo_service.run_rush(
        db,
        count=payload.count,
        dest_building_id=payload.dest_building_id,
        lot_id=payload.lot_id,
        start_minute_offset=payload.start_minute_offset,
        gap_seconds=payload.gap_seconds,
        occupy=payload.occupy,
    )


@router.post("/demo/release-noshows")
def demo_release(db: Session = Depends(get_db)):
    return demo_service.release_nows(db)


class FaultRequest(BaseModel):
    fault: str = Field(pattern="^(sensor_offline|sensor_online|bay_blocked|bay_unblock|wrong_bay|unauthorized)$")
    bay_id: Optional[str] = None
    device_id: Optional[str] = None


@router.post("/demo/fault")
def demo_fault(payload: FaultRequest, db: Session = Depends(get_db)):
    out = demo_service.inject_fault(db, payload.fault, payload.bay_id, payload.device_id)
    if not out.get("success"):
        raise HTTPException(status_code=400, detail=out.get("message", "Fault failed"))
    return out


@router.post("/demo/reset")
def demo_reset(db: Session = Depends(get_db)):
    return demo_service.reset_demo(db)


# --------------------------------------------------------------------------- #
# Metrics (BASELINE vs ParkWise)
# --------------------------------------------------------------------------- #
class MetricsRunRequest(BaseModel):
    seed: int = 42
    hours: int = Field(default=5, ge=1, le=24)
    scale: float = Field(default=1.0, ge=0.1, le=5.0)
    name: str = "baseline-vs-parkwise"


@router.post("/metrics/run")
def metrics_run(payload: MetricsRunRequest, db: Session = Depends(get_db)):
    result = run_comparison(
        db, seed=payload.seed, hours=payload.hours, scale=payload.scale,
        name=payload.name,
    )
    live_service.bump(db, "metrics")
    return result
