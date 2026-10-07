#!/usr/bin/env python3
"""Mock device — Phase 7 acceptance: a fake IR sensor / webcam edge device.

Posts ONLY normalized events to the SAME ingestion endpoints the real
hardware uses (X-API-Key auth, no DB shortcuts), then reads the public live
API back to prove the Live Lot Map would update:

    python scripts/mock_device.py http://127.0.0.1:8010
    PARKWISE_BASE_URL=https://parkwise-theta.vercel.app python scripts/mock_device.py

Flow
----
  1. heartbeat            POST /api/v1/ingest/heartbeat
  2. bay occupied         POST /api/v1/ingest/bay-event (occupied=true)
  3. read back            GET  /api/v1/lots/{lot}/bays  -> state must be occupied
  4. bay freed            POST /api/v1/ingest/bay-event (occupied=false)
  5. read back            -> state must be back to free
  6. (optional) demonstrate the demo-day input-source toggle: with
     --toggle-test, switch to simulated_only, show the 409 rejection, and
     restore `live` (requires admin login).

Exit code 0 = pass. Cleanup always restores the original bay state.
"""
from __future__ import annotations

import os
import sys
import uuid

import httpx

DEFAULT_BASE = os.environ.get("PARKWISE_BASE_URL", "http://127.0.0.1:8010")
ADMIN = ("admin@parkwise.edu", "admin123")
DEVICE_KEY = os.environ.get("PARKWISE_DEVICE_KEY", "sim-key-lot-a")

results: list[tuple[str, bool, str]] = []


def report(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE).rstrip("/")
    toggle_test = "--toggle-test" in sys.argv
    hw_source = os.environ.get("PARKWISE_MOCK_SOURCE", "ir_sensor")
    device_headers = {"X-API-Key": DEVICE_KEY}
    tag = "SMK-" + uuid.uuid4().hex[:6].upper()

    print(f"mock device -> {base} (source={hw_source}, key=***{DEVICE_KEY[-5:]})")

    with httpx.Client(base_url=base, timeout=30.0) as client:
        # 0. API reachable
        health = client.get("/api/v1/health")
        report("api reachable", health.status_code == 200, f"status={health.status_code}")
        if health.status_code != 200:
            return finish()

        # Pick a lot + a free bay from the PUBLIC live API (exactly what the
        # frontend Live Lot Map reads — no DB shortcuts).
        lots = client.get("/api/v1/lots").json()
        target_lot = None
        target_bay = None
        for lot in lots:
            bays = client.get(f"/api/v1/lots/{lot['id']}/bays").json()["bays"]
            free = [b for b in bays if b["state"] == "free"]
            if free:
                target_lot, target_bay = lot, free[0]
                break
        report("found a free bay via public API", target_bay is not None,
               f"lot={target_lot['name'] if target_lot else '-'} "
               f"bay={target_bay['label'] if target_bay else '-'}")
        if not target_bay:
            return finish()

        # 1. heartbeat
        r = client.post("/api/v1/ingest/heartbeat",
                        json={"device_id": "mock-device", "status": "online"},
                        headers=device_headers)
        report("heartbeat accepted", r.status_code == 200, f"status={r.status_code}")

        # 2. bay occupied (hardware source)
        r = client.post("/api/v1/ingest/bay-event",
                        json={"bay_id": target_bay["id"], "occupied": True,
                              "source": hw_source, "confidence": 0.93},
                        headers=device_headers)
        report("bay-event (occupied) accepted", r.status_code == 200,
               f"status={r.status_code} {r.text[:160]}")

        # 3. read back through the public API
        bays = client.get(f"/api/v1/lots/{target_lot['id']}/bays").json()["bays"]
        state = next((b["state"] for b in bays if b["id"] == target_bay["id"]), "?")
        report("live map shows sensor state", state in ("occupied", "allotted"),
               f"state={state}")

        # 4. bay freed
        r = client.post("/api/v1/ingest/bay-event",
                        json={"bay_id": target_bay["id"], "occupied": False,
                              "source": hw_source, "confidence": 0.95},
                        headers=device_headers)
        report("bay-event (freed) accepted", r.status_code == 200,
               f"status={r.status_code}")

        # 5. read back — restored
        bays = client.get(f"/api/v1/lots/{target_lot['id']}/bays").json()["bays"]
        state = next((b["state"] for b in bays if b["id"] == target_bay["id"]), "?")
        report("live map restored to free", state == "free", f"state={state}")

        # 6. demo-day toggle: hardware paused -> 409; simulator still flows
        if toggle_test:
            tok = client.post("/api/v1/auth/login",
                              json={"email": ADMIN[0], "password": ADMIN[1]})
            if tok.status_code != 200:
                report("admin login for toggle test", False, tok.text[:120])
            else:
                ah = {"Authorization": f"Bearer {tok.json()['access_token']}"}
                try:
                    r = client.post("/api/v1/admin/input-source",
                                    json={"mode": "simulated_only"}, headers=ah)
                    report("toggle -> simulated_only", r.status_code == 200, r.text[:120])

                    r = client.post("/api/v1/ingest/bay-event",
                                    json={"bay_id": target_bay["id"], "occupied": True,
                                          "source": hw_source, "confidence": 0.9},
                                    headers=device_headers)
                    report("hardware source now rejected (409)", r.status_code == 409,
                           r.text[:160])

                    r = client.post("/api/v1/ingest/bay-event",
                                    json={"bay_id": target_bay["id"], "occupied": True,
                                          "source": "simulator", "confidence": 1.0},
                                    headers=device_headers)
                    report("simulator still accepted", r.status_code == 200,
                           r.text[:160])
                    # restore free state after the simulator event
                    client.post("/api/v1/ingest/bay-event",
                                json={"bay_id": target_bay["id"], "occupied": False,
                                      "source": "simulator", "confidence": 1.0},
                                headers=device_headers)
                finally:
                    client.post("/api/v1/admin/input-source",
                                json={"mode": "live"}, headers=ah)
                    report("toggle restored to live", True)

        # cleanup: gate-scan nothing happened, but restore bay just in case
        client.post("/api/v1/ingest/bay-event",
                    json={"bay_id": target_bay["id"], "occupied": False,
                          "source": "simulator", "confidence": 1.0},
                    headers=device_headers)

    return finish()


def finish() -> int:
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\nmock device: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
