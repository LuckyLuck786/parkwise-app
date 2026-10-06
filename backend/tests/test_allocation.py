import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.models import Base, User, Vehicle, Lot, Building, Bay, Waitlist, Allotment, VehicleType, BayState, PriorityTier, AllotmentStatus
from app.services.allocation_service import allocate_bay
from app.services.waitlist_service import get_waitlist_queue
from app.services.noshow_service import check_and_release_noshows
from app.db.models import utcnow
import threading

@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    yield db
    db.close()

def setup_data(db):
    user1 = User(id="u1", name="U1", email="u1@test.com", password_hash="hash", priority_tier=1, needs_accessible=True)
    user2 = User(id="u2", name="U2", email="u2@test.com", password_hash="hash", priority_tier=3, needs_accessible=False)
    user3 = User(id="u3", name="U3", email="u3@test.com", password_hash="hash", priority_tier=2, needs_accessible=False)
    
    veh1 = Vehicle(id="v1", user_id="u1", plate_or_tag_id="PLATE1", type=VehicleType.four_wheeler)
    veh2 = Vehicle(id="v2", user_id="u2", plate_or_tag_id="PLATE2", type=VehicleType.four_wheeler)
    veh3 = Vehicle(id="v3", user_id="u3", plate_or_tag_id="PLATE3", type=VehicleType.four_wheeler)
    veh4_2w = Vehicle(id="v4", user_id="u2", plate_or_tag_id="PLATE4", type=VehicleType.two_wheeler)
    veh5 = Vehicle(id="v5", user_id="u1", plate_or_tag_id="PLATE5", type=VehicleType.four_wheeler)

    bldg1 = Building(id="b1", name="Engineering", lat=10.0, lng=10.0)
    
    lot1 = Lot(id="l1", name="Lot A", capacity=3, lat=10.1, lng=10.1)
    lot2 = Lot(id="l2", name="Lot B", capacity=2, lat=10.5, lng=10.5)
    
    # Lot 1 Bays
    bay1_acc = Bay(id="bay1", lot_id="l1", label="A1", type=VehicleType.four_wheeler, is_accessible=True, x=0, y=0)
    bay2_t2 = Bay(id="bay2", lot_id="l1", label="A2", type=VehicleType.four_wheeler, reserved_tier=2, x=0, y=0)
    bay3_2w = Bay(id="bay3", lot_id="l1", label="A3", type=VehicleType.two_wheeler, x=0, y=0)

    # Lot 2 Bays
    bay4 = Bay(id="bay4", lot_id="l2", label="B1", type=VehicleType.four_wheeler, x=0, y=0)
    
    db.add_all([user1, user2, user3, veh1, veh2, veh3, veh4_2w, veh5, bldg1, lot1, lot2, bay1_acc, bay2_t2, bay3_2w, bay4])
    db.commit()

def test_tier1_accessible_priority(db_session):
    setup_data(db_session)
    decision = allocate_bay(db_session, "PLATE1", destination_building_id="b1", lot_preference_id="l1")
    assert decision.success
    assert decision.bay["is_accessible"] == True

def test_tier2_quota_and_cutoff(db_session):
    setup_data(db_session)
    # user 2 is tier 3. bay2 is t2 reserved. lot A has only bay2 and bay1(acc).
    # We test before cutoff
    dt_before = datetime(2023, 1, 1, 9, 0, 0)
    decision = allocate_bay(db_session, "PLATE2", lot_preference_id="l1", current_time=dt_before)
    # Since bay2 is reserved, bay1 is accessible. Should fall to alt lot or waitlist
    assert decision.status in ["offered_alternative", "waitlisted"]
    
    # Release any allotment before testing second scenario
    allotment = db_session.query(Allotment).filter(
        Allotment.vehicle_id == "v2",
        Allotment.status.in_([AllotmentStatus.allotted, AllotmentStatus.occupied])
    ).first()
    if allotment:
        allotment.status = AllotmentStatus.completed
        if allotment.bay:
            allotment.bay.state = BayState.free
        db_session.commit()
    
    dt_after = datetime(2023, 1, 1, 11, 0, 0)
    decision_after = allocate_bay(db_session, "PLATE2", lot_preference_id="l1", current_time=dt_after)
    assert decision_after.success
    assert decision_after.bay["reserved_tier"] == 2

