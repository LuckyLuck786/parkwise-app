"""Input-source toggle (demo-day failure plan): one admin switch pauses
hardware input without changing any ingestion code path."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.database import get_db, Base
from app.db.models import (
    AuditLog,
    Bay,
    BayState,
    Device,
    DeviceKind,
    DeviceStatus,
    Lot,
    User,
    UserRole,
    Vehicle,
    VehicleType,
)
from app.core.security import get_password_hash


@pytest.fixture
def api():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
    device = Device(
        id="dev-1",
        name="gate-scanner",
        kind=DeviceKind.gate_scanner,
        api_key_hash=get_password_hash("secret-key-123"),
        status=DeviceStatus.online,
    )
    lot = Lot(id="lot-1", name="Lot A", capacity=2, lat=12.0, lng=77.0)
    bay = Bay(
        id="bay-1", lot_id="lot-1", label="A-01", type=VehicleType.four_wheeler,
        state=BayState.free, x=0, y=0,
    )
    admin = User(id="u-admin", name="Admin", email="admin@test.io",
                 password_hash=get_password_hash("adminpw"), role=UserRole.admin)
    driver = User(id="u-driver", name="Driver", email="driver@test.io",
                  password_hash=get_password_hash("driverpw"), role=UserRole.driver,
                  priority_tier=3)
    vehicle = Vehicle(id="v1", user_id="u-driver", plate_or_tag_id="KA-01-TEST-0001",
                      type=VehicleType.four_wheeler)
    db.add_all([device, lot, bay, admin, driver, vehicle])
    db.commit()
    db.close()

    yield {"client": client, "api_key": "secret-key-123"}

    app.dependency_overrides.clear()


def _login(client, email, password):
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _bay_event(client, api_key, source, headers=None):
    return client.post(
        "/api/v1/ingest/bay-event",
        json={"bay_id": "bay-1", "occupied": True, "source": source, "confidence": 0.9},
        headers={"X-API-Key": api_key, **(headers or {})},
    )


def test_default_mode_is_live_and_get_requires_admin(api):
    client = api["client"]
    driver = _login(client, "driver@test.io", "driverpw")
    admin = _login(client, "admin@test.io", "adminpw")

    assert client.get("/api/v1/admin/input-source").status_code == 401
    assert client.get("/api/v1/admin/input-source", headers=driver).status_code == 403

    body = client.get("/api/v1/admin/input-source", headers=admin).json()
    assert body["mode"] == "live"
    assert body["hardware_sources_paused"] is False
    assert set(body["modes"]) == {"live", "simulated_only"}


def test_toggle_requires_admin(api):
    client = api["client"]
    driver = _login(client, "driver@test.io", "driverpw")
    assert client.post("/api/v1/admin/input-source",
                       json={"mode": "simulated_only"}, headers=driver).status_code == 403
    # invalid mode rejected by schema
    admin = _login(client, "admin@test.io", "adminpw")
    assert client.post("/api/v1/admin/input-source",
                       json={"mode": "everything"}, headers=admin).status_code == 422


def test_simulated_only_blocks_hardware_not_simulator(api):
    client = api["client"]
    api_key = api["api_key"]
    admin = _login(client, "admin@test.io", "adminpw")

    # live: hardware accepted
    assert _bay_event(client, api_key, "ir_sensor").status_code == 200

    res = client.post("/api/v1/admin/input-source",
                      json={"mode": "simulated_only"}, headers=admin)
    assert res.status_code == 200
    assert res.json()["hardware_sources_paused"] is True

    # hardware rejected with a clear 409
    for source in ("ir_sensor", "webcam"):
        res = _bay_event(client, api_key, source)
        assert res.status_code == 409, res.text
        assert "simulated_only" in res.json()["detail"]

    # gate scan from hardware also rejected
    res = client.post(
        "/api/v1/ingest/gate-scan",
        json={"vehicle_tag_id": "KA-01-TEST-0001", "direction": "in_scan",
              "source": "ir_sensor"},
        headers={"X-API-Key": api_key},
    )
    assert res.status_code == 409

    # simulator + manual still flow through the same endpoint
    assert _bay_event(client, api_key, "simulator").status_code == 200
    assert _bay_event(client, api_key, "manual").status_code == 200

    # hardware re-enabled -> accepted again
    res = client.post("/api/v1/admin/input-source",
                      json={"mode": "live"}, headers=admin)
    assert res.status_code == 200
    assert _bay_event(client, api_key, "ir_sensor").status_code == 200


def test_toggle_writes_audit_log(api):
    client = api["client"]
    admin = _login(client, "admin@test.io", "adminpw")
    client.post("/api/v1/admin/input-source", json={"mode": "simulated_only"},
                headers=admin)

    res = client.get("/api/v1/admin/audit?limit=10", headers=admin)
    assert res.status_code == 200
    actions = [row.get("action") for row in res.json()]
    assert "input_source_changed" in actions
