from typing import Dict, Any, Optional
from datetime import datetime
from app.adapters.base import SensorAdapter
from app.db.models import EventSource, ScanDirection, utcnow

class SimulatorAdapter(SensorAdapter):
    """
    Sensor adapter for the simulation engine. Produces normalized events
    identical to hardware devices.
    """
    
    def normalize_bay_event(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        ts = raw_data.get("ts")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif not isinstance(ts, datetime):
            ts = utcnow()
            
        confidence = float(raw_data.get("confidence", 1.0))
        confidence = max(0.0, min(1.0, confidence))
        
        return {
            "bay_id": str(raw_data["bay_id"]),
            "occupied": bool(raw_data["occupied"]),
            "source": EventSource.simulator,
            "confidence": confidence,
            "ts": ts
        }

    def normalize_gate_scan(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        ts = raw_data.get("ts")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif not isinstance(ts, datetime):
            ts = utcnow()
            
        direction_raw = raw_data.get("direction", "in_scan")
        if direction_raw in ["in", "in_scan", ScanDirection.in_scan]:
            direction = ScanDirection.in_scan
        else:
            direction = ScanDirection.out_scan
            
        return {
            "vehicle_tag_id": str(raw_data["vehicle_tag_id"]),
            "direction": direction,
            "source": EventSource.simulator,
            "ts": ts,
            "destination_building_id": raw_data.get("destination_building_id"),
            "lot_preference_id": raw_data.get("lot_preference_id")
        }