def test_wrong_vehicle_type_rejection(db_session):
    setup_data(db_session)
    # PLATE4 is 2W.
    # fill 2W bay
    bay3 = db_session.query(Bay).filter_by(id="bay3").first()
    bay3.state = BayState.allotted
    db_session.commit()
    
    decision = allocate_bay(db_session, "PLATE4", lot_preference_id="l1")
    # lot A has 4W bays left. should not get them
    assert not decision.success
    assert decision.status == "waitlisted"

def test_double_scan_rejection(db_session):
    setup_data(db_session)
    # Allocate to PLATE1
    allocate_bay(db_session, "PLATE1", lot_preference_id="l1")
    # Try PLATE5 (same user)
    decision = allocate_bay(db_session, "PLATE5")
    assert not decision.success
    assert decision.status == "rejected"
    assert "active allotment" in decision.message

def test_alternative_lot_offer(db_session):
    setup_data(db_session)
    # Make all Lot 1 4W bays occupied
    bay1 = db_session.query(Bay).filter_by(id="bay1").first()
    bay2 = db_session.query(Bay).filter_by(id="bay2").first()
    bay1.state = BayState.allotted
    bay2.state = BayState.allotted
    db_session.commit()
    
    decision = allocate_bay(db_session, "PLATE1", lot_preference_id="l1")
    assert decision.success
    assert decision.status == "offered_alternative"
    assert decision.bay["lot_name"] == "Lot B"
    assert decision.alternative_lot["name"] == "Lot B"
    
def test_waitlist_ordering(db_session):
    setup_data(db_session)
    bay1 = db_session.query(Bay).filter_by(id="bay1").first()
    bay2 = db_session.query(Bay).filter_by(id="bay2").first()
    bay4 = db_session.query(Bay).filter_by(id="bay4").first()
    bay1.state = BayState.allotted
    bay2.state = BayState.allotted
    bay4.state = BayState.allotted
    db_session.commit()
    
    allocate_bay(db_session, "PLATE2", lot_preference_id="l1") # Tier 3
    allocate_bay(db_session, "PLATE3", lot_preference_id="l1") # Tier 2
    allocate_bay(db_session, "PLATE1", lot_preference_id="l1") # Tier 1
    
    queue = get_waitlist_queue(db_session, "l1")
    # Order should be Tier 1, then Tier 2, then Tier 3
    assert queue[0].vehicle.user.priority_tier == 1
    assert queue[1].vehicle.user.priority_tier == 2
    assert queue[2].vehicle.user.priority_tier == 3

def test_noshow_release_and_waitlist_promotion(db_session):
    setup_data(db_session)
    bay1 = db_session.query(Bay).filter_by(id="bay1").first()
    bay2 = db_session.query(Bay).filter_by(id="bay2").first()
    bay4 = db_session.query(Bay).filter_by(id="bay4").first()
    bay1.state = BayState.allotted
    bay2.state = BayState.allotted
    bay4.state = BayState.allotted
    db_session.commit()
    
    # Waitlist PLATE1
    allocate_bay(db_session, "PLATE1", lot_preference_id="l1")
    
    # Now simulate a noshow on bay4
    dt = datetime(2023, 1, 1, 10, 0, 0)
    allotment = Allotment(
        vehicle_id="v2",
        bay_id="bay4",
        status=AllotmentStatus.allotted,
        allotted_at=datetime(2023, 1, 1, 9, 45, 0)
    )
    db_session.add(allotment)
    db_session.commit()
    
    released = check_and_release_noshows(db_session, current_time=dt)
    assert len(released) == 1
    
    # Verify waitlist promotion: bay4 (Lot B) freed -> promoted
    queue = get_waitlist_queue(db_session, "l2")
    assert len(queue) == 0  # Promoted
    
