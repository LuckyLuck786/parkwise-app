from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime
from app.db.models import EventSource, ScanDirection

class SensorAdapter(ABC):
    """
    Abstract interface for all hardware and simulator sensor adapters.
    Ensures every source (IR sensor, OpenCV webcam, Simulator, Manual)
    normalizes data into the exact same payload structure before ingestion.
    """
    
    @abstractmethod
    def normalize_bay_event(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Returns normalized bay occupancy dict:
        {
            "bay_id": str,
            "occupied": bool,
            "source": EventSource,
            "confidence": float (0.0 to 1.0),
            "ts": datetime
        }
        """
        pass
        
    @abstractmethod
    def normalize_gate_scan(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Returns normalized gate scan dict:
        {
            "vehicle_tag_id": str,
            "direction": ScanDirection,
            "source": EventSource,
            "ts": datetime,
            "destination_building_id": Optional[str],
            "lot_preference_id": Optional[str]
        }
        """
        pass
