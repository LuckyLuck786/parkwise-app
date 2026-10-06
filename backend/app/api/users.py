"""Driver-facing account endpoints: vehicles CRUD, destination, tier edits.

Privacy: plates are masked for anyone who is not admin/gate staff, and a
driver only ever sees their own vehicles unmasked.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_admin
from app.db.database import get_db
from app.db.models import Allotment, AllotmentStatus, Building, User, UserRole, Vehicle, VehicleType
from app.schemas.auth import TierUpdate, UserOut, VehicleCreate, VehicleOut, VehicleUpdate
from app.services import live_service

router = APIRouter(prefix="/api/v1", tags=["Account"])

MAX_VEHICLES_PER_USER = 3


def mask_plate(plate: str) -> str:
    """KA-01-AB-1234 -> KA-••-••-1234 (keeps the shape, hides the identity)."""
    if not plate:
        return plate
    if "-" in plate:
        parts = plate.split("-")
        if len(parts) >= 3:
            return "-".join([parts[0]] + ["••"] * (len(parts) - 2) + [parts[-1]])
    if len(plate) <= 6:
        return "•" * len(plate)
    return f"{plate[:2]}{'•' * (len(plate) - 4)}{plate[-2:]}"


def can_see_full_plates(user: User) -> bool:
    role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    return role in ("admin", "gate_operator")


def serialize_vehicle(vehicle: Vehicle, viewer: User) -> dict:
    out = VehicleOut.model_validate(vehicle).model_dump()
    if vehicle.user_id != viewer.id and not can_see_full_plates(viewer):
        out["plate_or_tag_id"] = mask_plate(out["plate_or_tag_id"])
        out["masked"] = True
    return out


def _own_vehicle(db: Session, user: User, vehicle_id: str) -> Vehicle:
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if vehicle is None or vehicle.user_id != user.id:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


@router.get("/vehicles", response_model=List[dict])
def list_vehicles(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    all: bool = False,
):
    """Own vehicles (default). `?all=true` is admin-only (full roster)."""
    query = db.query(Vehicle)
    if not all:
        query = query.filter(Vehicle.user_id == user.id)
    elif not (isinstance(user.role, UserRole) and user.role == UserRole.admin):
        raise HTTPException(status_code=403, detail="Requires role: admin")
    vehicles = query.order_by(Vehicle.created_at.asc()).all()
    return [serialize_vehicle(v, user) for v in vehicles]


@router.post("/vehicles", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    payload: VehicleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plate = payload.plate_or_tag_id
    if db.query(Vehicle).filter(Vehicle.plate_or_tag_id == plate).first():
        raise HTTPException(status_code=409, detail="That plate/tag is already registered")
    mine = db.query(Vehicle).filter(Vehicle.user_id == user.id).count()
    if mine >= MAX_VEHICLES_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=f"Maximum {MAX_VEHICLES_PER_USER} vehicles per account",
        )
    vehicle = Vehicle(user_id=user.id, plate_or_tag_id=plate, type=payload.type)
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    live_service.bump(db, "vehicle")
    return serialize_vehicle(vehicle, user)


@router.patch("/vehicles/{vehicle_id}", response_model=dict)
def update_vehicle(
    vehicle_id: str,
    payload: VehicleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    vehicle = _own_vehicle(db, user, vehicle_id)
    if payload.plate_or_tag_id is not None:
        plate = payload.plate_or_tag_id.strip().upper()
        clash = db.query(Vehicle).filter(Vehicle.plate_or_tag_id == plate, Vehicle.id != vehicle.id).first()
        if clash:
            raise HTTPException(status_code=409, detail="That plate/tag is already registered")
        vehicle.plate_or_tag_id = plate
    if payload.type is not None:
        vehicle.type = payload.type
    if payload.active_today is not None:
        if payload.active_today:
            for other in db.query(Vehicle).filter(Vehicle.user_id == user.id, Vehicle.id != vehicle.id):
                other.active_today = False
        vehicle.active_today = payload.active_today
    db.commit()
    db.refresh(vehicle)
    return serialize_vehicle(vehicle, user)


@router.delete("/vehicles/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle(
    vehicle_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    vehicle = _own_vehicle(db, user, vehicle_id)
    holding = (
        db.query(Allotment)
        .filter(
            Allotment.vehicle_id == vehicle.id,
            Allotment.status.in_([AllotmentStatus.allotted, AllotmentStatus.occupied]),
        )
        .first()
    )
    if holding:
        raise HTTPException(
            status_code=409,
            detail="This vehicle currently holds a bay; it cannot be removed until it leaves",
        )
    db.delete(vehicle)
    db.commit()
    live_service.bump(db, "vehicle")


@router.post("/vehicles/{vehicle_id}/activate", response_model=dict)
def activate_vehicle(
    vehicle_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Select today's vehicle (exactly one can be active per account)."""
    vehicle = _own_vehicle(db, user, vehicle_id)
    for other in db.query(Vehicle).filter(Vehicle.user_id == user.id):
        other.active_today = other.id == vehicle.id
    db.commit()
    db.refresh(vehicle)
    return serialize_vehicle(vehicle, user)


@router.put("/me/destination", response_model=dict)
def set_destination(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    building_id = payload.get("building_id")
    if building_id is not None:
        building = db.query(Building).filter(Building.id == building_id).first()
        if building is None:
            raise HTTPException(status_code=404, detail="Building not found")
    user.destination_building_id = building_id
    db.commit()
    return {"destination_building_id": building_id}


@router.get("/users/{user_id}", response_model=dict)
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    out = UserOut.model_validate(target).model_dump()
    out["vehicles"] = [serialize_vehicle(v, user) for v in target.vehicles]
    return out


@router.patch("/users/{user_id}", response_model=dict)
def update_user(
    user_id: str,
    payload: TierUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Admin grant of priority tier / accessibility need (audit-logged by caller
    via the admin router's audit entries when needed)."""
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.priority_tier is not None:
        target.priority_tier = payload.priority_tier
    if payload.needs_accessible is not None:
        target.needs_accessible = payload.needs_accessible
    db.commit()
    db.refresh(target)
    return UserOut.model_validate(target).model_dump()
