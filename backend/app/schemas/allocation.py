from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class ScanRequest(BaseModel):
    plate_or_tag_id: str
    destination_building_id: Optional[str] = None
    lot_preference_id: Optional[str] = None
    source: str = "simulator"

class AllocationDecision(BaseModel):
    success: bool
    status: str
    bay: Optional[Dict[str, Any]] = None
    lot: Optional[Dict[str, Any]] = None
    alternative_lot: Optional[Dict[str, Any]] = None
    waitlist_position: Optional[int] = None
    message: str
    explanation: Dict[str, Any]
    allotment_id: Optional[str] = None
