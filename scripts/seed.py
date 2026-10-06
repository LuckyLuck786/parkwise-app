"""
ParkWise — Idempotent seed script.

Run:  python -m scripts.seed   (from parkwise/)
  or: python scripts/seed.py
"""
import sys
import os
import random
import json
from datetime import datetime, timedelta, timezone

# Ensure we can import from backend
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from app.db.database import SessionLocal, create_tables
from app.db.models import (
    User, Vehicle, Building, Lot, Bay, Rule, Device, Allotment, ScanEvent,
    UserRole, VehicleType, BayState, AllotmentStatus, ScanDirection, EventSource,
    DeviceKind, DeviceStatus,
)
from app.core.security import get_password_hash


def get_or_create(session, model, defaults=None, **kwargs):
    """Query by kwargs; create with defaults merged in if not found."""
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance, False
    params = {**kwargs, **(defaults or {})}
    instance = model(**params)
    session.add(instance)
    session.flush()
    return instance, True


def _generate_plate(prefix: str = "KA-03") -> str:
    letters = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=2))
    numbers = ''.join(random.choices("0123456789", k=4))
    return f"{prefix}-{letters}-{numbers}"


_FIRST_NAMES = [
    "Amit", "Rohit", "Sneha", "Kiran", "Aditya", "Neha", "Pooja",
    "Vikram", "Siddharth", "Anjali", "Rakesh", "Sunil", "Manish",
    "Divya", "Swati", "Arjun", "Nisha",
]
_LAST_NAMES = [
    "Sharma", "Verma", "Reddy", "Patil", "Desai", "Joshi", "Kulkarni",
    "Singh", "Yadav", "Gupta", "Kumar", "Choudhary",
]


def _random_name() -> str:
    return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"


# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------

BUILDINGS = [
    {"name": "Engineering",    "lat": 12.9716, "lng": 77.5946},
    {"name": "Science",        "lat": 12.9720, "lng": 77.5950},
    {"name": "Library",        "lat": 12.9718, "lng": 77.5942},
    {"name": "Admin Block",    "lat": 12.9714, "lng": 77.5948},
    {"name": "Medical Center", "lat": 12.9722, "lng": 77.5944},
]

LOTS = [
    {"name": "Lot A", "capacity": 24, "lat": 12.9717, "lng": 77.5947},
    {"name": "Lot B", "capacity": 20, "lat": 12.9715, "lng": 77.5943},
    {"name": "Lot C", "capacity": 18, "lat": 12.9721, "lng": 77.5945},
]

NAMED_USERS = [
    # Tier 1 — disabilities/medical
    {"email": "priya.sharma@example.com", "name": "Priya Sharma",
     "role": UserRole.driver, "priority_tier": 1, "needs_accessible": True,
     "vehicles": [("KA-01-AB-1234", VehicleType.four_wheeler),
                  ("KA-01-AB-1235", VehicleType.two_wheeler)]},
    {"email": "ravi.kumar@example.com", "name": "Ravi Kumar",
     "role": UserRole.driver, "priority_tier": 1, "needs_accessible": True,
     "vehicles": [("KA-01-CD-5678", VehicleType.four_wheeler)]},
    {"email": "meena.das@example.com", "name": "Meena Das",
     "role": UserRole.driver, "priority_tier": 1, "needs_accessible": True,
     "vehicles": [("KA-01-EF-9012", VehicleType.two_wheeler)]},
    # Tier 2 — faculty/staff/service
    {"email": "anand.rao@example.com", "name": "Dr. Anand Rao",
     "role": UserRole.driver, "priority_tier": 2, "needs_accessible": False,
     "vehicles": [("KA-02-GH-3456", VehicleType.four_wheeler),
                  ("KA-02-GH-3457", VehicleType.two_wheeler)]},
    {"email": "lakshmi.iyer@example.com", "name": "Prof. Lakshmi Iyer",
     "role": UserRole.driver, "priority_tier": 2, "needs_accessible": False,
     "vehicles": [("KA-02-IJ-7890", VehicleType.four_wheeler)]},
    {"email": "suresh.patel@example.com", "name": "Dr. Suresh Patel",
     "role": UserRole.driver, "priority_tier": 2, "needs_accessible": False,
     "vehicles": [("KA-02-KL-1234", VehicleType.four_wheeler)]},
    {"email": "deepa.nair@example.com", "name": "Officer Deepa Nair",
     "role": UserRole.driver, "priority_tier": 2, "needs_accessible": False,
     "vehicles": [("KA-02-MN-5678", VehicleType.four_wheeler)]},
    {"email": "kavitha.nurse@example.com", "name": "Nurse Kavitha",
     "role": UserRole.driver, "priority_tier": 2, "needs_accessible": False,
     "vehicles": [("KA-02-OP-9012", VehicleType.two_wheeler)]},
    # Admin & Gate
    {"email": "admin@parkwise.edu", "name": "Admin User",
     "role": UserRole.admin, "priority_tier": 3, "needs_accessible": False,
     "vehicles": [], "password": "admin123"},
    {"email": "gate1@parkwise.edu", "name": "Gate Operator 1",
     "role": UserRole.gate_operator, "priority_tier": 3, "needs_accessible": False,
     "vehicles": [], "password": "gate123"},
]

