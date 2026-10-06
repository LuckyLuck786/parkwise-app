"""Metrics endpoints: read the latest BASELINE vs ParkWise comparison, or
launch a new run (admin only)."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.db.database import get_db
from app.services.simulation_service import latest_run

router = APIRouter(prefix="/api/v1/metrics", tags=["Metrics"])


@router.get("")
def get_metrics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Latest stored comparison run (computed from data, never hardcoded)."""
    run = latest_run(db)
    if run is None:
        return {
            "run": None,
            "message": "No simulation run yet — launch one from Admin → Metrics.",
        }
    return {"run": run}
