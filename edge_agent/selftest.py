#!/usr/bin/env python3
"""Webcam-agent self-test — verifies the edge agent WITHOUT a webcam.

Generates two synthetic frames (empty lot / lot with one car), builds a
calibration JSON with polygons over a REAL bay fetched from the API, then
runs webcam_agent.py in --image mode:

    empty frame  -> baseline saved
    car frame    -> POST bay-event occupied (source=webcam) -> live map shows it
    empty frame  -> POST bay-event free        -> live map restored

    python edge_agent/selftest.py http://127.0.0.1:8010

Everything is written to a temp dir; nothing is committed or uploaded
except the two normalized bay-event pairs the agent itself sends.
Exit code 0 = pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

AGENT = Path(__file__).with_name("webcam_agent.py")
FRAME_W, FRAME_H = 640, 400


def make_frames(tmp: Path) -> tuple[Path, Path]:
    """Synthetic camera frames: dark asphalt with two painted bays; the
    'occupied' frame has a red car block inside bay 1."""
    import numpy as np

    def base():
        img = np.full((FRAME_H, FRAME_W, 3), 40, dtype=np.uint8)  # asphalt
        # bay 1: left half, bay 2: right half — painted floor rectangles
        img[80:320, 40:280] = (90, 90, 90)
        img[80:320, 340:580] = (90, 90, 90)
        for x in (40, 340):  # white edge lines
            img[80:84, x:x+240] = (230, 230, 230)
            img[316:320, x:x+240] = (230, 230, 230)
        return img

    empty = base()
    car = base()
    car[130:280, 80:250] = (40, 40, 200)  # red car in bay 1

    import cv2

    p_empty, p_car = tmp / "empty.jpg", tmp / "car.jpg"
    cv2.imwrite(str(p_empty), empty)
    cv2.imwrite(str(p_car), car)
    return p_empty, p_car


def main() -> int:
    base_url = (sys.argv[1] if len(sys.argv) > 2 else sys.argv[1] if len(sys.argv) > 1
                else "http://127.0.0.1:8010").rstrip("/")
    checks: list[tuple[str, bool, str]] = []

    def report(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        if client.get("/api/v1/health").status_code != 200:
            print(f"API not reachable at {base_url}")
            return 1
        # pick a real FREE bay (public API)
        lot = next(l for l in client.get("/api/v1/lots").json()
                   if l["counts"]["free"] >= 2)
        bays = client.get(f"/api/v1/lots/{lot['id']}/bays").json()["bays"]
        free = [b for b in bays if b["state"] == "free"][:2]
        bay1, bay2 = free[0], free[1]
        report("found 2 free bays", True, f"{bay1['label']}, {bay2['label']} in {lot['name']}")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        empty_img, car_img = make_frames(tmp)

        calib = {
            "lot": lot["name"],
            "bays": [
                {"bay_id": bay1["id"], "label": bay1["label"],
                 "polygon": [[40, 80], [280, 80], [280, 320], [40, 320]]},
                {"bay_id": bay2["id"], "label": bay2["label"],
                 "polygon": [[340, 80], [580, 80], [580, 320], [340, 320]]},
            ],
        }
        calib_path = tmp / "calibration.json"
        calib_path.write_text(json.dumps(calib))

        def run_agent(image: Path) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, str(AGENT), "--api", base_url,
                 "--calibration", str(calib_path), "--image", str(image)],
                capture_output=True, text=True, timeout=60,
            )

        # 1. baseline from the empty frame
        r = subprocess.run(
            [sys.executable, str(AGENT), "--api", base_url,
             "--calibration", str(calib_path), "--image", str(empty_img),
             "--save-baseline", str(calib_path)],
            capture_output=True, text=True, timeout=60,
        )
        report("baseline built from empty frame", r.returncode == 0,
               (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "")

        # 2. car frame -> occupied event for bay1
        r = run_agent(car_img)
        out = r.stdout + r.stderr
        report("agent ran on test image", r.returncode == 0, out.strip()[:200])
        report("occupied event sent for car bay",
               f"{bay1['id']}" in out and "OCCUPIED" in out, out.strip()[:300])

        bays_now = client_bays(base_url, lot["id"])
        state1 = next(b["state"] for b in bays_now if b["id"] == bay1["id"])
        report("live map shows webcam occupancy", state1 == "occupied", f"state={state1}")

        # 3. empty frame -> bay freed again
        r = run_agent(empty_img)
        out = r.stdout + r.stderr
        report("free event sent", r.returncode == 0 and "free (confidence" in out,
               out.strip()[:300])
        bays_now = client_bays(base_url, lot["id"])
        state1 = next(b["state"] for b in bays_now if b["id"] == bay1["id"])
        report("live map restored", state1 == "free", f"state={state1}")

    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"\nwebcam agent self-test: {passed}/{len(checks)} passed")
    return 0 if passed == len(checks) else 1


def client_bays(base_url: str, lot_id: str):
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        return client.get(f"/api/v1/lots/{lot_id}/bays").json()["bays"]


if __name__ == "__main__":
    sys.exit(main())
