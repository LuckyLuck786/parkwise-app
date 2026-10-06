import enum
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON, Enum as SAEnum, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
import uuid

def generate_uuid() -> str:
    return str(uuid.uuid4())

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize any incoming datetime to naive UTC (the storage format).

    Aware values are converted to UTC first, then stripped; naive values are
    assumed to already be UTC (which is how this app writes them).
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

# Enums
class UserRole(str, enum.Enum):
    driver = "driver"
    admin = "admin"
    gate_operator = "gate_operator"

class PriorityTier(int, enum.Enum):
    tier_1 = 1
    tier_2 = 2
    tier_3 = 3

class VehicleType(str, enum.Enum):
    two_wheeler = "two_wheeler"
    four_wheeler = "four_wheeler"

class BayState(str, enum.Enum):
    free = "free"
    allotted = "allotted"
    occupied = "occupied"
    blocked = "blocked"
    unknown = "unknown"

class AllotmentStatus(str, enum.Enum):
    allotted = "allotted"
    occupied = "occupied"
    completed = "completed"
    no_show_released = "no_show_released"
    cancelled = "cancelled"

class WaitlistStatus(str, enum.Enum):
    waiting = "waiting"
    offered = "offered"
    fulfilled = "fulfilled"
    expired = "expired"
    cancelled = "cancelled"

class ScanDirection(str, enum.Enum):
    in_scan = "in_scan"
    out_scan = "out_scan"

class EventSource(str, enum.Enum):
    simulator = "simulator"
    ir_sensor = "ir_sensor"
    webcam = "webcam"
    manual = "manual"

class DeviceKind(str, enum.Enum):
    ir_sensor = "ir_sensor"
    webcam = "webcam"
    gate_scanner = "gate_scanner"

class DeviceStatus(str, enum.Enum):
    online = "online"
    offline = "offline"
    degraded = "degraded"

class NotificationChannel(str, enum.Enum):
    in_app = "in_app"
    sms = "sms"
    telegram = "telegram"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.driver, nullable=False)
    priority_tier: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    needs_accessible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    destination_building_id: Mapped[Optional[str]] = mapped_column(ForeignKey("buildings.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    vehicles: Mapped[List["Vehicle"]] = relationship("Vehicle", back_populates="user")
    notifications: Mapped[List["Notification"]] = relationship("Notification", back_populates="user")
    destination_building: Mapped[Optional["Building"]] = relationship("Building")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    plate_or_tag_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    type: Mapped[VehicleType] = mapped_column(SAEnum(VehicleType), nullable=False)
    active_today: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="vehicles")
    allotments: Mapped[List["Allotment"]] = relationship("Allotment", back_populates="vehicle")
    scan_events: Mapped[List["ScanEvent"]] = relationship("ScanEvent", back_populates="vehicle")


class Lot(Base):
    __tablename__ = "lots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    bays: Mapped[List["Bay"]] = relationship("Bay", back_populates="lot")


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class Bay(Base):
    __tablename__ = "bays"
    __table_args__ = (
        UniqueConstraint("lot_id", "label", name="uix_lot_id_label"),
        Index("ix_bay_state", "state"),
        Index("ix_bay_lot_id_state", "lot_id", "state"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    lot_id: Mapped[str] = mapped_column(ForeignKey("lots.id"), nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[VehicleType] = mapped_column(SAEnum(VehicleType), nullable=False)
    is_accessible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reserved_tier: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    nearest_building_id: Mapped[Optional[str]] = mapped_column(ForeignKey("buildings.id"), nullable=True)
    state: Mapped[BayState] = mapped_column(SAEnum(BayState), default=BayState.free, nullable=False)

    lot: Mapped["Lot"] = relationship("Lot", back_populates="bays")
    nearest_building: Mapped[Optional["Building"]] = relationship("Building")
    allotments: Mapped[List["Allotment"]] = relationship("Allotment", back_populates="bay")
    bay_events: Mapped[List["BayEvent"]] = relationship("BayEvent", back_populates="bay")


class Allotment(Base):
    __tablename__ = "allotments"
    __table_args__ = (
        Index("ix_allotment_status", "status"),
        Index("ix_allotment_vehicle_id_status", "vehicle_id", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    bay_id: Mapped[str] = mapped_column(ForeignKey("bays.id"), nullable=False)
    status: Mapped[AllotmentStatus] = mapped_column(SAEnum(AllotmentStatus), nullable=False)
    allotted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    arrived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    explanation: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="allotments")
    bay: Mapped["Bay"] = relationship("Bay", back_populates="allotments")


class Waitlist(Base):
    __tablename__ = "waitlist"
    __table_args__ = (
        Index("ix_waitlist_status", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    lot_pref_id: Mapped[Optional[str]] = mapped_column(ForeignKey("lots.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    status: Mapped[WaitlistStatus] = mapped_column(SAEnum(WaitlistStatus), default=WaitlistStatus.waiting, nullable=False)
    offered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    offered_bay_id: Mapped[Optional[str]] = mapped_column(ForeignKey("bays.id"), nullable=True)

    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    offered_bay: Mapped[Optional["Bay"]] = relationship("Bay")
    lot_pref: Mapped[Optional["Lot"]] = relationship("Lot", foreign_keys=[lot_pref_id])


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(SAEnum(NotificationChannel), default=NotificationChannel.in_app, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="notifications")


class ScanEvent(Base):
    __tablename__ = "scan_events"
    __table_args__ = (
        Index("ix_scan_events_vehicle_id", "vehicle_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    direction: Mapped[ScanDirection] = mapped_column(SAEnum(ScanDirection), nullable=False)
    source: Mapped[EventSource] = mapped_column(SAEnum(EventSource), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="scan_events")


class BayEvent(Base):
    __tablename__ = "bay_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    bay_id: Mapped[str] = mapped_column(ForeignKey("bays.id"), nullable=False)
    occupied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[EventSource] = mapped_column(SAEnum(EventSource), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    bay: Mapped["Bay"] = relationship("Bay", back_populates="bay_events")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[DeviceKind] = mapped_column(SAEnum(DeviceKind), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String, nullable=False)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[DeviceStatus] = mapped_column(SAEnum(DeviceStatus), default=DeviceStatus.online, nullable=False)
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_ts", "ts"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class AppState(Base):
    """Small key/value store for state that must survive process restarts
    (demo clock, live-state version counter). Keeps the app serverless-safe:
    no reliance on in-process globals."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class SimulationRun(Base):
    """Persisted BASELINE vs ParkWise metric comparison run."""

    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False)
    assumptions: Mapped[dict] = mapped_column(JSON, nullable=False)
    baseline: Mapped[dict] = mapped_column(JSON, nullable=False)
    parkwise: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
