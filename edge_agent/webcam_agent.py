#!/usr/bin/env python3
"""ParkWise webcam edge agent — runs on the laptop, NOT on the server.

Reads a Logitech webcam (or a test image / video file), detects per-bay
occupancy from calibrated polygons, optionally reads QR / ArUco tags on toy
vehicles at the gate, and POSTs ONLY normalized events to the same
/api/v1/ingest/* endpoints every other source uses (source="webcam").

    python edge_agent/webcam_agent.py --api http://127.0.0.1:8010 \
        --calibration edge_agent/calibration.json --camera 0

    # verify WITHOUT a webcam (acceptance mode):
    python edge_agent/webcam_agent.py --api http://127.0.0.1:8010 \
        --calibration edge_agent/calibration.json \
        --image edge_agent/test_frame.jpg --once

    # draw bay polygons interactively and save the calibration file:
    python edge_agent/calibrate.py --image frame.jpg \
        --output edge_agent/calibration.json

Detection (deliberately simple and explainable — no ML weights):
  * per-bay baseline colour model built from empty-bay samples,
  * live frames compared per pixel; the fraction of "different" pixels
    inside the polygon is the occupancy score,
  * score >= threshold -> occupied, with confidence = distance from the
    threshold (clamped to 0.5..0.99),
  * hysteresis: a bay must flip on two consecutive frames before the state
    is sent (sensor debounce), and only *changes* are POSTed.

Privacy: frames are processed in memory only. Nothing is written, uploaded
or stored — no images, no video, no logs of pixels. `--debug` opens a local
OpenCV window that is never saved.

Dependencies (edge machine only, NOT the server):
    pip install -r edge_agent/requirements.txt
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - guidance, not logic
    sys.exit(
        "Missing edge dependencies. On the laptop run:\n"
        "    pip install -r edge_agent/requirements.txt"
    )

import httpx

API_SOURCE = "webcam"  # EventSource.webcam on the server


# --------------------------------------------------------------------------- #
# Calibration file
# --------------------------------------------------------------------------- #
@dataclass
class BayPoly:
    bay_id: str
    polygon: List[Tuple[float, float]]
    label: str = ""
    # baseline pixel stats (mean colour + per-pixel stddev) for the polygon
    baseline: Optional[dict] = None

    def mask(self, shape: Tuple[int, int]) -> "np.ndarray":
        m = np.zeros(shape[:2], dtype=np.uint8)
        cv2.fillPoly(m, [np.array(self.polygon, dtype=np.int32)], 255)
        return m


def load_calibration(path: Path) -> dict:
    data = json.loads(path.read_text())
    if "bays" not in data or not isinstance(data["bays"], list):
        raise ValueError(f"{path}: missing 'bays' list — run calibrate.py first")
    for b in data["bays"]:
        if "bay_id" not in b or "polygon" not in b:
            raise ValueError(f"{path}: every bay needs bay_id + polygon")
    return data


def save_baseline(calib: dict, path: Path, frame: "np.ndarray") -> None:
    """Compute per-bay empty-bay colour baselines and persist them.

    Call this ONCE with the lot empty (calibrate.py records the frame the
    polygons were drawn on, so that frame is the natural baseline).
    """
    for b in calib["bays"]:
        bay = BayPoly(bay_id=b["bay_id"], polygon=[tuple(p) for p in b["polygon"]])
        mask = bay.mask(frame.shape)
        pixels = frame[mask > 0].astype(np.float32)
        if pixels.size == 0:
            raise ValueError(f"bay {b['bay_id']} has an empty polygon")
        b["baseline"] = {
            "mean": pixels.mean(axis=0).tolist(),
            "std": pixels.std(axis=0).tolist(),
        }
    path.write_text(json.dumps(calib, indent=2))
    print(f"baseline saved to {path} ({len(calib['bays'])} bays)")


# --------------------------------------------------------------------------- #
# Occupancy scoring
# --------------------------------------------------------------------------- #
@dataclass
class BayState:
    bay_id: str
    label: str
    occupied: Optional[bool] = None      # last SENT state
    pending: Optional[bool] = None       # candidate state (debounce)
    pending_frames: int = 0
    score: float = 0.0
    confidence: float = 0.0
    last_sent: Optional[bool] = None

    # hysteresis thresholds
    on_threshold: float = 0.45
    off_threshold: float = 0.35

    def update(self, score: float) -> Tuple[Optional[bool], float]:
        """Feed one frame; returns (state_to_send, confidence) or (None, 0)."""
        self.score = score
        # First reading ever: adopt and send immediately (sync with server;
        # debounce only applies to *changes* after that).
        if self.occupied is None:
            self.occupied = score >= self.on_threshold
            margin = abs(score - (self.on_threshold if self.occupied else self.off_threshold))
            self.confidence = round(min(0.99, 0.5 + margin), 2)
            return self.occupied, self.confidence

        candidate = self.occupied
        if score >= self.on_threshold:
            candidate = True
        elif score <= self.off_threshold:
            candidate = False
        # else: keep previous (dead band = hysteresis, no flapping)

        if candidate == self.occupied:
            self.pending = None
            self.pending_frames = 0
            return None, 0.0

        # debounce: candidate must hold for 2 consecutive frames
        if self.pending == candidate:
            self.pending_frames += 1
        else:
            self.pending = candidate
            self.pending_frames = 1
        if self.pending_frames < 2:
            return None, 0.0

        self.occupied = candidate
        self.pending = None
        self.pending_frames = 0
        # confidence: how far the score sits from the decision boundary
        margin = abs(score - (self.on_threshold if candidate else self.off_threshold))
        self.confidence = round(min(0.99, 0.5 + margin), 2)
        return candidate, self.confidence


def occupancy_score(frame: "np.ndarray", bay: BayPoly) -> Optional[float]:
    """Fraction of the polygon whose colour deviates from the baseline.

    0.0 = looks exactly like the empty baseline, 1.0 = every pixel differs.
    Unsupervised, deterministic, and explainable in one sentence — no ML.
    """
    if not bay.baseline:
        return None
    mask = bay.mask(frame.shape)
    pixels = frame[mask > 0].astype(np.float32)
    if pixels.size == 0:
        return None
    mean = np.array(bay.baseline["mean"], dtype=np.float32)
    std = np.maximum(np.array(bay.baseline["std"], dtype=np.float32), 8.0)
    # per-channel z-score, averaged; anything > 2.5 sigma counts as "changed"
    z = np.abs(pixels - mean) / std
    changed = (z > 2.5).any(axis=1)
    return float(changed.mean())


# --------------------------------------------------------------------------- #
# Gate tag reading (QR first, ArUco as fallback)
# --------------------------------------------------------------------------- #
def read_tag(frame: "np.ndarray") -> Optional[str]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    try:
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(gray)
        if data:
            return str(data).strip()
    except cv2.error:
        pass
    try:
        aruco = cv2.aruco
        dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        params = aruco.DetectorParameters()
        corners, ids, _ = aruco.ArucoDetector(dictionary, params).detectMarkers(gray)
        if ids is not None and len(ids):
            return str(int(ids[0][0]))
    except (AttributeError, cv2.error):
        pass
    return None


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #
@dataclass
class Agent:
    base_url: str
    api_key: str
    device_id: str
    calibration: dict
    states: Dict[str, BayState] = field(default_factory=dict)
    sent: Dict[str, bool] = field(default_factory=dict)
    last_heartbeat: float = 0.0
    dry_run: bool = False
    heartbeat_interval: float = 30.0

    def __post_init__(self) -> None:
        for b in self.calibration["bays"]:
            self.states[b["bay_id"]] = BayState(
                bay_id=b["bay_id"],
                label=b.get("label", b["bay_id"]),
                on_threshold=self.calibration.get("on_threshold", 0.45),
                off_threshold=self.calibration.get("off_threshold", 0.35),
            )

    # ---- HTTP ------------------------------------------------------------ #
    def _post(self, path: str, payload: dict) -> dict:
        if self.dry_run:
            print(f"[dry-run] POST {path} {json.dumps(payload)}")
            return {"success": True}
        r = httpx.post(
            f"{self.base_url}{path}",
            json=payload,
            headers={"X-API-Key": self.api_key},
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json() if r.content else {}

    def heartbeat(self, status: str = "online") -> None:
        now = time.time()
        if now - self.last_heartbeat < self.heartbeat_interval:
            return
        self.last_heartbeat = now
        self._post("/api/v1/ingest/heartbeat",
                   {"device_id": self.device_id, "status": status})

    def send_bay_event(self, bay_id: str, occupied: bool, confidence: float) -> None:
        self._post("/api/v1/ingest/bay-event", {
            "bay_id": bay_id,
            "occupied": occupied,
            "source": API_SOURCE,
            "confidence": confidence,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        self.sent[bay_id] = occupied
        tag = "OCCUPIED" if occupied else "free"
        print(f"  -> {bay_id}: {tag} (confidence {confidence})")

    def send_gate_scan(self, vehicle_tag_id: str, direction: str = "in_scan") -> None:
        self._post("/api/v1/ingest/gate-scan", {
            "vehicle_tag_id": vehicle_tag_id,
            "direction": direction,
            "source": API_SOURCE,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

    # ---- per-frame ------------------------------------------------------- #
    def process_frame(self, frame: "np.ndarray") -> None:
        self.heartbeat()
        for b in self.calibration["bays"]:
            bay = BayPoly(
                bay_id=b["bay_id"],
                polygon=[tuple(p) for p in b["polygon"]],
                label=b.get("label", ""),
                baseline=b.get("baseline"),
            )
            score = occupancy_score(frame, bay)
            if score is None:
                continue
            state = self.states[b["bay_id"]]
            to_send, confidence = state.update(score)
            if to_send is not None and self.sent.get(state.bay_id) != to_send:
                self.send_bay_event(state.bay_id, to_send, confidence)
            state.last_sent = to_send if to_send is not None else state.last_sent

        # optional gate region: read a QR/ArUco tag
        gate = self.calibration.get("gate_region")
        if gate:
            x0, y0, x1, y1 = [int(v) for v in gate]
            crop = frame[y0:y1, x0:x1]
            if crop.size:
                tag = read_tag(crop)
                if tag and self.sent.get("__tag__") != tag:
                    self.send_gate_scan(tag)
                    self.sent["__tag__"] = tag

    def initial_states(self, frame: "np.ndarray") -> None:
        """First frame: record current state WITHOUT sending (no false burst)."""
        for b in self.calibration["bays"]:
            bay = BayPoly(bay_id=b["bay_id"], polygon=[tuple(p) for p in b["polygon"]],
                          baseline=b.get("baseline"))
            score = occupancy_score(frame, bay)
            state = self.states[b["bay_id"]]
            if score is None:
                continue
            state.occupied = score >= state.on_threshold
            self.sent[state.bay_id] = state.occupied


def draw_overlay(frame: "np.ndarray", agent: Agent) -> "np.ndarray":
    out = frame.copy()
    for b in agent.calibration["bays"]:
        pts = np.array(b["polygon"], dtype=np.int32)
        state = agent.states[b["bay_id"]]
        occupied = state.occupied
        colour = (0, 0, 255) if occupied else (0, 200, 0)   # red/green…
        cv2.polylines(out, [pts], True, colour, 2)
        # …but NEVER colour alone: label + state word inside every polygon
        cx, cy = pts.mean(axis=0).astype(int)
        text = f"{state.label or b['bay_id']}: {'OCC' if occupied else 'FREE'} {state.score:.2f}"
        cv2.putText(out, text, (cx - 60, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 2, cv2.LINE_AA)
    gate = agent.calibration.get("gate_region")
    if gate:
        x0, y0, x1, y1 = [int(v) for v in gate]
        cv2.rectangle(out, (x0, y0), (x1, y1), (255, 200, 0), 2)
        cv2.putText(out, "GATE", (x0, y0 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (255, 200, 0), 2, cv2.LINE_AA)
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ParkWise webcam edge agent")
    p.add_argument("--api", default="http://127.0.0.1:8010",
                   help="ParkWise API base URL (local or deployed)")
    p.add_argument("--api-key", default="sim-key-lot-a",
                   help="device API key (default: seeded simulator device key)")
    p.add_argument("--device-id", default="webcam-agent-1")
    p.add_argument("--calibration", type=Path,
                   default=Path(__file__).resolve().with_name("calibration.json"))
    p.add_argument("--camera", type=int, default=None, help="camera index, e.g. 0")
    p.add_argument("--video", type=Path, default=None, help="video file (offline test)")
    p.add_argument("--image", type=Path, default=None,
                   help="single test image (acceptance mode, no webcam needed)")
    p.add_argument("--once", action="store_true",
                   help="process one frame/image then exit (test mode)")
    p.add_argument("--save-baseline", type=Path, default=None,
                   help="build baseline from --image and save calibration, then exit")
    p.add_argument("--gate-region", type=str, default=None,
                   help="x0,y0,x1,y1 crop for QR/ArUco gate tag reading")
    p.add_argument("--dry-run", action="store_true",
                   help="print events instead of POSTing (no server needed)")
    p.add_argument("--debug", action="store_true",
                   help="local debug window with polygon overlays (never saved)")
    p.add_argument("--interval", type=float, default=0.25,
                   help="seconds between camera frames")
    p.add_argument("--duration", type=float, default=None,
                   help="stop after N seconds (default: run until Ctrl-C)")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if not args.calibration.exists():
        sys.exit(f"Calibration not found: {args.calibration}\n"
                 f"Draw one with: python edge_agent/calibrate.py --image frame.jpg "
                 f"--output {args.calibration}")
    calib = load_calibration(args.calibration)
    if args.gate_region:
        calib["gate_region"] = [int(v) for v in args.gate_region.split(",")]

    # --- load source frame(s) ------------------------------------------- #
    if args.image:
        frame = cv2.imread(str(args.image))
        if frame is None:
            sys.exit(f"Cannot read image: {args.image}")
        if args.save_baseline:
            save_baseline(calib, args.save_baseline, frame)
            return 0
    else:
        frame = None

    agent = Agent(
        base_url=args.api.rstrip("/"),
        api_key=args.api_key,
        device_id=args.device_id,
        calibration=calib,
        dry_run=args.dry_run,
    )
    agent.heartbeat_interval = 30.0
    agent.last_heartbeat = 0.0  # force an immediate first heartbeat
    agent.heartbeat()

    # --- single image / once mode --------------------------------------- #
    if args.image or args.once:
        if frame is None:
            sys.exit("--once requires --image, --video or --camera")
        # NB: no initial_states() here — in test-image mode the whole point
        # is that the first reading is POSTed (update() sends it immediately).
        print(f"processing {args.image or 'first frame'} …")
        agent.process_frame(frame)
        print("current bay states: " + ", ".join(
            f"{s.label or s.bay_id}={'OCC' if s.occupied else 'FREE'}"
            for s in agent.states.values()))
        if args.debug:
            cv2.imshow("ParkWise webcam agent (debug)", draw_overlay(frame, agent))
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        return 0

    # --- continuous mode ------------------------------------------------- #
    if args.video:
        cap = cv2.VideoCapture(str(args.video))
    elif args.camera is not None:
        cap = cv2.VideoCapture(args.camera)
    else:
        sys.exit("Provide --camera N, --video FILE or --image FILE")

    if not cap.isOpened():
        sys.exit("Cannot open video source")

    started = time.time()
    first = True
    try:
        while True:
            ok, img = cap.read()
            if not ok:
                if args.video:
                    break  # end of file
                time.sleep(args.interval)
                continue
            if first:
                if not args.image:
                    agent.initial_states(img)
                first = False
            agent.process_frame(img)
            if args.debug:
                cv2.imshow("ParkWise webcam agent (debug)", draw_overlay(img, agent))
                cv2.waitKey(1)
            if args.duration and time.time() - started > args.duration:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if args.debug:
            cv2.destroyAllWindows()
        agent.heartbeat(status="offline")
    print("agent stopped; states sent:", json.dumps(
        {k: v for k, v in agent.sent.items() if not k.startswith("__")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
