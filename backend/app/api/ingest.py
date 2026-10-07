"""Ingestion endpoints.

All hardware and simulated devices POST the same normalized events here,
authenticated by a per-device API key (X-API-Key). The handlers are thin:
the actual pipeline lives in services/ingest_service.py so the simulator,
the admin demo controls and the gate kiosk share one code path.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Device, EventSource, ScanDirection, utcnow
from app.schemas.ingest import (
    BayEventIngestRequest,
    GateScanIngestRequest,
    HeartbeatIngestRequest,
    IngestResponse,
)
from app.services import ingest_service, input_source
from app.services.device_auth import authenticate_device
from app.services.reconcile_service import get_active_conflicts

router = APIRouter(prefix="/api/v1/ingest", tags=["Ingest"])


def _assert_source_allowed(db: Session, source: Any) -> None:
    """Demo-day failure plan: one admin toggle can pause hardware input."""
    if not input_source.source_allowed(db, source):
        name = getattr(source, "value", source)
        raise HTTPException(
            status_code=409,
            detail=(
                f"Hardware input is paused (input source = simulated_only). "
                f"Source {name!r} rejected; simulator and manual events are "
                "still accepted. An admin can re-enable hardware in the "
                "Simulator panel."
            ),
        )


@router.post("/bay-event", response_model=IngestResponse)
def ingest_bay_event(
    payload: BayEventIngestRequest,
    device: Device = Depends(authenticate_device),
    db: Session = Depends(get_db),
):
    """Normalized bay_occupancy {bay_id, occupied, source, confidence, ts}."""
    _assert_source_allowed(db, payload.source)
    try:
        result = ingest_service.process_bay_event(db, device, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    conflict = result["conflict"]
    return IngestResponse(
        success=True,
        message="Bay occupancy event recorded successfully.",
        event_id=result["event_id"],
        conflict_detected=conflict is not None,
        conflict_details=conflict,
    )


@router.post("/gate-scan", response_model=IngestResponse)
def ingest_gate_scan(
    payload: GateScanIngestRequest,
    device: Device = Depends(authenticate_device),
    db: Session = Depends(get_db),
):
    """Normalized gate_scan {vehicle_tag_id, direction, source, ts}."""
    _assert_source_allowed(db, payload.source)
    try:
        result = ingest_service.process_gate_scan(
            db, device, payload.model_dump(), actor=f"device:{device.name}"
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return IngestResponse(
        success=bool(result.get("success")),
        message=result.get("message", ""),
        event_id=result.get("event_id"),
        allocation_result=result.get("allocation"),
    )


@router.post("/heartbeat")
def ingest_heartbeat(
    payload: HeartbeatIngestRequest,
    device: Device = Depends(authenticate_device),
    db: Session = Depends(get_db),
):
    data = ingest_service.process_heartbeat(db, device, payload.model_dump())
    return {"success": True, **data}


@router.get("/conflicts")
def list_conflicts(db: Session = Depends(get_db)):
    """Conflicts are readable here so an edge agent can poll them; the admin
    dashboard uses /api/v1/admin/conflicts (same data, admin auth)."""
    return get_active_conflicts(db)
