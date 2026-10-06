"""Reconciliation: compare scan-assigned state vs sensor-observed state.

Conflict types raised (always with a reason, never an automatic punishment):

  * unauthorized_occupancy   — bay physically occupied with no gate allotment
  * wrong_bay_parking        — bay occupied with no allotment while another bay
                               in the same lot is scanned-in but not arrived
  * occupied_bay_not_exited  — system believes the bay is occupied but the
                               sensor reports it empty and no allotment is open
                               (exit never recorded)
  * no_show                  — allotted bay still empty after the grace period
  * blocked_bay_occupied     — sensor sees a car in a bay marked blocked
  * device_offline           — missed heartbeats -> fall back to scan-inferred
                               state and flag low confidence

Every transition is written to the audit log with its explanation.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import (
    Allotment,
    AllotmentStatus,
    AuditLog,
    Bay,
    BayEvent,
    BayState,
    Device,
    DeviceStatus,
    as_utc_naive,
    utcnow,
)
from app.services.rules_service import get_rule
from app.services.waitlist_service import fulfill_offer, promote_waitlist_head


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    return as_utc_naive(dt)


def _raise_conflict(db: Session, conflict: Dict[str, Any], current_time: datetime) -> Dict[str, Any]:
    db.add(
        AuditLog(
            actor="reconcile_service",
            action="conflict_detected",
            details=conflict,
            ts=current_time,
        )
    )
    db.commit()
    return conflict


def reconcile_bay_event(
    db: Session,
    bay_id: str,
    sensor_occupied: bool,
    sensor_confidence: float = 1.0,
    current_time: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Apply one normalized bay-occupancy observation. Returns a conflict dict
    when something disagrees, else None."""
    if current_time is None:
        current_time = utcnow()
    current_time = _naive(current_time)

    bay = db.query(Bay).filter(Bay.id == bay_id).first()
    if bay is None:
        return None

    grace_minutes = int(get_rule(db, "grace_period_minutes", 10))
    timeout_seconds = int(get_rule(db, "heartbeat_timeout_seconds", 120))

    active = (
        db.query(Allotment)
        .filter(
            Allotment.bay_id == bay.id,
            Allotment.status.in_([AllotmentStatus.allotted, AllotmentStatus.occupied]),
        )
        .first()
    )

    # ---------------------------------------------- sensor reports occupied --
    if sensor_occupied:
        if bay.state == BayState.blocked:
            return _raise_conflict(
                db,
                {
                    "conflict_type": "blocked_bay_occupied",
                    "bay_id": bay.id,
                    "bay_label": bay.label,
                    "lot_id": bay.lot_id,
                    "severity": "warning",
                    "message": f"Bay {bay.label} is marked blocked but a vehicle is detected in it.",
                    "confidence": sensor_confidence,
                    "recommended_action": "Check the bay blockage and clear it manually if safe.",
                    "ts": current_time.isoformat(),
                },
                current_time,
            )

        if active is None:
            # Is someone scanned-in to another bay in this lot? -> wrong bay.
            pending = (
                db.query(Allotment)
                .join(Bay, Allotment.bay_id == Bay.id)
                .filter(
                    Bay.lot_id == bay.lot_id,
                    Allotment.status == AllotmentStatus.allotted,
                )
                .all()
            )
            if pending:
                expected = ", ".join(f"{a.bay.label}" for a in pending)
                vehicles = ", ".join(
                    sorted({a.vehicle.plate_or_tag_id for a in pending if a.vehicle})
                )
                conflict = {
                    "conflict_type": "wrong_bay_parking",
                    "bay_id": bay.id,
                    "bay_label": bay.label,
                    "lot_id": bay.lot_id,
                    "severity": "warning",
                    "message": (
                        f"Bay {bay.label} is occupied with no allotment while "
                        f"scanned-in vehicle(s) {vehicles} are expected at {expected} in the same lot."
                    ),
                    "confidence": sensor_confidence,
                    "suspected_vehicles": sorted(
                        {a.vehicle.plate_or_tag_id for a in pending if a.vehicle}
                    ),
                    "recommended_action": "Verify visually; the driver may have parked in the wrong bay. No automatic penalty.",
                    "ts": current_time.isoformat(),
                }
                bay.state = BayState.occupied
                return _raise_conflict(db, conflict, current_time)

            conflict = {
                "conflict_type": "unauthorized_occupancy",
                "bay_id": bay.id,
                "bay_label": bay.label,
                "lot_id": bay.lot_id,
                "severity": "warning",
                "message": f"Bay {bay.label} is physically occupied without an active gate allotment.",
                "confidence": sensor_confidence,
                "recommended_action": "Security patrol verification requested. No automatic penalty.",
                "ts": current_time.isoformat(),
            }
            bay.state = BayState.occupied
            return _raise_conflict(db, conflict, current_time)

        if active.status == AllotmentStatus.allotted:
            active.status = AllotmentStatus.occupied
            active.arrived_at = current_time
            bay.state = BayState.occupied
            fulfill_offer(db, bay.id)
            db.add(
                AuditLog(
                    actor="reconcile_service",
                    action="vehicle_arrived_at_bay",
                    details={
                        "bay_id": bay.id,
                        "allotment_id": active.id,
                        "vehicle_id": active.vehicle_id,
                        "confidence": sensor_confidence,
                        "source": "sensor",
                    },
                    ts=current_time,
                )
            )
            db.commit()
        # Already occupied -> duplicate observation, nothing to change.
        return None

    # ---------------------------------------------- sensor reports empty -----
    if active is not None:
        if active.status == AllotmentStatus.occupied:
            active.status = AllotmentStatus.completed
            active.released_at = current_time
            bay.state = BayState.free
            db.add(
                AuditLog(
                    actor="reconcile_service",
                    action="vehicle_departed_bay",
                    details={
                        "bay_id": bay.id,
                        "allotment_id": active.id,
                        "vehicle_id": active.vehicle_id,
                        "confidence": sensor_confidence,
                    },
                    ts=current_time,
                )
            )
            db.commit()
            promote_waitlist_head(db, bay.id, current_time)
            return None

        # status == allotted: has the grace period expired?
        allotted_at = _naive(active.allotted_at)
        if allotted_at is not None and (current_time - allotted_at) > timedelta(minutes=grace_minutes):
            conflict = {
                "conflict_type": "no_show",
                "bay_id": bay.id,
                "bay_label": bay.label,
                "lot_id": bay.lot_id,
                "severity": "info",
                "message": (
                    f"Bay {bay.label} is still empty {grace_minutes} minutes after allotment."
                ),
                "confidence": sensor_confidence,
                "recommended_action": "Bay released back to the pool and offered to the waitlist.",
                "ts": current_time.isoformat(),
            }
            _raise_conflict(db, conflict, current_time)
            # Release (this also notifies the driver and promotes the waitlist).
            from app.services.noshow_service import check_and_release_noshows

            check_and_release_noshows(db, current_time=current_time)
            return conflict
        return None

    # No open allotment. Is our own record stale?
    if bay.state == BayState.occupied:
        conflict = {
            "conflict_type": "occupied_bay_not_exited",
            "bay_id": bay.id,
            "bay_label": bay.label,
            "lot_id": bay.lot_id,
            "severity": "info",
            "message": (
                f"Bay {bay.label} was recorded as occupied but no allotment is open and the "
                f"sensor now reports it empty — the exit was never recorded."
            ),
            "confidence": sensor_confidence,
            "recommended_action": "State corrected to free; the missed exit is logged for audit.",
            "ts": current_time.isoformat(),
        }
        bay.state = BayState.free
        _raise_conflict(db, conflict, current_time)
        promote_waitlist_head(db, bay.id, current_time)
        return conflict

    return None


