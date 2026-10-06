from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from app.db.models import EventSource, ScanDirection, DeviceStatus

class BayEventIngestRequest(BaseModel):
    bay_id: str
    occupied: bool
    source: EventSource = EventSource.simulator
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    ts: Optional[datetime] = None

class GateScanIngestRequest(BaseModel):
    vehicle_tag_id: str
    direction: ScanDirection = ScanDirection.in_scan
    source: EventSource = EventSource.simulator
    destination_building_id: Optional[str] = None
    lot_preference_id: Optional[str] = None
    ts: Optional[datetime] = None

class HeartbeatIngestRequest(BaseModel):
    device_id: str
    status: DeviceStatus = DeviceStatus.online
    ts: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

class IngestResponse(BaseModel):
    success: bool
    message: str
    event_id: Optional[str] = None
    conflict_detected: bool = False
    conflict_details: Optional[Dict[str, Any]] = None
    allocation_result: Optional[Dict[str, Any]] = None
