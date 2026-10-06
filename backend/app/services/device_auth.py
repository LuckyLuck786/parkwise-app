from typing import Optional
from fastapi import Header, HTTPException, Security, Depends, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import Device, DeviceStatus, utcnow
from app.core.security import verify_password

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def authenticate_device(
    x_api_key: Optional[str] = Security(api_key_header),
    db: Session = Depends(get_db)
) -> Device:
    """
    Verifies device authenticity using the hashed API key.
    Updates the device's last_heartbeat timestamp and online status.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header"
        )
        
    devices = db.query(Device).all()
    for dev in devices:
        if verify_password(x_api_key, dev.api_key_hash):
            dev.last_heartbeat = utcnow()
            dev.status = DeviceStatus.online
            db.commit()
            return dev
            
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid Device API Key"
    )