def test_concurrency_simultaneous_allocation():
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        engine = create_engine(f"sqlite:///{db_path}?timeout=30", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        SessionMaker = sessionmaker(bind=engine)
        db = SessionMaker()
        setup_data(db)
        
        bay1 = db.query(Bay).filter_by(id="bay1").first()
        bay3 = db.query(Bay).filter_by(id="bay3").first()
        bay4 = db.query(Bay).filter_by(id="bay4").first()
        bay1.state = BayState.allotted
        bay3.state = BayState.allotted
        bay4.state = BayState.allotted
        bay2 = db.query(Bay).filter_by(id="bay2").first()
        bay2.reserved_tier = None
        db.commit()
        db.close()
        
        results = []
        def run_allocate(plate):
            s = SessionMaker()
            try:
                d = allocate_bay(s, plate, lot_preference_id="l1")
                results.append(d)
            finally:
                s.close()
                
        t1 = threading.Thread(target=run_allocate, args=("PLATE1",))
        t2 = threading.Thread(target=run_allocate, args=("PLATE3",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        successes = [r for r in results if r.success]
        assert len(successes) == 1
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_explanation_is_complete(db_session):
    """Every decision must explain: rule applied, candidates considered,
    why this bay, and why others were rejected."""
    setup_data(db_session)
    # Nothing is occupied in Lot A: the accessible bay and the Tier-2-reserved
    # bay are both free but must be rejected for this Tier 3 four-wheeler
    # (before the cut-off), and the 2W bay fails the type check.

    dt_before = datetime(2023, 1, 1, 9, 0, 0)
    decision = allocate_bay(db_session, "PLATE2", destination_building_id="b1",
                            lot_preference_id="l1", current_time=dt_before)

    exp = decision.explanation
    assert exp["rule_applied"]
    assert exp["candidates_considered"] >= 1
    assert exp["rejections"], "rejections for considered bays must be listed"
    # bay2 is tier-2 reserved and bay1 is accessible -> both rejected with reasons
    joined = " ".join(exp["rejections"].keys())
    assert "tier2" in joined or "tier_2" in joined
    assert "accessible" in joined
    assert exp["rules_in_effect"]["tier2_cutoff_hour"] == 10
    assert decision.success, decision.message
    assert exp["chosen"]["bay"]
    assert exp["chosen"]["reason"]


def test_tier3_cannot_take_accessible_bay(db_session):
    """Accessible bays are a Tier-1 quota: Tier 3 must not take one while a
    regular bay exists, and must not take one at all when the rule says so."""
    setup_data(db_session)
    # Lot A: bay1 accessible (4W), bay2 tier2-reserved (4W), bay3 (2W)
    # Occupy bay2 so only the accessible 4W bay is free in Lot A.
    bay2 = db_session.query(Bay).filter_by(id="bay2").first()
    bay2.state = BayState.allotted
    db_session.commit()

    dt_before = datetime(2023, 1, 1, 9, 0, 0)
    decision = allocate_bay(db_session, "PLATE2", lot_preference_id="l1", current_time=dt_before)
    # Tier 3 must not get the accessible bay -> falls through to Lot B (bay4).
    assert decision.success
    assert decision.bay["is_accessible"] == False


def test_waitlist_position_is_tier_ordered(db_session):
    """Waitlist is ordered by tier then arrival time; positions are live."""
    setup_data(db_session)
    for bid in ("bay1", "bay2", "bay4"):
        db_session.query(Bay).filter_by(id=bid).first().state = BayState.allotted
    db_session.commit()

    d3 = allocate_bay(db_session, "PLATE2", lot_preference_id="l1")   # tier 3
    d2 = allocate_bay(db_session, "PLATE3", lot_preference_id="l1")   # tier 2
    d1 = allocate_bay(db_session, "PLATE1", lot_preference_id="l1")   # tier 1

    assert d3.status == d2.status == d1.status == "waitlisted"
    # Each decision reports its position at that moment ...
    assert d3.waitlist_position == 1        # alone in the queue
    assert d2.waitlist_position == 1        # tier 2 jumps ahead of tier 3
    assert d1.waitlist_position == 1        # tier 1 goes to the head
    # ... and the final queue is tier-ordered.
    queue = get_waitlist_queue(db_session)
    assert [w.vehicle.user.priority_tier for w in queue] == [1, 2, 3]
    assert [w.vehicle.plate_or_tag_id for w in queue] == ["PLATE1", "PLATE3", "PLATE2"]
