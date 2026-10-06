import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.models import Base, Lot, Bay, BayState, Allotment, AllotmentStatus, Vehicle, VehicleType, User
from app.services.prediction_service import get_historical_hourly_arrivals, predict_lot_fill_time, predict_all_lots

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

def setup_prediction_data(db):
    lot = Lot(id="lot-1", name="Lot A", capacity=10, lat=10.0, lng=10.0)
    user = User(id="u1", name="U1", email="u1@test.com", password_hash="hash", priority_tier=3)
    veh = Vehicle(id="v1", user_id="u1", plate_or_tag_id="KA-01-1111", type=VehicleType.four_wheeler)
    db.add_all([lot, user, veh])
    
    # 10 bays
    bays = []
    for i in range(10):
        b = Bay(id=f"bay-{i}", lot_id="lot-1", label=f"A-{i+1:02d}", type=VehicleType.four_wheeler, state=BayState.free, x=i, y=0)
        bays.append(b)
    db.add_all(bays)
    db.commit()

    # Add historical arrivals on Mondays (weekday 0)
    # Day 1 Monday: 4 arrivals between 8:00 and 9:00
    # Day 2 Monday: 6 arrivals between 8:00 and 9:00 -> avg 5 arrivals/hour at 8am
    mon1 = datetime(2023, 1, 2, 8, 15, 0) # Monday
    mon2 = datetime(2023, 1, 9, 8, 20, 0) # Monday
    
    hist_allotments = [
        Allotment(vehicle_id="v1", bay_id="bay-0", status=AllotmentStatus.completed, arrived_at=datetime(2023, 1, 2, 8, 10)),
        Allotment(vehicle_id="v1", bay_id="bay-1", status=AllotmentStatus.completed, arrived_at=datetime(2023, 1, 2, 8, 20)),
        Allotment(vehicle_id="v1", bay_id="bay-2", status=AllotmentStatus.completed, arrived_at=datetime(2023, 1, 2, 8, 30)),
        Allotment(vehicle_id="v1", bay_id="bay-3", status=AllotmentStatus.completed, arrived_at=datetime(2023, 1, 2, 8, 40)),
        
        Allotment(vehicle_id="v1", bay_id="bay-0", status=AllotmentStatus.completed, arrived_at=datetime(2023, 1, 9, 8, 5)),
        Allotment(vehicle_id="v1", bay_id="bay-1", status=AllotmentStatus.completed, arrived_at=datetime(2023, 1, 9, 8, 15)),
        Allotment(vehicle_id="v1", bay_id="bay-2", status=AllotmentStatus.completed, arrived_at=datetime(2023, 1, 9, 8, 25)),
        Allotment(vehicle_id="v1", bay_id="bay-3", status=AllotmentStatus.completed, arrived_at=datetime(2023, 1, 9, 8, 35)),
        Allotment(vehicle_id="v1", bay_id="bay-4", status=AllotmentStatus.completed, arrived_at=datetime(2023, 1, 9, 8, 45)),
        Allotment(vehicle_id="v1", bay_id="bay-5", status=AllotmentStatus.completed, arrived_at=datetime(2023, 1, 9, 8, 55)),
    ]
    db.add_all(hist_allotments)
    db.commit()

def test_hourly_arrival_profile_computation(db_session):
    setup_prediction_data(db_session)
    # Check Monday (weekday 0)
    profile = get_historical_hourly_arrivals(db_session, "lot-1", day_of_week=0)
    # (4 + 6) / 2 = 5.0 average arrivals at 8am
    assert profile[8] == 5.0
    # Other hours should be 0.0
    assert profile[12] == 0.0

def test_prediction_when_lot_is_full(db_session):
    setup_prediction_data(db_session)
    # Fill all 10 bays
    bays = db_session.query(Bay).all()
    for b in bays:
        b.state = BayState.occupied
    db_session.commit()
    
    current_time = datetime(2023, 1, 16, 8, 30, 0)
    result = predict_lot_fill_time(db_session, "lot-1", current_time=current_time)
    assert result["is_full_now"] == True
    assert result["current_occupancy"] == 10
    assert result["minutes_until_full"] == 0
    assert "FULL" in result["warning_message"]
    assert result["confidence"] == "high"

def test_prediction_dynamic_fill_time_calculation(db_session):
    setup_prediction_data(db_session)
    # Lot capacity 10. Occupy 5 bays. 5 bays remaining.
    bays = db_session.query(Bay).all()
    for b in bays[:5]:
        b.state = BayState.occupied
    db_session.commit()
    
    # Current time: Monday at 08:00 AM.
    # From history, 8am has 5 arrivals/hour (0.0833 arrivals/min).
    # Remaining 5 bays will fill in exactly ~60 minutes, so predicted fill time should be 09:00.
    current_time = datetime(2023, 1, 16, 8, 0, 0) # Monday
    result = predict_lot_fill_time(db_session, "lot-1", current_time=current_time)
    
    assert result["is_full_now"] == False
    assert result["current_occupancy"] == 5
    assert result["capacity"] == 10
    assert result["predicted_fill_time"] == "09:00"
    assert result["minutes_until_full"] == 60
    assert result["confidence"] == "high"
    assert "heuristic_label" in result
    assert "Statistical Heuristic" in result["heuristic_label"]
    assert "likely full by 09:00" in result["warning_message"]

def test_predict_all_lots(db_session):
    setup_prediction_data(db_session)
    predictions = predict_all_lots(db_session)
    assert len(predictions) == 1
    assert predictions[0]["lot_id"] == "lot-1"
