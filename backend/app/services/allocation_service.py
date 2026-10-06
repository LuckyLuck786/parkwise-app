"""Allocation engine.

Flow for one gate scan:
  1. resolve the vehicle (reject unknown tags)
  2. reject if the driver already holds a bay (one bay per account)
  3. build the candidate set: correct vehicle type, bay free, reservation rules
     (accessible bays -> Tier 1, Tier 2 quota held until the cut-off hour)
  4. rank: accessible first for Tier 1, then walking distance to the
     destination building, then lot fill balance
  5. claim atomically (conditional UPDATE ... WHERE state='free'), so two
     simultaneous scans can never claim the same bay
  6. if the preferred lot is full, offer the nearest lot with space (with an
     estimated drive time); if nothing anywhere, waitlist
  7. every decision carries an explanation: rule applied, candidates
     considered, why this bay, why others were rejected

No decision is ever hardcoded: quota, cut-off and grace values come from the
`rules` table via rules_service.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import (
    Allotment,
    AllotmentStatus,
    AuditLog,
    Bay,
    BayState,
    Building,
    Lot,
    Vehicle,
    as_utc_naive,
    utcnow,
)
from app.schemas.allocation import AllocationDecision
from app.services import notification_service
from app.services.distance_utils import (
    estimate_drive_time_minutes,
    estimate_walk_meters,
)
from app.services.rules_service import get_rule, get_rules
from app.services.waitlist_service import add_to_waitlist, get_position, get_waitlist_queue

MAX_REJECTION_SAMPLES = 15  # keep explanations readable


def _naive(dt: datetime) -> datetime:
    return as_utc_naive(dt)


def _accessible_allowed(user, bay: Bay, rules: Dict[str, Any]) -> Tuple[bool, str]:
    if not bay.is_accessible:
        return True, ""
    if user.priority_tier == 1 or user.needs_accessible:
        return True, ""
    if rules.get("accessible_reserved_for_tier1", True):
        return False, "accessible_bay_reserved_for_tier1"
    return True, ""


def _tier2_allowed(user, bay: Bay, after_cutoff: bool, cutoff_hour: int) -> Tuple[bool, str]:
    if bay.reserved_tier != 2:
        return True, ""
    if user.priority_tier in (1, 2):
        return True, ""
    if after_cutoff:
        return True, ""
    return False, f"reserved_for_tier2_until_{cutoff_hour:02d}:00"


def _classify(
    db: Session,
    bay: Bay,
    vehicle: Vehicle,
    user,
    after_cutoff: bool,
    cutoff_hour: int,
    rules: Dict[str, Any],
) -> Tuple[bool, str]:
    """Return (is_candidate, rejection_reason)."""
    if bay.type != vehicle.type:
        return False, f"vehicle_type_mismatch ({vehicle.type.value} bay)"
    if bay.state != BayState.free:
        return False, f"bay_state_{bay.state.value}"
    ok, reason = _accessible_allowed(user, bay, rules)
    if not ok:
        return False, reason
    ok, reason = _tier2_allowed(user, bay, after_cutoff, cutoff_hour)
    if not ok:
        return False, reason
    return True, ""


def _rank(user, bays: List[Bay], dest_building: Optional[Building]) -> List[Bay]:
    """Accessible first for Tier 1, then walking distance, then label."""

    def key(bay: Bay):
        tier1 = user.priority_tier == 1 or user.needs_accessible
        acc_first = 0 if (tier1 and bay.is_accessible) else 1
        dist = estimate_walk_meters(bay, dest_building)
        return (acc_first, dist, bay.label)

    return sorted(bays, key=key)


def _lot_free_counts(db: Session, vehicle: Vehicle, user, after_cutoff: bool,
                     cutoff_hour: int, rules: Dict[str, Any], exclude_lot: Optional[str] = None):
    """Free, rule-eligible bays per lot -> ({lot_id: [bays]}, rejects, evaluated)."""
    bays = db.query(Bay).filter(Bay.state == BayState.free).all()
    per_lot: Dict[str, List[Bay]] = {}
    rejects: Dict[str, int] = {}
    evaluated = 0
    for bay in bays:
        if exclude_lot and bay.lot_id == exclude_lot:
            continue
        evaluated += 1
        ok, reason = _classify(db, bay, vehicle, user, after_cutoff, cutoff_hour, rules)
        if ok:
            per_lot.setdefault(bay.lot_id, []).append(bay)
        else:
            rejects[reason] = rejects.get(reason, 0) + 1
    return per_lot, rejects, evaluated


def _claim(db: Session, bay_id: str) -> bool:
    """Atomic claim: only succeeds if the bay is still free."""
    claimed = (
        db.query(Bay)
        .filter(Bay.id == bay_id, Bay.state == BayState.free)
        .update({"state": BayState.allotted}, synchronize_session="fetch")
    )
    db.flush()
    return bool(claimed)


def _preferred_lot(db: Session, lot_preference_id: Optional[str],
                   destination_building_id: Optional[str]) -> Optional[Lot]:
    if lot_preference_id:
        return db.query(Lot).filter(Lot.id == lot_preference_id).first()
    if destination_building_id:
        building = db.query(Building).filter(Building.id == destination_building_id).first()
        if building and building.lat is not None:
            lots = db.query(Lot).all()
            with_coords = [l for l in lots if l.lat is not None and l.lng is not None]
            if with_coords:
                return min(
                    with_coords,
                    key=lambda l: abs(l.lat - building.lat) * 100000
                    + abs(l.lng - building.lng) * 100000,
                )
    return None


def allocate_bay(
    db: Session,
    plate_or_tag_id: str,
    destination_building_id: Optional[str] = None,
    lot_preference_id: Optional[str] = None,
    current_time: Optional[datetime] = None,
    actor: str = "gate",
) -> AllocationDecision:
    if current_time is None:
        current_time = utcnow()
    current_time = _naive(current_time)

    rules = get_rules(db)
    cutoff_hour = int(rules.get("tier2_cutoff_hour", 10))
    grace_minutes = int(rules.get("grace_period_minutes", 10))
    after_cutoff = current_time.hour >= cutoff_hour
    rules_in_effect = {
        "tier2_cutoff_hour": cutoff_hour,
        "grace_period_minutes": grace_minutes,
        "tier2_quota_pct": rules.get("tier2_quota_pct"),
        "tier1_quota_pct": rules.get("tier1_quota_pct"),
        "accessible_reserved_for_tier1": rules.get("accessible_reserved_for_tier1", True),
        "after_tier2_cutoff": after_cutoff,
    }

    # ---- 1. resolve the vehicle -------------------------------------------
    vehicle = db.query(Vehicle).filter(Vehicle.plate_or_tag_id == plate_or_tag_id).first()
    if vehicle is None:
        return AllocationDecision(
            success=False,
            status="rejected",
            message="Vehicle not registered",
            explanation={
                "rule_applied": "vehicle_must_be_registered",
                "rejection_reasons": ["vehicle_not_registered"],
                "scanned_tag": plate_or_tag_id,
                "rules_in_effect": rules_in_effect,
            },
        )

    user = vehicle.user

    # ---- 2. one bay per account -------------------------------------------
    active = (
        db.query(Allotment)
        .join(Vehicle, Allotment.vehicle_id == Vehicle.id)
        .filter(
            Vehicle.user_id == user.id,
            Allotment.status.in_([AllotmentStatus.allotted, AllotmentStatus.occupied]),
        )
        .first()
    )
    if active is not None:
        return AllocationDecision(
            success=False,
            status="rejected",
            message=f"User already holds active allotment in bay {active.bay.label}",
            explanation={
                "rule_applied": "one_active_allotment_per_account",
                "rejection_reasons": ["active_allotment_exists"],
                "held_bay": active.bay.label,
                "held_lot": active.bay.lot.name if active.bay.lot else None,
                "rules_in_effect": rules_in_effect,
            },
        )

    # ---- 3. destination & preferred lot ------------------------------------
    dest_building = None
    if destination_building_id:
        dest_building = db.query(Building).filter(Building.id == destination_building_id).first()
    pref_lot = _preferred_lot(db, lot_preference_id, destination_building_id)

    # ---- 4. candidates in the preferred lot --------------------------------
    rejections: Dict[str, int] = {}
    considered = 0
    chosen_bay: Optional[Bay] = None
    candidates: List[Bay] = []

    if pref_lot is not None:
        lot_bays = db.query(Bay).filter(Bay.lot_id == pref_lot.id).all()
        for bay in lot_bays:
            considered += 1
            ok, reason = _classify(db, bay, vehicle, user, after_cutoff, cutoff_hour, rules)
            if ok:
                candidates.append(bay)
            else:
                rejections[reason] = rejections.get(reason, 0) + 1
        for bay in _rank(user, candidates, dest_building):
            if _claim(db, bay.id):
                chosen_bay = db.query(Bay).filter(Bay.id == bay.id).first()
                break

    # ---- 5. alternative lots -----------------------------------------------
    alternative_lot: Optional[Lot] = None
    best_drive_time: Optional[int] = None
    alt_free = 0
    alt_rejects: Dict[str, int] = {}

    alt_evaluated = 0
    if chosen_bay is None:
        per_lot, alt_rejects, alt_evaluated = _lot_free_counts(
            db, vehicle, user, after_cutoff, cutoff_hour, rules,
            exclude_lot=pref_lot.id if pref_lot else None,
        )
        for reason, count in alt_rejects.items():
            rejections[reason] = rejections.get(reason, 0) + count

        if per_lot:
            ranked_lots = []
            for lot_id, bays in per_lot.items():
                lot = db.query(Lot).filter(Lot.id == lot_id).first()
                if lot is None:
                    continue
                drive = estimate_drive_time_minutes(pref_lot, lot) if pref_lot else 0
                fill_balance = len(bays)
                ranked_lots.append((drive, -fill_balance, lot, bays))
            ranked_lots.sort(key=lambda t: (t[0], t[1]))

            for drive, _, lot, bays in ranked_lots:
                for bay in _rank(user, bays, dest_building):
                    if _claim(db, bay.id):
                        chosen_bay = db.query(Bay).filter(Bay.id == bay.id).first()
                        alternative_lot = lot
                        best_drive_time = drive
                        alt_free = len(bays)
                        break
                if chosen_bay:
                    break

    # ---- 6. waitlist --------------------------------------------------------
    if chosen_bay is None:
        entry = add_to_waitlist(db, vehicle.id, pref_lot.id if pref_lot else None, current_time)
        position = get_position(db, entry.id) or (len(get_waitlist_queue(db)) or 1)
        explanation = {
            "rule_applied": "waitlist_when_no_bay_anywhere",
            "ordering_rule": "priority_tier_then_arrival_time",
            "user_tier": user.priority_tier,
            "vehicle_type": vehicle.type.value,
            "preferred_lot": pref_lot.name if pref_lot else None,
            "destination": dest_building.name if dest_building else None,
            "candidates_considered": considered,
            "rejections": dict(sorted(rejections.items(), key=lambda kv: -kv[1])),
            "waitlist_position": position,
            "hold_grace_minutes": grace_minutes,
            "rules_in_effect": rules_in_effect,
        }
        db.add(
            AuditLog(
                actor=actor,
                action="allocate_bay_waitlisted",
                details={
                    "vehicle_id": vehicle.id,
                    "tag": vehicle.plate_or_tag_id,
                    "position": position,
                    "rejections": explanation["rejections"],
                },
                ts=current_time,
            )
        )
        db.commit()
        notification_service.notify(
            db,
            user.id,
            f"All lots are full. You are #{position} on the waitlist; "
            f"you will be notified when a bay frees up.",
            ts=current_time,
        )
        return AllocationDecision(
            success=False,
            status="waitlisted",
            waitlist_position=position,
            message="All lots full. Placed on priority waitlist.",
            explanation=explanation,
        )

    # ---- 7. explanation + audit + notification ------------------------------
    walk_m = estimate_walk_meters(chosen_bay, dest_building)
    chosen_lot = chosen_bay.lot
    offered_alternative = alternative_lot is not None and pref_lot is not None \
        and alternative_lot.id != pref_lot.id

    rejection_summary = dict(sorted(rejections.items(), key=lambda kv: -kv[1]))

    if offered_alternative:
        chosen_reason = (
            f"Preferred lot had no eligible {vehicle.type.value} bay; "
            f"{alternative_lot.name} is the nearest lot with space "
            f"(~{best_drive_time} min drive, {alt_free} bays free)."
        )
    elif pref_lot is None:
        chosen_reason = f"Nearest eligible bay to {dest_building.name if dest_building else 'campus'}."
    else:
        chosen_reason = (
            f"Nearest eligible {vehicle.type.value} bay in {chosen_lot.name} "
            f"to {dest_building.name if dest_building else 'your destination'} "
            f"(~{walk_m:.0f} m walk)."
        )

    explanation: Dict[str, Any] = {
        "rule_applied": "tier_quota_then_distance_then_fill_balance",
        "user_tier": user.priority_tier,
        "needs_accessible": bool(user.needs_accessible),
        "vehicle_type": vehicle.type.value,
        "preferred_lot": pref_lot.name if pref_lot else "auto (nearest to destination)",
        "destination": dest_building.name if dest_building else None,
        "candidates_considered": considered + alt_evaluated,
        "candidates_after_rules": len(candidates),
        "rejections": rejection_summary,
        "chosen": {
            "bay": chosen_bay.label,
            "lot": chosen_lot.name,
            "is_accessible": bool(chosen_bay.is_accessible),
            "reserved_tier": chosen_bay.reserved_tier,
            "walk_meters_estimate": round(walk_m, 1),
            "reason": chosen_reason,
        },
        "alternatives": [
            {
                "lot": alternative_lot.name,
                "free_bays": alt_free,
                "estimated_drive_time_mins": best_drive_time,
            }
        ] if offered_alternative else [],
        "rules_in_effect": rules_in_effect,
    }

    allotment = Allotment(
        vehicle_id=vehicle.id,
        bay_id=chosen_bay.id,
        status=AllotmentStatus.allotted,
        allotted_at=current_time,
        explanation=explanation,
    )
    db.add(allotment)
    chosen_bay.state = BayState.allotted
    db.add(
        AuditLog(
            actor=actor,
            action="allocate_bay",
            details={
                "vehicle_id": vehicle.id,
                "tag": vehicle.plate_or_tag_id,
                "bay_id": chosen_bay.id,
                "bay": chosen_lot.name + "/" + chosen_bay.label,
                "tier": user.priority_tier,
                "offered_alternative": offered_alternative,
                "rejections": rejection_summary,
            },
            ts=current_time,
        )
    )
    db.commit()
    db.refresh(allotment)

    status = "offered_alternative" if offered_alternative else "allotted"
    if offered_alternative:
        msg = f"Preferred lot full. Allotted bay {chosen_bay.label} in {chosen_lot.name}"
        notification_service.notify(
            db,
            user.id,
            (
                f"{pref_lot.name} is full. Bay {chosen_bay.label} in {chosen_lot.name} is held "
                f"for you (~{best_drive_time} min drive). Arrive within {grace_minutes} minutes."
            ),
            ts=current_time,
        )
    else:
        msg = f"Allotted bay {chosen_bay.label} in lot {chosen_lot.name}"
        notification_service.notify(
            db,
            user.id,
            f"Bay {chosen_bay.label} allotted in {chosen_lot.name}. Arrive within {grace_minutes} minutes.",
            ts=current_time,
        )

    return AllocationDecision(
        success=True,
        status=status,
        bay={
            "id": chosen_bay.id,
            "label": chosen_bay.label,
            "lot_name": chosen_lot.name,
            "type": chosen_bay.type.value,
            "is_accessible": chosen_bay.is_accessible,
            "reserved_tier": chosen_bay.reserved_tier,
            "x": chosen_bay.x,
            "y": chosen_bay.y,
        },
        lot={
            "id": chosen_lot.id,
            "name": chosen_lot.name,
            "lat": chosen_lot.lat,
            "lng": chosen_lot.lng,
        },
        alternative_lot=(
            {
                "id": alternative_lot.id,
                "name": alternative_lot.name,
                "estimated_drive_time_mins": best_drive_time,
                "available_bays": alt_free,
            }
            if offered_alternative else None
        ),
        message=msg,
        explanation=explanation,
        allotment_id=allotment.id,
    )
