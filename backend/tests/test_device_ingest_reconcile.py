import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.database import get_db, Base
from app.db.models import (
    Device, DeviceKind, DeviceStatus, Lot, Bay, BayState, Vehicle,
    VehicleType, User, Allotment, AllotmentStatus, ScanDirection, EventSource,
    BayEvent, utcnow
)
from app.core.security import get_password_hash
from app.adapters.simulator import SimulatorAdapter
from app.services.reconcile_service import check_device_heartbeats

@pytest.fixture
def test_setup():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()
            
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    
    db = TestingSessionLocal()
    # Seed device with known API key
    device = Device(
        id="dev-1",
        name="test-gate-scanner",
        kind=DeviceKind.gate_scanner,
        api_key_hash=get_password_hash("secret-key-123"),
        status=DeviceStatus.online
    )
    user = User(id="u1", name="Test User", email="user@test.com", password_hash="hash", priority_tier=3)
    vehicle = Vehicle(id="v1", user_id="u1", plate_or_tag_id="KA-05-TEST-9999", type=VehicleType.four_wheeler)
    lot = Lot(id="lot-1", name="Lot A", capacity=2, lat=12.0, lng=77.0)
    bay1 = Bay(id="bay-1", lot_id="lot-1", label="A-01", type=VehicleType.four_wheeler, state=BayState.free, x=0, y=0)
    bay2 = Bay(id="bay-2", lot_id="lot-1", label="A-02", type=VehicleType.four_wheeler, state=BayState.free, x=1, y=0)
    
    db.add_all([device, user, vehicle, lot, bay1, bay2])
    db.commit()
    
    yield {"client": client, "db": db, "api_key": "secret-key-123"}
    
    app.dependency_overrides.clear()
    db.close()

def test_device_auth_required(test_setup):
    client = test_setup["client"]
    # Missing header
    res = client.post("/api/v1/ingest/heartbeat", json={"device_id": "dev-1"})
    assert res.status_code == 401
    
    # Wrong key
    res = client.post(
        "/api/v1/ingest/heartbeat",
        json={"device_id": "dev-1"},
        headers={"X-API-Key": "wrong-key"}
    )
    assert res.status_code == 403