DEFAULT_RULES = [
    ("tier1_quota_pct",             {"value": 10},  "Percentage of bays reserved for Tier 1 (accessible)"),
    ("tier2_quota_pct",             {"value": 15},  "Percentage of bays reserved for Tier 2 until cutoff"),
    ("grace_period_minutes",        {"value": 10},  "Minutes to arrive after allotment before no-show release"),
    ("tier2_cutoff_hour",           {"value": 10},  "Hour (24h) after which Tier 2 reserved bays open to all"),
    ("waitlist_offer_minutes",      {"value": 5},   "Minutes to accept a waitlist offer before it expires"),
    ("prediction_warning_minutes",  {"value": 30},  "Minutes before predicted full to show warning"),
    ("heartbeat_timeout_seconds",   {"value": 120}, "Seconds without heartbeat before device marked offline"),
]


# ---------------------------------------------------------------------------
# Bay generation helpers
# ---------------------------------------------------------------------------

def _make_lot_a_bays(lot_id: str, buildings: dict) -> list[dict]:
    """Lot A: 24 bays, 6 rows × 4 cols."""
    bays = []
    for i in range(1, 25):
        label = f"A-{i:02d}"
        vtype = VehicleType.four_wheeler if i <= 14 else VehicleType.two_wheeler
        is_acc = i in (1, 2)
        res_tier = 2 if i == 3 else None
        row, col = divmod(i - 1, 4)
        nearest = buildings["Engineering"] if row < 3 else buildings["Science"]
        bays.append({
            "lot_id": lot_id, "label": label, "type": vtype,
            "is_accessible": is_acc, "reserved_tier": res_tier,
            "x": col, "y": row, "nearest_building_id": nearest.id,
            "state": BayState.free,
        })
    return bays


def _make_lot_b_bays(lot_id: str, buildings: dict) -> list[dict]:
    """Lot B: 20 bays, 5 rows × 4 cols."""
    bays = []
    for i in range(1, 21):
        label = f"B-{i:02d}"
        vtype = VehicleType.four_wheeler if i <= 12 else VehicleType.two_wheeler
        is_acc = i in (1, 13)
        res_tier = 2 if i == 2 else None
        row, col = divmod(i - 1, 4)
        nearest = buildings["Library"] if row < 2 else buildings["Admin Block"]
        bays.append({
            "lot_id": lot_id, "label": label, "type": vtype,
            "is_accessible": is_acc, "reserved_tier": res_tier,
            "x": col, "y": row, "nearest_building_id": nearest.id,
            "state": BayState.free,
        })
    return bays


def _make_lot_c_bays(lot_id: str, buildings: dict) -> list[dict]:
    """Lot C: 18 bays, 6 rows × 3 cols."""
    bays = []
    for i in range(1, 19):
        label = f"C-{i:02d}"
        vtype = VehicleType.four_wheeler if i <= 10 else VehicleType.two_wheeler
        is_acc = i in (1, 2)
        res_tier = 2 if i == 3 else None
        row, col = divmod(i - 1, 3)
        bays.append({
            "lot_id": lot_id, "label": label, "type": vtype,
            "is_accessible": is_acc, "reserved_tier": res_tier,
            "x": col, "y": row, "nearest_building_id": buildings["Medical Center"].id,
            "state": BayState.free,
        })
    return bays


# ---------------------------------------------------------------------------
# Historical data generation
# ---------------------------------------------------------------------------