def check_device_heartbeats(
    db: Session,
    timeout_seconds: Optional[int] = None,
    current_time: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Mark devices offline when they stop heartbeating; alert once per change."""
    if current_time is None:
        current_time = utcnow()
    current_time = _naive(current_time)
    if timeout_seconds is None:
        timeout_seconds = int(get_rule(db, "heartbeat_timeout_seconds", 120))

    cutoff = current_time - timedelta(seconds=timeout_seconds)
    alerts: List[Dict[str, Any]] = []
    for dev in db.query(Device).all():
        last = _naive(dev.last_heartbeat)
        missed = last is None or last < cutoff
        if missed and dev.status != DeviceStatus.offline:
            dev.status = DeviceStatus.offline
            alert = {
                "device_id": dev.id,
                "device_name": dev.name,
                "kind": dev.kind.value if dev.kind else None,
                "status": "offline",
                "message": (
                    f"Device {dev.name} missed heartbeats for more than {timeout_seconds}s. "
                    f"Falling back to scan-inferred state with a low-confidence badge."
                ),
                "ts": current_time.isoformat(),
            }
            alerts.append(alert)
            db.add(
                AuditLog(
                    actor="reconcile_service",
                    action="device_offline",
                    details=alert,
                    ts=current_time,
                )
            )
    if alerts:
        db.commit()
    return alerts


def bay_confidence_map(
    db: Session,
    timeout_seconds: Optional[int] = None,
    current_time: Optional[datetime] = None,
    low_threshold: Optional[float] = None,
) -> Dict[str, Dict[str, Any]]:
    """Per-bay confidence/state-source used for the low-confidence badge.

    Sensors report *changes*, not periodic state, so a bay's last event being
    old is normal. What matters is whether the devices are heartbeating:

    state_source:
      * "sensor"         — derived from a sensor observation while the fleet
                           is online
      * "scan_inferred"  — devices missed heartbeats (or there is no sensor
                           evidence), so the state falls back to what the gate
                           scans imply — this is what gets the badge
      * "initial"        — no evidence at all (fresh/seeded free state)
    """
    if current_time is None:
        current_time = utcnow()
    current_time = _naive(current_time)
    if timeout_seconds is None:
        timeout_seconds = int(get_rule(db, "heartbeat_timeout_seconds", 120))
    if low_threshold is None:
        low_threshold = float(get_rule(db, "low_confidence_threshold", 0.6))

    window_start = current_time - timedelta(seconds=timeout_seconds)

    # Is any sensor-capable device actually alive right now?
    devices_online = any(
        dev.status == DeviceStatus.online
        and (_naive(dev.last_heartbeat) or datetime.min) >= window_start
        for dev in db.query(Device).all()
    )

    latest: Dict[str, BayEvent] = {}
    for ev in (
        db.query(BayEvent)
        .order_by(BayEvent.ts.desc())
        .limit(5000)
        .all()
    ):
        ev_ts = _naive(ev.ts)
        if ev.bay_id not in latest and ev_ts is not None and ev_ts <= current_time:
            latest[ev.bay_id] = ev

    out: Dict[str, Dict[str, Any]] = {}
    for bay in db.query(Bay).all():
        ev = latest.get(bay.id)
        ev_ts = _naive(ev.ts) if ev else None

        if ev is not None and ev_ts is not None and ev_ts >= window_start:
            # Fresh observation.
            confidence = float(ev.confidence)
            source = "sensor"
        elif ev is not None and devices_online:
            # Old observation, but the fleet is alive: sensors only report
            # changes, so we still trust the last reading.
            confidence = float(ev.confidence)
            source = "sensor"
        elif ev is not None:
            # Devices went quiet -> scan-inferred with a low-confidence badge.
            confidence = min(float(ev.confidence), 0.5)
            source = "scan_inferred"
        else:
            if bay.state in (BayState.free, BayState.allotted):
                confidence = 1.0
                source = "initial" if bay.state == BayState.free else "scan_inferred"
            else:
                confidence = 1.0 if devices_online else 0.5
                source = "sensor" if devices_online else "scan_inferred"

        out[bay.id] = {
            "confidence": round(confidence, 2),
            "state_source": source,
            "low_confidence": bool(confidence < low_threshold),
            "last_sensor_ts": ev_ts.isoformat() if ev_ts else None,
            "devices_online": devices_online,
        }
    return out


def get_active_conflicts(db: Session, limit: int = 50) -> List[Dict[str, Any]]:
    """Most recent unresolved conflicts from the audit trail."""
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.action == "conflict_detected")
        .order_by(AuditLog.ts.desc())
        .limit(200)
        .all()
    )
    conflicts: List[Dict[str, Any]] = []
    for log in logs:
        if not log.details or log.details.get("resolved"):
            continue
        conflicts.append({"audit_id": log.id, **log.details})
        if len(conflicts) >= limit:
            break
    return conflicts


def resolve_conflict(db: Session, audit_id: str, actor: str = "admin") -> bool:
    """Human resolution of a conflict — marks it resolved in the audit trail."""
    log = db.query(AuditLog).filter(AuditLog.id == audit_id).first()
    if log is None or log.action != "conflict_detected":
        return False
    details = dict(log.details or {})
    details["resolved"] = True
    log.details = details
    db.add(
        AuditLog(
            actor=actor,
            action="conflict_resolved",
            details={"conflict_audit_id": audit_id, "original": log.details},
        )
    )
    db.commit()
    return True
