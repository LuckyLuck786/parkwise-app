"""Gate scan endpoint (simulation + real gate operator).

The kiosk and any staff member post here; the handler feeds the *same*
ingestion pipeline used by /api/v1/ingest/gate-scan (the path hardware uses),
so a simulated scan and a hardware scan are indistinguishable downstream.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_staff
from app.db.database import get_db
from app.db.models import Building, EventSource, Lot, User, UserRole, Vehicle, VehicleType
from app.services import ingest_service, live_service
from app.services.clock_service import get_virtual_now

router = APIRouter(prefix="/api/v1/gate", tags=["Gate"])


class GateScanRequest(BaseModel):
    plate_or_tag_id: str = Field(min_length=3, max_length=64)
    direction: str = Field(default="in_scan", pattern="^(in_scan|out_scan)$")
    destination_building_id: Optional[str] = None
    lot_preference_id: Optional[str] = None
    source: str = Field(default="simulator", pattern="^(simulator|ir_sensor|webcam|manual)$")
    vehicle_id: Optional[str] = None  # kiosk convenience: pick from the driver's vehicles


def _resolve_tag(db: Session, payload: GateScanRequest) -> str:
    if payload.vehicle_id:
        vehicle = db.query(Vehicle).filter(Vehicle.id == payload.vehicle_id).first()
        if vehicle is None:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        return vehicle.plate_or_tag_id
    return payload.plate_or_tag_id.strip().upper()


@router.post("/scan")
def gate_scan(
    payload: GateScanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Allot a bay for an arriving vehicle (or release it on exit).

    Allowed for staff (admin / gate operator) and for a driver scanning their
    own vehicle in the simulation kiosk.
    """
    role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    tag = _resolve_tag(db, payload)

    if role == "driver":
        vehicle = db.query(Vehicle).filter(Vehicle.plate_or_tag_id == tag).first()
        if vehicle is None or vehicle.user_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="Drivers may only scan their own vehicles",
            )

    if payload.destination_building_id:
        if db.query(Building).filter(Building.id == payload.destination_building_id).first() is None:
            raise HTTPException(status_code=404, detail="Building not found")
    if payload.lot_preference_id:
        if db.query(Lot).filter(Lot.id == payload.lot_preference_id).first() is None:
            raise HTTPException(status_code=404, detail="Lot not found")

    result = ingest_service.process_gate_scan(
        db,
        device=None,
        payload={
            "vehicle_tag_id": tag,
            "direction": payload.direction,
            "source": EventSource(payload.source),
            "destination_building_id": payload.destination_building_id,
            "lot_preference_id": payload.lot_preference_id,
            "ts": get_virtual_now(db),
        },
        actor=f"{role}:{user.email}",
    )
    live_service.bump(db, "allocation", {"tag": tag, "direction": payload.direction})
    return {
        "success": result.get("success"),
        "message": result.get("message"),
        "allocation": result.get("allocation"),
    }
