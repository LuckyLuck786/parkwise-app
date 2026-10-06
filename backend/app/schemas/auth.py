"""Auth / profile / vehicle request+response schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import UserRole, VehicleType


def _enum_val(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    priority_tier: int
    needs_accessible: bool
    destination_building_id: Optional[str] = None

    @field_validator("role", mode="before")
    @classmethod
    def _role(cls, v):
        return _enum_val(v)

    model_config = ConfigDict(from_attributes=True)


# No email-validator dependency: a pragmatic pattern is enough here.
EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=160)
    password: str = Field(min_length=6, max_length=128)
    # Self-registration can only ever create a driver. Tier 1/2 must be granted
    # by an admin (needs_accessible is honoured for Tier 1 at registration so a
    # driver can declare a disability, but the tier itself stays 3 by default).
    priority_tier: int = Field(default=3, ge=1, le=3)
    needs_accessible: bool = False


class LoginRequest(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=160)
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class VehicleCreate(BaseModel):
    plate_or_tag_id: str = Field(min_length=3, max_length=32)
    type: VehicleType

    @field_validator("plate_or_tag_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("plate_or_tag_id must not be empty")
        return v


class VehicleUpdate(BaseModel):
    plate_or_tag_id: Optional[str] = Field(default=None, min_length=3, max_length=32)
    type: Optional[VehicleType] = None
    active_today: Optional[bool] = None


class VehicleOut(BaseModel):
    id: str
    plate_or_tag_id: str
    type: str
    active_today: bool
    created_at: Optional[datetime] = None

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v):
        return _enum_val(v)

    model_config = ConfigDict(from_attributes=True)


class DestinationUpdate(BaseModel):
    building_id: Optional[str] = None


class TierUpdate(BaseModel):
    """Admin edit of a user's priority tier / accessibility need."""
    priority_tier: Optional[int] = Field(default=None, ge=1, le=3)
    needs_accessible: Optional[bool] = None
