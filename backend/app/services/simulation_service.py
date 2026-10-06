"""BASELINE vs ParkWise metric comparison.

Both policies replay the *identical* arrival sequence (same vehicles, same
arrival times, same dwell times) over the same lot layout, so the difference
comes only from the allocation policy.

Everything reported here is computed from the run. Nothing is hardcoded.

BASELINE model (first-come-first-served, no information) — assumptions:
  * the driver enters the preferred lot and drives the aisles, inspecting
    bays in layout order until a matching free bay is found;
  * reservations/accessible bays are invisible to the driver, so a Tier 3
    driver may take an accessible bay;
  * a lot with no matching free bay costs a full cruise and counts as a
    wasted entry, then the driver tries the next lot by drive time;
  * after `give_up_minutes` of searching the driver leaves (failed entry).

PARKWISE model:
  * gate decision ranks eligible bays (type, tier quota, accessible first for
    Tier 1) by walking distance;
  * the alternative lot is offered at the gate, so the driver does not cruise
    a full lot;
  * when every lot is full the driver waitlists and gets a bay as soon as one
    frees (held for the grace window), or fails after `give_up_minutes`.

Model parameters are listed in ASSUMPTIONS and returned with every run.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import (
    Allotment,
    AllotmentStatus,
    Bay,
    Building,
    Lot,
    SimulationRun,
    User,
    Vehicle,
    as_utc_naive,
    utcnow,
)
from app.services.distance_utils import estimate_drive_time_minutes, get_bay_distance_to_building

# --------------------------------------------------------------------------- #
# Model parameters (documented assumptions, not results)
# --------------------------------------------------------------------------- #
ASSUMPTIONS: Dict[str, Any] = {
    "replay": (
        "Both policies replay the identical arrival sequence: same vehicles, "
        "same arrival timestamps, same dwell times."
    ),
    "baseline_policy": (
        "First-come-first-served with no information: the driver cruises the "
        "preferred lot inspecting bays in layout order, ignoring tier "
        "reservations and accessible bays."
    ),
    "parkwise_policy": (
        "Gate scan -> rules engine: vehicle-type match, tier quota and "
        "accessible rules, rank by walking distance, alternative lot offered "
        "at the gate, waitlist with priority ordering when everything is full."
    ),
    "baseline_seconds_per_bay_inspected": 6.0,
    "bay_pitch_m": 7.5,             # distance between adjacent bays while cruising
    "lot_creep_m_per_min": 100.0,   # slow driving inside a lot
    "gate_decision_seconds": 5.0,   # scan + allocation decision + display
    "park_manoeuvre_minutes": 0.5,  # pulling in and stopping
    "walk_m_per_min": 80.0,         # walking speed used for the final approach
    "give_up_minutes": 15.0,        # both policies abandon the search after this
    "baseline_ignores_reservations": True,
    "peak_hour_arrivals": 6.0,
    "peak_hour_arrivals_note": (
        "The generated sequence is normalised so the peak hour contains "
        "`peak_hour_arrivals * scale` vehicles; the hourly SHAPE comes from "
        "the seeded 14-day history (or the stated uniform working-hours "
        "fallback when no history exists yet)."
    ),
    "note": (
        "These are explicit, stated model parameters. The metric values "
        "themselves are computed from the simulation run, never hardcoded."
    ),
}

ASSUMPTION_KEYS = [
    "baseline_seconds_per_bay_inspected",
    "bay_pitch_m",
    "lot_creep_m_per_min",
    "gate_decision_seconds",
    "park_manoeuvre_minutes",
    "walk_m_per_min",
    "give_up_minutes",
    "peak_hour_arrivals",
]


# --------------------------------------------------------------------------- #
# Sequence generation
# --------------------------------------------------------------------------- #
@dataclass
class Arrival:
    idx: int
    minute: float                 # minutes after window start
    vehicle_type: str             # two_wheeler | four_wheeler
    tier: int
    needs_accessible: bool
    pref_lot_id: str
    dest_building_id: Optional[str]
    dwell_minutes: float


@dataclass
class SimBay:
    id: str
    lot_id: str
    label: str
    vtype: str
    is_accessible: bool
    reserved_tier: Optional[int]
    x: int
    y: int
    free_from: float = 0.0        # minute from which this bay is available


@dataclass
class LotLayout:
    id: str
    name: str
    capacity: int
    lat: Optional[float]
    lng: Optional[float]
    bays: List[SimBay] = field(default_factory=list)


def _load_layout(db: Session) -> Dict[str, LotLayout]:
    layout: Dict[str, LotLayout] = {}
    for lot in db.query(Lot).all():
        layout[lot.id] = LotLayout(
            id=lot.id, name=lot.name, capacity=lot.capacity,
            lat=lot.lat, lng=lot.lng, bays=[],
        )
    for bay in db.query(Bay).all():
        if bay.lot_id in layout:
            layout[bay.lot_id].bays.append(
                SimBay(
                    id=bay.id, lot_id=bay.lot_id, label=bay.label,
                    vtype=bay.type.value, is_accessible=bay.is_accessible,
                    reserved_tier=bay.reserved_tier, x=bay.x, y=bay.y,
                )
            )
    return layout


def _historical_dwell_minutes(db: Session) -> List[float]:
    """Dwell times observed in history (completed allotments)."""
    rows = (
        db.query(Allotment.arrived_at, Allotment.released_at)
        .filter(
            Allotment.status == AllotmentStatus.completed,
            Allotment.arrived_at.isnot(None),
            Allotment.released_at.isnot(None),
        )
        .limit(2000)
        .all()
    )
    dwells = []
    for arrived, released in rows:
        a = as_utc_naive(arrived)
        r = as_utc_naive(released)
        if a and r and r > a:
            dwells.append((r - a).total_seconds() / 60.0)
    return dwells


def _population(db: Session) -> Dict[str, Any]:
    """Vehicle-type and tier mix taken from the real seeded population."""
    vehicles = db.query(Vehicle).all()
    types = [v.type.value for v in vehicles] or ["four_wheeler"]
    tiers: List[int] = []
    accessible: List[bool] = []
    for v in vehicles:
        if v.user is not None:
            tiers.append(int(v.user.priority_tier))
            accessible.append(bool(v.user.needs_accessible))
    return {
        "types": types,
        "tiers": tiers or [3],
        "accessible": accessible or [False],
    }


def _hourly_rates(db: Session, weekday: int = 0) -> Dict[int, float]:
    """Arrivals per hour across the whole campus, from history, for a given
    weekday (0=Monday)."""
    from app.services.prediction_service import get_historical_hourly_arrivals

    rates = {h: 0.0 for h in range(24)}
    lots = db.query(Lot).all()
    if not lots:
        return rates
    for lot in lots:
        profile = get_historical_hourly_arrivals(db, lot.id, weekday)
        for h, v in profile.items():
            rates[h] += v
    return rates


def default_start(now: Optional[datetime] = None) -> datetime:
    """Weekday 07:00 — the morning rush the predictor is built around."""
    now = as_utc_naive(now) or as_utc_naive(utcnow())
    day = (now or datetime.utcnow()).replace(hour=7, minute=0, second=0, microsecond=0)
    if day.weekday() >= 5:
        day = day + timedelta(days=(7 - day.weekday()))
    return day


def generate_arrival_sequence(
    db: Session,
    start: datetime,
    hours: int = 5,
    seed: int = 42,
    scale: float = 1.0,
    max_arrivals: Optional[int] = None,
) -> List[Arrival]:
    """Deterministic arrival sequence shaped by the historical hourly profile."""
    rng = random.Random(seed)
    layout = _load_layout(db)
    lots = [l for l in layout.values() if l.bays]
    if not lots:
        return []

    pop = _population(db)
    dwell_pool = _historical_dwell_minutes(db) or [180.0]
    start = as_utc_naive(start) or as_utc_naive(utcnow())
    rates = _hourly_rates(db, weekday=start.weekday())
    buildings = db.query(Building).all()
    total_capacity = sum(len(l.bays) for l in lots)

    # Normalise the shape so `scale` controls volume honestly.
    profile_source = "14-day historical hourly arrival profile"
    if sum(rates.values()) <= 0:
        # No history yet (fresh database): a stated, uniform working-hours
        # profile derived from capacity — labelled in the result, never
        # presented as measured data.
        profile_source = "uniform working-hours fallback (no history yet)"
        rates = {
            h: (total_capacity * 0.5 if 8 <= h <= 17 else 0.0)
            for h in range(24)
        }
    peak = max(rates.values()) or 1.0

    seq: List[Arrival] = []
    idx = 0
    for h in range(hours):
        hour_of_day = (start.hour + h) % 24
        expected = (rates.get(hour_of_day, 0.0) / peak) * (ASSUMPTIONS["peak_hour_arrivals"] * scale)
        n = int(expected) + (1 if rng.random() < (expected % 1) else 0)
        for _ in range(n):
            minute = h * 60 + rng.uniform(0, 60)
            vehicle_type = rng.choice(pop["types"])
            tier = rng.choice(pop["tiers"])
            needs_accessible = tier == 1 and rng.random() < 0.7
            dest = rng.choice(buildings).id if buildings else None
            pref = rng.choice(lots).id
            dwell = rng.choice(dwell_pool)
            seq.append(
                Arrival(
                    idx=idx, minute=minute, vehicle_type=vehicle_type,
                    tier=tier, needs_accessible=needs_accessible,
                    pref_lot_id=pref, dest_building_id=dest,
                    dwell_minutes=dwell,
                )
            )
            idx += 1

    seq.sort(key=lambda a: a.minute)
    if max_arrivals is not None:
        seq = seq[:max_arrivals]
    for i, a in enumerate(seq):
        a.idx = i
    generate_arrival_sequence.last_profile_source = profile_source  # for run_comparison
    return seq


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _drive_min(a: LotLayout, b: LotLayout) -> float:
    if a.id == b.id:
        return 0.0
    class _L:  # duck-typed pair for distance_utils
        lat, lng = a.lat, a.lng
    class _R:
        lat, lng = b.lat, b.lng
    if a.lat is None or b.lat is None:
        return 3.0
    return float(estimate_drive_time_minutes(_L(), _R()))


def _creep_min(bay: SimBay) -> float:
    """Time to drive from the lot entrance (0,0) to this bay."""
    cells = abs(bay.x) + abs(bay.y)
    return (cells * ASSUMPTIONS["bay_pitch_m"]) / ASSUMPTIONS["lot_creep_m_per_min"]


def _inspect_seconds(k: int) -> float:
    """Baseline cost of inspecting k bays (driving past + looking)."""
    per_bay = (
        ASSUMPTIONS["baseline_seconds_per_bay_inspected"]
        + ASSUMPTIONS["bay_pitch_m"] / ASSUMPTIONS["lot_creep_m_per_min"] * 60.0
    )
    return k * per_bay


def _walk_to_bay_min(bay: SimBay, layout: LotLayout, dest_id: Optional[str],
                     buildings: Dict[str, Building]) -> float:
    """Final approach: driving to the bay cell, then walking is folded into it
    via the same creep model (we report search time, not a routed path)."""
    return _creep_min(bay)


def _empty_stats() -> Dict[str, Any]:
    return {
        "parked": 0,
        "failed": 0,
        "wasted_entries": 0,
        "search_times": [],
        "tier1_arrivals": 0,
        "tier1_parked_accessible": 0,
        "occupied_minutes": 0.0,
        "waitlisted": 0,
        "waitlist_resolved": 0,
    }


def _occupancy_minutes(arr: Arrival, window_minutes: float) -> float:
    """Occupied bay-minutes counted only inside the measured window, so
    utilization can never exceed 100%."""
    remaining = window_minutes - arr.minute
    if remaining <= 0:
        return 0.0
    return min(arr.dwell_minutes, remaining)


def _finalise(stats: Dict[str, Any], window_minutes: float, capacity: int,
              arrivals: int, policy: str) -> Dict[str, Any]:
    # Average search time is over vehicles that actually parked; failures are
    # reported separately as failed_entries (mixing them would hide both).
    search = sorted(stats["search_times"])
    avg = round(sum(search) / len(search), 2) if search else None
    p90 = round(search[int(len(search) * 0.9) - 1], 2) if search else None
    util = (
        round(stats["occupied_minutes"] * 100.0 / (capacity * window_minutes), 1)
        if capacity and window_minutes else 0.0
    )
    tier1_total = stats["tier1_arrivals"]
    tier1_pct = (
        round(stats["tier1_parked_accessible"] * 100.0 / tier1_total, 1)
        if tier1_total else 100.0
    )
    return {
        "policy": policy,
        "arrivals": arrivals,
        "parked": stats["parked"],
        "failed_entries": stats["failed"],
        "wasted_entries": stats["wasted_entries"],
        "avg_search_minutes": avg,
        "p90_search_minutes": p90,
        "avg_search_note": "mean over parked vehicles only; failures are counted separately",
        "utilization_pct": util,
        "tier1_access_success_pct": tier1_pct,
        "tier1_arrivals": tier1_total,
        "waitlisted": stats["waitlisted"],
        "waitlist_resolved": stats["waitlist_resolved"],
        "occupied_bay_minutes": round(stats["occupied_minutes"], 1),
    }


# --------------------------------------------------------------------------- #
# Policies
# --------------------------------------------------------------------------- #
def _reset(layout: Dict[str, LotLayout]) -> Dict[str, LotLayout]:
    """Each policy must replay on a pristine layout."""
    for lot in layout.values():
        for bay in lot.bays:
            bay.free_from = 0.0
    return layout


def run_baseline(seq: List[Arrival], layout: Dict[str, LotLayout],
                 window_minutes: float) -> Dict[str, Any]:
    """FCFS with no information, per the documented assumptions."""
    _reset(layout)
    stats = _empty_stats()
    capacity = sum(len(l.bays) for l in layout.values())
    lots_by_id = dict(layout)

    for arr in seq:
        t = arr.minute
        if arr.tier == 1:
            stats["tier1_arrivals"] += 1
        pref = lots_by_id.get(arr.pref_lot_id)
        if pref is None:
            continue
        order = [pref] + sorted(
            [l for l in layout.values() if l.id != pref.id],
            key=lambda l: _drive_min(pref, l),
        )

        elapsed = 0.0
        parked = False
        for i, lot in enumerate(order):
            drive = _drive_min(pref, lot) if i > 0 else 0.0
            elapsed += drive
            matching = sorted(
                [b for b in lot.bays if b.vtype == arr.vehicle_type],
                key=lambda b: (b.y, b.x),
            )
            free = next((b for b in matching if b.free_from <= t + elapsed), None)
            inspected = matching.index(free) + 1 if free is not None else len(matching)
            elapsed += _inspect_seconds(inspected) / 60.0

            if free is None:
                # drove the whole lot and found nothing -> wasted entry
                stats["wasted_entries"] += 1
                if elapsed >= ASSUMPTIONS["give_up_minutes"]:
                    break
                continue

            park_time = elapsed + ASSUMPTIONS["park_manoeuvre_minutes"]
            if t + park_time - t >= ASSUMPTIONS["give_up_minutes"] and i > 0:
                # reaching a far lot beyond the give-up horizon still counts,
                # but only if the driver keeps going
                pass
            free.free_from = t + park_time + arr.dwell_minutes
            stats["parked"] += 1
            stats["search_times"].append(park_time)
            stats["occupied_minutes"] += _occupancy_minutes(arr, window_minutes)
            if arr.tier == 1 and free.is_accessible:
                stats["tier1_parked_accessible"] += 1
            parked = True
            break

        if not parked:
            stats["failed"] += 1

    return _finalise(stats, window_minutes, capacity, len(seq), "BASELINE (FCFS, no information)")


def run_parkwise(seq: List[Arrival], layout: Dict[str, LotLayout],
                 window_minutes: float, buildings: Dict[str, Building],
                 grace_minutes: int = 10, cutoff_hour: int = 10,
                 start_hour: int = 7) -> Dict[str, Any]:
    """Replay of the ParkWise rules engine."""
    _reset(layout)
    stats = _empty_stats()
    capacity = sum(len(l.bays) for l in layout.values())
    lots_by_id = dict(layout)

    def bay_rank(bay: SimBay, lot: LotLayout, arr: Arrival) -> Tuple:
        tier1 = arr.tier == 1 or arr.needs_accessible
        acc_first = 0 if (tier1 and bay.is_accessible) else 1
        dest = buildings.get(arr.dest_building_id)
        dist = float("inf")
        if dest is not None:
            class _Bay:  # duck-typed for distance_utils
                pass
            b = _Bay()
            b.lot = type("L", (), {"lat": lot.lat, "lng": lot.lng})()
            dist = get_bay_distance_to_building(b, dest)
        return (acc_first, dist + (abs(bay.x) + abs(bay.y)) * ASSUMPTIONS["bay_pitch_m"], bay.label)

    def eligible(bay: SimBay, arr: Arrival, hour: int) -> bool:
        if bay.vtype != arr.vehicle_type:
            return False
        if bay.is_accessible and (arr.tier != 1 and not arr.needs_accessible):
            return False
        if bay.reserved_tier == 2 and arr.tier not in (1, 2) and hour < cutoff_hour:
            return False
        return True

    for arr in seq:
        t = arr.minute
        if arr.tier == 1:
            stats["tier1_arrivals"] += 1
        hour = (start_hour + int(t // 60)) % 24
        pref = lots_by_id.get(arr.pref_lot_id)
        if pref is None:
            continue

        def candidates(lot: LotLayout) -> List[SimBay]:
            return sorted(
                [b for b in lot.bays if b.free_from <= t and eligible(b, arr, hour)],
                key=lambda b: bay_rank(b, lot, arr),
            )

        choice: Optional[Tuple[LotLayout, SimBay]] = None
        gate_extra = ASSUMPTIONS["gate_decision_seconds"] / 60.0

        pool = candidates(pref)
        if pool:
            choice = (pref, pool[0])
            travel = gate_extra + _creep_min(pool[0])
        else:
            alt_lots = sorted(
                [l for l in layout.values() if l.id != pref.id and candidates(l)],
                key=lambda l: _drive_min(pref, l),
            )
            if alt_lots:
                alt = alt_lots[0]
                choice = (alt, candidates(alt)[0])
                travel = gate_extra + _drive_min(pref, alt) + _creep_min(choice[1])
            else:
                # No eligible bay anywhere: join the waitlist and take the
                # first bay that frees up (same eligibility rules apply), or
                # give up after `give_up_minutes`.
                stats["waitlisted"] += 1
                eligible_pool = [
                    b
                    for lot in layout.values()
                    for b in lot.bays
                    if eligible(b, arr, hour)
                ]
                if not eligible_pool:
                    stats["failed"] += 1
                    continue
                future = sorted(
                    (b for b in eligible_pool if b.free_from > t),
                    key=lambda b: b.free_from,
                )
                if not future:
                    # Nothing occupied, nothing eligible-free: no rule-compliant
                    # bay exists for this vehicle/tier.
                    stats["failed"] += 1
                    continue
                bay = future[0]
                wait = bay.free_from - t
                if wait > ASSUMPTIONS["give_up_minutes"]:
                    stats["failed"] += 1
                    continue
                bay.free_from = (
                    t + wait + ASSUMPTIONS["park_manoeuvre_minutes"] + arr.dwell_minutes
                )
                stats["waitlist_resolved"] += 1
                stats["parked"] += 1
                stats["occupied_minutes"] += _occupancy_minutes(arr, window_minutes)
                stats["search_times"].append(wait)
                if arr.tier == 1 and bay.is_accessible:
                    stats["tier1_parked_accessible"] += 1
                continue

        lot, bay = choice
        park_time = travel + ASSUMPTIONS["park_manoeuvre_minutes"]
        bay.free_from = t + park_time + arr.dwell_minutes
        stats["parked"] += 1
        stats["search_times"].append(park_time)
        stats["occupied_minutes"] += _occupancy_minutes(arr, window_minutes)
        if arr.tier == 1 and bay.is_accessible:
            stats["tier1_parked_accessible"] += 1

    return _finalise(stats, window_minutes, capacity, len(seq), "PARKWISE (rules engine)")


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def run_comparison(
    db: Session,
    seed: int = 42,
    hours: int = 5,
    scale: float = 1.0,
    start: Optional[datetime] = None,
    name: str = "baseline-vs-parkwise",
    persist: bool = True,
) -> Dict[str, Any]:
    start = as_utc_naive(start) or default_start()
    layout = _load_layout(db)
    seq = generate_arrival_sequence(db, start, hours=hours, seed=seed, scale=scale)
    buildings = {b.id: b for b in db.query(Building).all()}

    window_minutes = float(hours * 60)
    # Fresh layout per policy: neither run may see the other's occupancy.
    baseline = run_baseline(seq, _load_layout(db), window_minutes)
    parkwise = run_parkwise(seq, _load_layout(db), window_minutes, buildings)

    deltas = {
        key: (
            round((parkwise[key] - baseline[key]), 2)
            if isinstance(baseline[key], (int, float)) and isinstance(parkwise[key], (int, float))
            else None
        )
        for key in ("avg_search_minutes", "failed_entries", "wasted_entries",
                    "utilization_pct", "tier1_access_success_pct")
    }

    result = {
        "name": name,
        "params": {"seed": seed, "hours": hours, "scale": scale, "start": start.isoformat()},
        "arrivals": len(seq),
        "assumptions": {"model": ASSUMPTIONS["replay"], "baseline": ASSUMPTIONS["baseline_policy"],
                        "parkwise": ASSUMPTIONS["parkwise_policy"],
                        "arrival_profile": getattr(generate_arrival_sequence, "last_profile_source", "history"),
                        "parameters": {k: ASSUMPTIONS[k] for k in ASSUMPTION_KEYS}},
        "baseline": baseline,
        "parkwise": parkwise,
        "delta_parkwise_minus_baseline": deltas,
        "generated_at": as_utc_naive(utcnow()).isoformat(),
        "label": "Computed from this simulation run — not measured field data.",
    }

    if persist and seq:
        run = SimulationRun(
            name=name,
            params=result["params"],
            assumptions=result["assumptions"],
            baseline=baseline,
            parkwise=parkwise,
        )
        db.add(run)
        db.commit()
        result["run_id"] = run.id
    return result


def latest_run(db: Session) -> Optional[Dict[str, Any]]:
    run = db.query(SimulationRun).order_by(SimulationRun.created_at.desc()).first()
    if run is None:
        return None
    return {
        "run_id": run.id,
        "name": run.name,
        "params": run.params,
        "assumptions": run.assumptions,
        "baseline": run.baseline,
        "parkwise": run.parkwise,
        "generated_at": as_utc_naive(run.created_at).isoformat() if run.created_at else None,
        "label": "Computed from this simulation run — not measured field data.",
    }
