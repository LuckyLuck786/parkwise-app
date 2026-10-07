# ParkWise — Thermocol Model Layout Guide

The physical model mirrors the **Bay Editor** grid (Admin → Bay Editor) one
bay one square, so what you draw there is what you build on the board.

## 1. Print the grid, transfer it to thermocol

1. In the Bay Editor, open the lot you are modelling (start with **Lot A** —
   24 bays fits a 2 ft × 3 ft board).
2. Take a screenshot of the grid or rebuild from the bay table
   (`label, x, y, type, is_accessible` — each unit = 1 square).
3. On paper, print a square grid of the same size (e.g. 24 × 8 squares),
   mark each square with its bay label (`A-01` … ), then glue it onto the
   thermocol sheet.
4. Cut lane markings (arrows) between rows; leave a driving lane ≥ 1 toy-car
   width between bay rows.

## 2. Bay sizes (toy vehicles)

| Element | Size on 1-unit grid | Notes |
|---|---|---|
| 4-wheeler bay | 6 cm × 12 cm | matches `type=four_wheeler` |
| 2-wheeler bay | 4 cm × 7 cm | two 2W bays may share one 4W square |
| Accessible bay | 8 cm × 12 cm + 1 cm hatch strip | mark `is_accessible` squares with cross-hatch + ♿ sticker — **never colour alone** |
| Driving lane | ≥ 6 cm wide | one-way loop keeps toy cars from dead-ending |
| Gate stop line | 2 cm before first lot row | where the scanner/camera reads tags |

Paint bay outlines white on the grey thermocol so the webcam baseline
contrast is high.

## 3. Camera (Logitech webcam) mounting

- **Height:** 70–90 cm above the board looking straight down (birds-eye);
  a 45° corner mount also works if every bay polygon stays unoccluded.
- **Coverage:** one webcam covers ~12–16 bays comfortably; for the full
  Lot A use two webcams (two edge-agent processes, different
  `--device-id`, same API key) or one wide-angle at 110°.
- **Fixing:** clamp on a rigid pole taped to the table edge — vibration is
  the number-one cause of calibration drift.
- **Focus:** lock manual focus (turn the ring and tape it) so autofocus
  does not breathe during the demo.

## 4. Lighting

- Even diffuse light; avoid a window behind the board (sun movement
  changes colours mid-demo and breaks baselines).
- If the room is dim, one LED strip along the top edge; avoid lamps that
  flicker (they alias with the camera frame rate).
- Do NOT move or re-colour anything between baseline capture and demo —
  the baseline is captured with the lot **empty** (see
  `edge_agent/webcam_agent.py --save-baseline`).

## 5. QR / ArUco tags on toy vehicles

- Print **ArUco DICT_4X4_50** tags, IDs 0–31, at 3 cm × 3 cm for toy cars
  and 2 cm × 2 cm for bikes; mount flat on the roof/seat, not on curved
  bodywork.
- Alternative: QR codes with the vehicle tag string
  (`SMK-XXXXXX` or a driver's plate) — easier to read from a phone when
  demoing the gate scan manually.
- Gate station: the camera's **gate region** (a rectangle calibrated once)
  is where tags are read; place the stop line inside that rectangle.
- Test read distance: QR at 25–40 cm, ArUco at 30–60 cm under demo light.

## 6. IR sensor placement (optional per-bay sensing)

- Mount the IR pair at the bay's outer edge, 15–25 cm above the surface,
  pointing across the bay centre — see `WIRING.md`.
- Toy cars must fully break the beam; test every bay after the board is
  final (thermocol dust on the receiver lowers range).

## 7. Board layout checklist before demo day

- [ ] Bay labels on board == Bay Editor labels (`A-01`, `A-02`, …)
- [ ] Accessible bays nearest the step-free entrance (ramp cut-out)
- [ ] Gate stop line inside camera gate region
- [ ] Every IR bay marked with its `bay_id` on a paper flag (for BAY_MAP)
- [ ] Baseline captured with an empty lot
- [ ] One `scripts/mock_device.py` run passes before guests arrive