def _generate_historical_data(session, vehicles: list[Vehicle], bays: list[Bay]):
    """Generate 14 days of realistic historical arrivals."""
    # Skip if we already have substantial history
    if session.query(Allotment).filter(
        Allotment.status == AllotmentStatus.completed
    ).count() >= 100:
        print("  Historical data already present — skipping.")
        return

    random.seed(42)
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    bays_by_type: dict[VehicleType, list[Bay]] = {
        VehicleType.four_wheeler: [b for b in bays if b.type == VehicleType.four_wheeler],
        VehicleType.two_wheeler:  [b for b in bays if b.type == VehicleType.two_wheeler],
    }

    driver_vehicles = [v for v in vehicles if v.user.role == UserRole.driver]
    if not driver_vehicles:
        print("  No driver vehicles to create history for.")
        return

    total_allotments = 0
    total_scans = 0

    for day_offset in range(14, 0, -1):
        current_date = today - timedelta(days=day_offset)
        is_weekend = current_date.weekday() >= 5
        num_arrivals = random.randint(15, 20) if is_weekend else random.randint(40, 50)
        daily_vehicles = random.sample(
            driver_vehicles, min(num_arrivals, len(driver_vehicles))
        )

        for v in daily_vehicles:
            # Arrival time with morning-rush weighting on weekdays
            if is_weekend:
                hour = random.randint(8, 18)
            else:
                hour = random.choices(
                    [7, 8, 9, 10, 11, 14, 15],
                    weights=[5, 40, 30, 10, 5, 5, 5], k=1
                )[0]
            minute = random.randint(0, 59)
            arrived_at = current_date.replace(hour=hour, minute=minute)
            duration = timedelta(hours=random.randint(2, 9))
            released_at = arrived_at + duration

            matching = bays_by_type.get(v.type, [])
            if not matching:
                continue
            bay = random.choice(matching)

            allotment = Allotment(
                vehicle_id=v.id,
                bay_id=bay.id,
                status=AllotmentStatus.completed,
                allotted_at=arrived_at - timedelta(minutes=random.randint(2, 10)),
                arrived_at=arrived_at,
                released_at=released_at,
                explanation={"rule": "historical_seed", "bay": bay.label},
            )
            session.add(allotment)
            total_allotments += 1

            # Corresponding scan events
            scan_in = ScanEvent(
                vehicle_id=v.id,
                direction=ScanDirection.in_scan,
                source=EventSource.simulator,
                ts=arrived_at,
            )
            scan_out = ScanEvent(
                vehicle_id=v.id,
                direction=ScanDirection.out_scan,
                source=EventSource.simulator,
                ts=released_at,
            )
            session.add(scan_in)
            session.add(scan_out)
            total_scans += 2

    session.flush()
    print(f"  Created {total_allotments} historical allotments, {total_scans} scan events.")


# ---------------------------------------------------------------------------
# Main seed function
# ---------------------------------------------------------------------------

