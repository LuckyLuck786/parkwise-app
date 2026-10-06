"""End-to-end API tests: auth, account CRUD, gate flow, full-lot + waitlist,
release, predictions, admin rules, metrics and the polling fallback."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.database import get_db, Base
from app.db.models import (
    Allotment,
    AllotmentStatus,
    Bay,
    BayState,
    Building,
    Lot,
    User,
    UserRole,
    Vehicle,
    VehicleType,
    Waitlist,
    WaitlistStatus,
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
    b1 = Building(id="b1", name="Engineering", lat=12.9716, lng=77.5946)
    lot_a = Lot(id="lot-a", name="Lot A", capacity=3, lat=12.9717, lng=77.5947)
    lot_b = Lot(id="lot-b", name="Lot B", capacity=2, lat=12.9715, lng=77.5943)
    bays = [
        Bay(id="a1", lot_id="lot-a", label="A-01", type=VehicleType.four_wheeler,
            is_accessible=True, x=0, y=0, nearest_building_id="b1"),
        Bay(id="a2", lot_id="lot-a", label="A-02", type=VehicleType.four_wheeler,
            reserved_tier=2, x=1, y=0, nearest_building_id="b1"),
        Bay(id="a3", lot_id="lot-a", label="A-03", type=VehicleType.four_wheeler,
            x=2, y=0, nearest_building_id="b1"),
        Bay(id="b1", lot_id="lot-b", label="B-01", type=VehicleType.four_wheeler,
            x=0, y=0),
        Bay(id="b2", lot_id="lot-b", label="B-02", type=VehicleType.four_wheeler,
            x=1, y=0),
    ]
    admin = User(id="u-admin", name="Admin", email="admin@test.io",
                 password_hash=get_password_hash("adminpw"), role=UserRole.admin)
    gate = User(id="u-gate", name="Gate", email="gate@test.io",
                password_hash=get_password_hash("gatepw"), role=UserRole.gate_operator)
    driver = User(id="u-driver", name="Driver", email="driver@test.io",
                  password_hash=get_password_hash("driverpw"), role=UserRole.driver,
                  priority_tier=3)
    other = User(id="u-other", name="Other", email="other@test.io",
                 password_hash=get_password_hash("otherpw"), role=UserRole.driver,
                 priority_tier=1, needs_accessible=True, destination_building_id="b1")
    db.add_all([b1, lot_a, lot_b, *bays, admin, gate, driver, other])
    db.commit()
    db.close()

    yield {"client": client, "sessions": TestingSessionLocal}

    app.dependency_overrides.clear()


def _login(client, email, password):
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    body = res.json()
    return {"Authorization": f"Bearer {body['access_token']}"}


def _register_vehicle(client, headers, plate, vtype="four_wheeler"):
    res = client.post("/api/v1/vehicles",
                      json={"plate_or_tag_id": plate, "type": vtype},
                      headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def test_register_login_and_auth_rejection(api):
    client = api["client"]
    res = client.post("/api/v1/auth/register", json={
        "name": "New Driver", "email": "new@driver.io", "password": "secret123",
    })
    assert res.status_code == 201
    token = res.json()["access_token"]
    assert res.json()["user"]["role"] == "driver"

    # no token
    assert client.get("/api/v1/me/status").status_code == 401
    # bad token
    assert client.get("/api/v1/me/status",
                      headers={"Authorization": "Bearer nope"}).status_code == 401
    # admin route with a driver token
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/admin/rules", headers=headers).status_code == 403
    # wrong password
    assert client.post("/api/v1/auth/login",
                       json={"email": "new@driver.io", "password": "wrong"}).status_code == 401
    # duplicate email
    assert client.post("/api/v1/auth/register", json={
        "name": "New Driver", "email": "new@driver.io", "password": "secret123",
    }).status_code == 409


def test_public_live_endpoints_need_no_auth(api):
    client = api["client"]
    assert client.get("/api/v1/lots").status_code == 200
    assert client.get("/api/v1/lots/lot-a/bays").status_code == 200
    assert client.get("/api/v1/predictions").status_code == 200
    assert client.get("/api/v1/buildings").status_code == 200
    assert client.get("/api/v1/events/poll?since=0").status_code == 200


# --------------------------------------------------------------------------- #
# Vehicles
# --------------------------------------------------------------------------- #
def test_vehicle_crud_and_limit(api):
    client = api["client"]
    headers = _login(client, "driver@test.io", "driverpw")

    v1 = _register_vehicle(client, headers, "KA-01-AA-1111")
    v2 = _register_vehicle(client, headers, "KA-01-AA-2222")
    _register_vehicle(client, headers, "KA-01-AA-3333")

    # 4th vehicle rejected
    res = client.post("/api/v1/vehicles",
                      json={"plate_or_tag_id": "KA-01-AA-4444", "type": "two_wheeler"},
                      headers=headers)
    assert res.status_code == 409

    # duplicate plate
    res = client.post("/api/v1/vehicles",
                      json={"plate_or_tag_id": "KA-01-AA-1111", "type": "two_wheeler"},
                      headers=headers)
    assert res.status_code == 409

    # activate exactly one
    _register_vehicle(client, headers, "KA-01-AA-5555") if False else None
    res = client.post(f"/api/v1/vehicles/{v1['id']}/activate", headers=headers)
    assert res.status_code == 200 and res.json()["active_today"] is True
    res = client.post(f"/api/v1/vehicles/{v2['id']}/activate", headers=headers)
    assert res.json()["active_today"] is True
    vehicles = client.get("/api/v1/vehicles", headers=headers).json()
    assert sum(1 for v in vehicles if v["active_today"]) == 1

    # delete
    assert client.delete(f"/api/v1/vehicles/{v1['id']}", headers=headers).status_code == 204


# --------------------------------------------------------------------------- #
# Gate flow: allotment, one-bay-per-account, full lot, waitlist, release
# --------------------------------------------------------------------------- #
def test_gate_scan_allots_with_explanation(api):
    client = api["client"]
    headers = _login(client, "driver@test.io", "driverpw")
    _register_vehicle(client, headers, "KA-03-DR-0001")

    res = client.post("/api/v1/gate/scan", json={
        "plate_or_tag_id": "KA-03-DR-0001",
        "lot_preference_id": "lot-a",
        "destination_building_id": "b1",
    }, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    alloc = body["allocation"]
    assert alloc["status"] in ("allotted", "offered_alternative")
    assert alloc["bay"]["label"].startswith("A-") or alloc["bay"]["label"].startswith("B-")
    assert alloc["explanation"]["rule_applied"]
    assert alloc["explanation"]["chosen"]["reason"]

    # one bay per account: the driver's second vehicle is rejected
    _register_vehicle(client, headers, "KA-03-DR-0002", "two_wheeler")
    res = client.post("/api/v1/gate/scan", json={
        "plate_or_tag_id": "KA-03-DR-0002",
    }, headers=headers)
    assert res.status_code == 200
    assert res.json()["allocation"]["status"] == "rejected"
    assert "already holds" in res.json()["message"]

    # driver status shows the bay
    status = client.get("/api/v1/me/status", headers=headers).json()
    assert status["current_parking"] is not None
    assert status["current_parking"]["bay"]["label"]
    assert status["current_parking"]["walk_hint"]["text"]


def test_full_lot_alternative_waitlist_and_release(api):
    client = api["client"]
    Session = api["sessions"]

    # Fill the campus: four bays are held by other people, and bay A-03 has a
    # real open allotment for a holder who is about to drive out.
    db = Session()
    db.add(User(id="u-holder", name="Holder", email="holder@test.io",
                password_hash=get_password_hash("holderpw"), role=UserRole.driver))
    db.add(Vehicle(id="v-holder", user_id="u-holder",
                   plate_or_tag_id="KA-03-HOLD-01", type=VehicleType.four_wheeler))
    db.add(Allotment(id="al-holder", vehicle_id="v-holder", bay_id="a3",
                     status=AllotmentStatus.occupied))
    for bay_id in ("a1", "a2", "b1", "b2"):
        db.query(Bay).filter(Bay.id == bay_id).first().state = BayState.allotted
    db.query(Bay).filter(Bay.id == "a3").first().state = BayState.occupied
    db.commit()
    db.close()

    driver_headers = _login(client, "driver@test.io", "driverpw")
    _register_vehicle(client, driver_headers, "KA-03-FULL-01")
    res = client.post("/api/v1/gate/scan", json={
        "plate_or_tag_id": "KA-03-FULL-01", "lot_preference_id": "lot-a",
    }, headers=driver_headers)
    assert res.status_code == 200
    assert res.json()["allocation"]["status"] == "waitlisted"
    position = res.json()["allocation"]["waitlist_position"]
    assert position == 1

    # Tier 1 driver joins behind them, then jumps to the head of the queue.
    t1_headers = _login(client, "other@test.io", "otherpw")
    _register_vehicle(client, t1_headers, "KA-03-T1-0001")
    res = client.post("/api/v1/gate/scan", json={
        "plate_or_tag_id": "KA-03-T1-0001", "lot_preference_id": "lot-a",
    }, headers=t1_headers)
    assert res.json()["allocation"]["status"] == "waitlisted"
    assert res.json()["allocation"]["waitlist_position"] == 1

    status = client.get("/api/v1/me/status", headers=t1_headers).json()
    assert status["waitlist"]["position"] == 1

    # The holder drives out -> the bay is freed and offered to the waitlist
    # head (Tier 1), through the same ingestion endpoint hardware uses.
    device_headers = {"X-API-Key": _device_key(db := Session())}
    res = client.post("/api/v1/ingest/gate-scan", json={
        "vehicle_tag_id": "KA-03-HOLD-01", "direction": "out_scan",
    }, headers=device_headers)
    assert res.status_code == 200, res.text
    assert res.json()["allocation_result"] is None
    db.close()

    # The Tier 1 driver now holds the freed bay (A-03) and was notified.
    status = client.get("/api/v1/me/status", headers=t1_headers).json()
    assert status["current_parking"] is not None
    assert status["current_parking"]["bay"]["label"] == "A-03"
    notes = client.get("/api/v1/me/notifications", headers=t1_headers).json()
    assert any("bay" in n["message"].lower() for n in notes)

    # The Tier 3 driver is still waiting and can leave the queue.
    status = client.get("/api/v1/me/status", headers=driver_headers).json()
    assert status["waitlist"] is not None
    assert status["current_parking"] is None
    res = client.post("/api/v1/waitlist/leave", json={}, headers=driver_headers)
    assert res.status_code == 200
    status = client.get("/api/v1/me/status", headers=driver_headers).json()
    assert status["waitlist"] is None


def _device_key(db) -> str:
    """Create/return a device API key for ingest calls in tests."""
    from app.db.models import Device, DeviceKind, DeviceStatus
    from app.core.security import get_password_hash as hashpw

    existing = db.query(Device).filter(Device.name == "test-device").first()
    if existing is None:
        db.add(Device(id="dev-test", name="test-device", kind=DeviceKind.gate_scanner,
                      api_key_hash=hashpw("test-key"), status=DeviceStatus.online))
        db.commit()
    return "test-key"


# --------------------------------------------------------------------------- #
# Predictions + live polling
# --------------------------------------------------------------------------- #
def test_predictions_are_labelled_heuristic(api):
    client = api["client"]
    body = client.get("/api/v1/predictions").json()
    assert "disclaimer" in body and "heuristic" in body["disclaimer"].lower()
    assert body["predictions"], "one prediction per lot expected"
    for pred in body["predictions"]:
        assert pred["method"]
        assert pred["heuristic_label"]
        assert pred["confidence"] in ("high", "medium", "low")


def test_poll_fallback_reports_version_changes(api):
    client = api["client"]

    # mutate state first so the version is > 0
    headers = _login(client, "driver@test.io", "driverpw")
    _register_vehicle(client, headers, "KA-03-POLL-01")

    first = client.get("/api/v1/events/poll?since=0").json()
    assert first["version"] > 0 and first["changed"] is True
    same = client.get(f"/api/v1/events/poll?since={first['version']}").json()
    assert same["changed"] is False

    # another mutation -> version bumps -> clients refetch
    _register_vehicle(client, headers, "KA-03-POLL-02")
    after = client.get(f"/api/v1/events/poll?since={first['version']}").json()
    assert after["changed"] is True and after["version"] > first["version"]


# --------------------------------------------------------------------------- #
# Admin: rules, analytics, conflicts, metrics
# --------------------------------------------------------------------------- #
def test_admin_rules_roundtrip_and_protection(api):
    client = api["client"]
    admin_headers = _login(client, "admin@test.io", "adminpw")

    rules = client.get("/api/v1/admin/rules", headers=admin_headers).json()
    assert "grace_period_minutes" in rules
    assert rules["grace_period_minutes"]["description"]

    res = client.put("/api/v1/admin/rules",
                     json={"updates": {"grace_period_minutes": 7}},
                     headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["grace_period_minutes"] == 7

    # unknown rule rejected
    res = client.put("/api/v1/admin/rules",
                     json={"updates": {"nonsense": 1}}, headers=admin_headers)
    assert res.status_code == 400

    # driver cannot read or write
    driver_headers = _login(client, "driver@test.io", "driverpw")
    assert client.get("/api/v1/admin/rules", headers=driver_headers).status_code == 403
    assert client.put("/api/v1/admin/rules",
                      json={"updates": {"grace_period_minutes": 1}},
                      headers=driver_headers).status_code == 403


def test_admin_bay_editor(api):
    client = api["client"]
    admin_headers = _login(client, "admin@test.io", "adminpw")

    res = client.post("/api/v1/admin/bays", json={
        "lot_id": "lot-b", "label": "B-99", "type": "two_wheeler",
        "x": 0, "y": 4, "is_accessible": True,
    }, headers=admin_headers)
    assert res.status_code == 201, res.text
    bay_id = res.json()["id"]

    res = client.patch(f"/api/v1/admin/bays/{bay_id}",
                       json={"x": 3, "y": 5, "reserved_tier": 2},
                       headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["x"] == 3 and res.json()["reserved_tier"] == 2

    assert client.delete(f"/api/v1/admin/bays/{bay_id}", headers=admin_headers).status_code == 204

    # audit trail recorded the edits
    audit = client.get("/api/v1/admin/audit", headers=admin_headers).json()
    actions = {a["action"] for a in audit}
    assert "bay_created" in actions and "bay_deleted" in actions


def test_admin_analytics_shapes(api):
    client = api["client"]
    admin_headers = _login(client, "admin@test.io", "adminpw")
    body = client.get("/api/v1/admin/analytics", headers=admin_headers).json()
    for key in ("lots", "queue_length", "conflicts", "no_show", "utilization_series",
                "devices", "audit", "totals"):
        assert key in body
    assert isinstance(body["no_show"]["no_show_rate_pct"], (int, float))


def test_metrics_run_computes_both_policies(api):
    client = api["client"]
    admin_headers = _login(client, "admin@test.io", "adminpw")
    res = client.post("/api/v1/admin/metrics/run",
                      json={"seed": 7, "hours": 4, "scale": 1.0},
                      headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["arrivals"] > 0, "the run must generate arrivals"
    for policy in ("baseline", "parkwise"):
        assert policy in body
        for metric in ("parked", "failed_entries", "wasted_entries",
                       "avg_search_minutes", "utilization_pct",
                       "tier1_access_success_pct"):
            assert metric in body[policy]
    assert body["assumptions"]["parameters"]
    assert "computed" in body["label"].lower()

    stored = client.get("/api/v1/metrics").json()
    assert stored["run"]["baseline"]["policy"].startswith("BASELINE")


# --------------------------------------------------------------------------- #
# Privacy: plates masked outside staff/owner views
# --------------------------------------------------------------------------- #
def test_plates_masked_for_non_staff(api):
    client = api["client"]
    db = api["sessions"]()
    from app.db.models import Allotment as A

    # give the "other" (tier 1) driver an open allotment in bay a1
    db.add(Vehicle(id="v-plate", user_id="u-other", plate_or_tag_id="KA-01-AB-1234",
                   type=VehicleType.four_wheeler))
    db.add(A(vehicle_id="v-plate", bay_id="a1", status=AllotmentStatus.occupied))
    db.query(Bay).filter(Bay.id == "a1").first().state = BayState.occupied
    db.commit()
    db.close()

    # anonymous viewer sees a masked plate
    bays = client.get("/api/v1/lots/lot-a/bays").json()["bays"]
    plate = next(b for b in bays if b["id"] == "a1")["allotment"]["plate"]
    assert "•" in plate and "1234" in plate

    # admin sees the real plate
    admin_headers = _login(client, "admin@test.io", "adminpw")
    bays = client.get("/api/v1/lots/lot-a/bays", headers=admin_headers).json()["bays"]
    plate = next(b for b in bays if b["id"] == "a1")["allotment"]["plate"]
    assert plate == "KA-01-AB-1234"