def test_heartbeat_ingest(test_setup):
    client = test_setup["client"]
    api_key = test_setup["api_key"]
    db = test_setup["db"]
    
    res = client.post(
        "/api/v1/ingest/heartbeat",
        json={"device_id": "dev-1", "status": "online"},
        headers={"X-API-Key": api_key}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "online"

def test_gate_scan_in_and_out(test_setup):
    client = test_setup["client"]
    api_key = test_setup["api_key"]
    db = test_setup["db"]
    
    # 1. Scan In
    res = client.post(
        "/api/v1/ingest/gate-scan",
        json={
            "vehicle_tag_id": "KA-05-TEST-9999",
            "direction": "in_scan",
            "lot_preference_id": "lot-1"
        },
        headers={"X-API-Key": api_key}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] == True
    assert body["allocation_result"] is not None
    assert body["allocation_result"]["status"] == "allotted"
    bay_id = body["allocation_result"]["bay"]["id"]
    
    # Verify bay is now allotted
    bay = db.query(Bay).filter_by(id=bay_id).first()
    assert bay.state == BayState.allotted
    
    # 2. Scan Out
    res_out = client.post(
        "/api/v1/ingest/gate-scan",
        json={
            "vehicle_tag_id": "KA-05-TEST-9999",
            "direction": "out_scan"
        },
        headers={"X-API-Key": api_key}
    )
    assert res_out.status_code == 200
    db.refresh(bay)
    assert bay.state == BayState.free

def test_bay_event_arrival_and_departure(test_setup):
    client = test_setup["client"]
    api_key = test_setup["api_key"]
    db = test_setup["db"]
    
    # Create an active allotment for bay-1
    allotment = Allotment(
        vehicle_id="v1",
        bay_id="bay-1",
        status=AllotmentStatus.allotted,
        allotted_at=utcnow(),
    )
    bay1 = db.query(Bay).filter_by(id="bay-1").first()
    bay1.state = BayState.allotted
    db.add(allotment)
    db.commit()
    
    # Send bay event: occupied=True (Vehicle arrived at bay)
    res = client.post(
        "/api/v1/ingest/bay-event",
        json={"bay_id": "bay-1", "occupied": True, "source": "simulator"},
        headers={"X-API-Key": api_key}
    )
    assert res.status_code == 200
    db.refresh(bay1)
    db.refresh(allotment)
    assert bay1.state == BayState.occupied
    assert allotment.status == AllotmentStatus.occupied
    
    # Send bay event: occupied=False (Vehicle departed bay)
    res_dep = client.post(
        "/api/v1/ingest/bay-event",
        json={"bay_id": "bay-1", "occupied": False, "source": "simulator"},
        headers={"X-API-Key": api_key}
    )
    assert res_dep.status_code == 200
    db.refresh(bay1)
    db.refresh(allotment)
    assert bay1.state == BayState.free
    assert allotment.status == AllotmentStatus.completed

def test_reconcile_unauthorized_occupancy(test_setup):
    client = test_setup["client"]
    api_key = test_setup["api_key"]
    
    # Bay-2 is currently free in DB. Send physical occupancy event without gate scan!
    res = client.post(
        "/api/v1/ingest/bay-event",
        json={"bay_id": "bay-2", "occupied": True, "source": "ir_sensor"},
        headers={"X-API-Key": api_key}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["conflict_detected"] == True
    assert body["conflict_details"]["conflict_type"] == "unauthorized_occupancy"
    assert "without an active gate allotment" in body["conflict_details"]["message"]

def test_simulator_adapter_normalization():
    adapter = SimulatorAdapter()
    
    norm_bay = adapter.normalize_bay_event({
        "bay_id": "bay-10",
        "occupied": True,
        "confidence": 0.95
    })
    assert norm_bay["bay_id"] == "bay-10"
    assert norm_bay["occupied"] == True
    assert norm_bay["source"] == EventSource.simulator
    assert norm_bay["confidence"] == 0.95
    
    norm_gate = adapter.normalize_gate_scan({
        "vehicle_tag_id": "KA-01-1234",
        "direction": "in"
    })
    assert norm_gate["vehicle_tag_id"] == "KA-01-1234"
    assert norm_gate["direction"] == ScanDirection.in_scan
    assert norm_gate["source"] == EventSource.simulator

def test_device_offline_detection(test_setup):
    db = test_setup["db"]
    dev = db.query(Device).filter_by(id="dev-1").first()
    # Set last heartbeat 5 minutes ago in UTC
    dev.last_heartbeat = utcnow() - timedelta(minutes=5)
    db.commit()
    
    offline_alerts = check_device_heartbeats(db, timeout_seconds=120)
    assert len(offline_alerts) == 1
    assert offline_alerts[0]["device_id"] == "dev-1"
    assert offline_alerts[0]["status"] == "offline"
    
    db.refresh(dev)
    assert dev.status == DeviceStatus.offline


def test_conflict_wrong_bay_parking(test_setup):
    """Vehicle scanned into bay-1 but the sensor sees a car in bay-2."""
    client = test_setup["client"]
    api_key = test_setup["api_key"]
    db = test_setup["db"]

    allotment = Allotment(
        vehicle_id="v1",
        bay_id="bay-1",
        status=AllotmentStatus.allotted,
        allotted_at=utcnow(),
    )
    bay1 = db.query(Bay).filter_by(id="bay-1").first()
    bay1.state = BayState.allotted
    db.add(allotment)
    db.commit()

    res = client.post(
        "/api/v1/ingest/bay-event",
        json={"bay_id": "bay-2", "occupied": True, "source": "ir_sensor", "confidence": 0.8},
        headers={"X-API-Key": api_key},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["conflict_detected"] is True
    assert body["conflict_details"]["conflict_type"] == "wrong_bay_parking"
    assert "KA-05-TEST-9999" in body["conflict_details"]["suspected_vehicles"]
    assert "No automatic penalty" in body["conflict_details"]["recommended_action"]


def test_conflict_occupied_bay_not_exited(test_setup):
    """System still thinks the bay is occupied; the sensor says it is empty."""
    client = test_setup["client"]
    api_key = test_setup["api_key"]
    db = test_setup["db"]

    bay2 = db.query(Bay).filter_by(id="bay-2").first()
    bay2.state = BayState.occupied
    db.commit()

    res = client.post(
        "/api/v1/ingest/bay-event",
        json={"bay_id": "bay-2", "occupied": False, "source": "ir_sensor"},
        headers={"X-API-Key": api_key},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["conflict_details"]["conflict_type"] == "occupied_bay_not_exited"
    db.refresh(bay2)
    assert bay2.state == BayState.free


def test_no_show_release_via_sensor_and_waitlist_offer(test_setup):
    """Allotted bay never occupied past grace -> release + notify."""
    from app.db.models import Waitlist, WaitlistStatus, Notification

    client = test_setup["client"]
    api_key = test_setup["api_key"]
    db = test_setup["db"]

    allotment = Allotment(
        vehicle_id="v1",
        bay_id="bay-1",
        status=AllotmentStatus.allotted,
        allotted_at=utcnow() - timedelta(minutes=30),
    )
    bay1 = db.query(Bay).filter_by(id="bay-1").first()
    bay1.state = BayState.allotted
    db.add(allotment)
    # a second driver waiting for a bay
    db.add(User(id="u2", name="Waiting", email="w@test.com", password_hash="h", priority_tier=3))
    db.add(Vehicle(id="v2", user_id="u2", plate_or_tag_id="KA-05-WAIT-0001", type=VehicleType.four_wheeler))
    db.add(Waitlist(id="w1", vehicle_id="v2", status=WaitlistStatus.waiting))
    db.commit()

    res = client.post(
        "/api/v1/ingest/bay-event",
        json={"bay_id": "bay-1", "occupied": False, "source": "simulator"},
        headers={"X-API-Key": api_key},
    )
    assert res.status_code == 200
    assert res.json()["conflict_details"]["conflict_type"] == "no_show"

    db.refresh(allotment)
    db.refresh(bay1)
    assert allotment.status == AllotmentStatus.no_show_released
    assert allotment.explanation["release"]["reason"] == "no_show"
    assert bay1.state == BayState.allotted  # handed to the waitlist head

    note = db.query(Notification).filter(Notification.user_id == "u2").first()
    assert note is not None and "bay" in note.message.lower()


def test_low_confidence_badge_when_sensor_stale(test_setup):
    """Offline/stale sensors -> scan-inferred state with a low-confidence badge."""
    from app.services.reconcile_service import bay_confidence_map

    db = test_setup["db"]
    bay2 = db.query(Bay).filter_by(id="bay-2").first()
    bay2.state = BayState.occupied
    db.add(
        BayEvent(
            bay_id="bay-2",
            occupied=True,
            source=EventSource.ir_sensor,
            confidence=0.9,
            ts=utcnow() - timedelta(minutes=10),  # stale: > heartbeat window
        )
    )
    db.commit()

    cmap = bay_confidence_map(db, timeout_seconds=120)
    assert cmap["bay-2"]["state_source"] == "scan_inferred"
    assert cmap["bay-2"]["low_confidence"] is True
    # A fresh event keeps full confidence.
    db.add(
        BayEvent(
            bay_id="bay-2",
            occupied=True,
            source=EventSource.ir_sensor,
            confidence=0.95,
            ts=utcnow(),
        )
    )
    db.commit()
    cmap = bay_confidence_map(db, timeout_seconds=120)
    assert cmap["bay-2"]["state_source"] == "sensor"
    assert cmap["bay-2"]["low_confidence"] is False
