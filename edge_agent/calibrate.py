#!/usr/bin/env python3
"""ParkWise bay-polygon calibration tool (laptop, interactive).

Draws one polygon per bay on a still frame (or a live camera snapshot) and
saves the calibration JSON the webcam agent loads. Polygon coordinates are
in image pixels, matching what the Bay Editor grid shows for each lot, so
the thermocol layout can be traced bay by bay.

    python edge_agent/calibrate.py --image frame.jpg \
        --output edge_agent/calibration.json --bays A-01,A-02,A-03

Controls (OpenCV window):
    left click   add polygon point
    right click  undo last point
    Enter        close polygon for the current bay, advance to the next
    r            reset the current bay's points
    s            save and exit (can stop early — undrawn bays are skipped)
    q            quit without saving

No image is ever written to disk: the frame stays in memory, only the JSON
polygons are saved. After calibrating, build the empty-bay colour baseline:

    python edge_agent/webcam_agent.py --calibration edge_agent/calibration.json \
        --image empty_lot_frame.jpg --save-baseline edge_agent/calibration.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit("Missing edge dependencies: pip install -r edge_agent/requirements.txt")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Draw bay polygons, save calibration JSON")
    p.add_argument("--image", type=Path, required=True, help="still frame to draw on")
    p.add_argument("--output", type=Path, required=True, help="calibration JSON path")
    p.add_argument("--bays", required=True,
                   help="comma-separated bay labels in grid order, e.g. A-01,A-02,A-03")
    p.add_argument("--lot", default="", help="lot name recorded in the file")
    p.add_argument("--scale", type=float, default=1.0,
                   help="downscale factor for drawing on big frames "
                        "(coordinates are scaled back on save)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    frame = cv2.imread(str(args.image))
    if frame is None:
        sys.exit(f"Cannot read image: {args.image}")

    labels = [b.strip() for b in args.bays.split(",") if b.strip()]
    if not labels:
        sys.exit("--bays must list at least one label")

    scale = args.scale
    if scale != 1.0:
        frame = cv2.resize(frame, None, fx=scale, fy=scale)

    state = {"label_idx": 0, "points": []}
    polygons: List[Tuple[str, List[Tuple[float, float]]]] = []
    window = "Calibrate bays (Enter=next bay, s=save, q=quit)"

    def redraw() -> np.ndarray:
        img = frame.copy()
        for i, (label, poly) in enumerate(polygons):
            pts = np.array(poly, dtype=np.int32)
            cv2.polylines(img, [pts], True, (0, 200, 0), 2)
            c = pts.mean(axis=0).astype(int)
            cv2.putText(img, label, (int(c[0]) - 30, int(c[1])),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0), 2, cv2.LINE_AA)
        if state["points"]:
            pts = np.array(state["points"], dtype=np.int32)
            for pt in state["points"]:
                cv2.circle(img, tuple(pt), 4, (0, 140, 255), -1)
            if len(pts) > 1:
                cv2.polylines(img, [pts], False, (0, 140, 255), 2)
        hint = (f"bay {state['label_idx'] + 1}/{len(labels)}: "
                f"{labels[state['label_idx']] if state['label_idx'] < len(labels) else '-'}"
                f"  |  {len(state['points'])} pts  |  ENTER=next  R=reset  S=save  Q=quit")
        cv2.putText(img, hint, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2, cv2.LINE_AA)
        return img

    def on_mouse(event, x, y, flags, param):  # noqa: ANN001
        if event == cv2.EVENT_LBUTTONDOWN and state["label_idx"] < len(labels):
            state["points"].append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and state["points"]:
            state["points"].pop()

    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)

    saved = False
    try:
        while True:
            cv2.imshow(window, redraw())
            key = cv2.waitKey(30) & 0xFF
            if key in (13, 10):  # Enter — close current bay
                if len(state["points"]) >= 3 and state["label_idx"] < len(labels):
                    inv = 1.0 / scale
                    poly = [(px * inv, py * inv) for px, py in state["points"]]
                    polygons.append((labels[state["label_idx"]], poly))
                    state["points"] = []
                    state["label_idx"] += 1
                    if state["label_idx"] >= len(labels):
                        print("all bays drawn — press S to save")
            elif key in (ord("r"), ord("R")):
                state["points"] = []
            elif key in (ord("s"), ord("S")):
                saved = True
                break
            elif key in (ord("q"), ord("Q"), 27):
                break
    finally:
        cv2.destroyAllWindows()

    if not saved:
        print("quit without saving")
        return 1
    if not polygons:
        sys.exit("No polygons drawn — nothing saved")

    out = {
        "lot": args.lot,
        "image_size": {"width": int(frame.shape[1] / scale),
                       "height": int(frame.shape[0] / scale)},
        "bays": [
            {"bay_id": label, "label": label, "polygon": [[round(px, 1), round(py, 1)]
                                                          for px, py in poly]}
            for label, poly in polygons
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2))
    print(f"saved {len(polygons)} bay polygons -> {args.output}")
    print("next: build the empty-bay baseline with webcam_agent.py --save-baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