def seed():
    create_tables()
    session = SessionLocal()
    try:
        print("=== ParkWise Seed ===")

        # ── Buildings ─────────────────────────────────────────────
        print("Seeding buildings …")
        buildings: dict[str, Building] = {}
        for bd in BUILDINGS:
            b, created = get_or_create(session, Building, name=bd["name"],
                                       defaults={"lat": bd["lat"], "lng": bd["lng"]})
            buildings[b.name] = b
            if created:
                print(f"  + {b.name}")

        # ── Lots ──────────────────────────────────────────────────
        print("Seeding lots …")
        lots: dict[str, Lot] = {}
        for ld in LOTS:
            lot, created = get_or_create(session, Lot, name=ld["name"],
                                         defaults={"capacity": ld["capacity"],
                                                    "lat": ld["lat"], "lng": ld["lng"]})
            lots[lot.name] = lot
            if created:
                print(f"  + {lot.name} ({lot.capacity} bays)")

        # ── Bays ──────────────────────────────────────────────────
        print("Seeding bays …")
        all_bay_defs = (
            _make_lot_a_bays(lots["Lot A"].id, buildings)
            + _make_lot_b_bays(lots["Lot B"].id, buildings)
            + _make_lot_c_bays(lots["Lot C"].id, buildings)
        )
        bay_count = 0
        for bd in all_bay_defs:
            _, created = get_or_create(
                session, Bay,
                lot_id=bd["lot_id"], label=bd["label"],
                defaults={k: v for k, v in bd.items() if k not in ("lot_id", "label")},
            )
            if created:
                bay_count += 1
        print(f"  {bay_count} bays created ({62 - bay_count} already existed)")

        # ── Users & Vehicles ──────────────────────────────────────
        print("Seeding users & vehicles …")
        driver_pass_hash = get_password_hash("pass123")

        random.seed(42)  # deterministic Tier-3 generation

        # Build full user list (named + generated Tier-3)
        all_user_defs = list(NAMED_USERS)
        used_emails: set[str] = {u["email"] for u in NAMED_USERS}
        used_plates: set[str] = set()
        for u in NAMED_USERS:
            for plate, _ in u["vehicles"]:
                used_plates.add(plate)

        for _ in range(17):  # Tier 3 drivers
            name = _random_name()
            email = f"{name.lower().replace(' ', '.')}@example.com"
            while email in used_emails:
                name = _random_name()
                email = f"{name.lower().replace(' ', '.')}@example.com"
            used_emails.add(email)

            veh_list: list[tuple[str, VehicleType]] = []
            num_v = random.choice([1, 2])
            for _ in range(num_v):
                plate = _generate_plate()
                while plate in used_plates:
                    plate = _generate_plate()
                used_plates.add(plate)
                vtype = random.choice([VehicleType.four_wheeler, VehicleType.two_wheeler])
                veh_list.append((plate, vtype))

            all_user_defs.append({
                "email": email, "name": name,
                "role": UserRole.driver, "priority_tier": 3,
                "needs_accessible": False, "vehicles": veh_list,
            })

        all_vehicles: list[Vehicle] = []
        for ud in all_user_defs:
            pw = ud.get("password", "pass123")
            pw_hash = get_password_hash(pw) if pw != "pass123" else driver_pass_hash

            user, created = get_or_create(
                session, User, email=ud["email"],
                defaults={
                    "name": ud["name"],
                    "password_hash": pw_hash,
                    "role": ud["role"],
                    "priority_tier": ud["priority_tier"],
                    "needs_accessible": ud["needs_accessible"],
                },
            )
            if created:
                print(f"  + user: {user.name} ({user.email})")

            for plate, vtype in ud["vehicles"]:
                veh, v_created = get_or_create(
                    session, Vehicle, plate_or_tag_id=plate,
                    defaults={
                        "user_id": user.id,
                        "type": vtype,
                        "active_today": False,
                    },
                )
                all_vehicles.append(veh)
                if v_created:
                    print(f"    + vehicle: {plate} ({vtype.value})")

        # ── Rules ─────────────────────────────────────────────────
        print("Seeding rules …")
        for key, value, desc in DEFAULT_RULES:
            _, created = get_or_create(session, Rule, key=key,
                                       defaults={"value": value, "description": desc})
            if created:
                print(f"  + {key}")

        # ── Devices ───────────────────────────────────────────────
        print("Seeding devices …")
        devices_data = [
            ("simulator-lot-a", DeviceKind.gate_scanner, "sim-key-lot-a"),
            ("simulator-lot-b", DeviceKind.gate_scanner, "sim-key-lot-b"),
            ("simulator-lot-c", DeviceKind.gate_scanner, "sim-key-lot-c"),
        ]
        for dname, dkind, api_key in devices_data:
            _, created = get_or_create(
                session, Device, name=dname,
                defaults={
                    "kind": dkind,
                    "api_key_hash": get_password_hash(api_key),
                    "status": DeviceStatus.online,
                },
            )
            if created:
                print(f"  + device: {dname}")

        # ── Historical data ───────────────────────────────────────
        print("Seeding historical arrivals …")
        all_bays = session.query(Bay).all()
        _generate_historical_data(session, all_vehicles, all_bays)

        session.commit()
        print("\n✓ Seed completed successfully!")

        # Summary
        print(f"  Users:       {session.query(User).count()}")
        print(f"  Vehicles:    {session.query(Vehicle).count()}")
        print(f"  Buildings:   {session.query(Building).count()}")
        print(f"  Lots:        {session.query(Lot).count()}")
        print(f"  Bays:        {session.query(Bay).count()}")
        print(f"  Rules:       {session.query(Rule).count()}")
        print(f"  Devices:     {session.query(Device).count()}")
        print(f"  Allotments:  {session.query(Allotment).count()}")
        print(f"  Scan events: {session.query(ScanEvent).count()}")

    except Exception as e:
        session.rollback()
        print(f"\n✗ Seed failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed()
