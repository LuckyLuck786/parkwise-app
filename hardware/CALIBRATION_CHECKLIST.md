# ParkWise — Calibration Checklist

Work top to bottom. Total time: ~15 minutes with the board ready.

## A. Before calibrating

- [ ] Board final: bays painted, labels match the Bay Editor exactly
- [ ] Lighting on and stable for ≥ 2 min (camera white balance settles)
- [ ] Webcam locked (rigid mount, manual focus taped)
- [ ] Lot **empty** — no toy vehicles in any bay
- [ ] API reachable: `curl $API/api/v1/health` → `{"status":"ok"}`
- [ ] Seed intact — bay ids read after any re-seed (ids are deterministic,
      but a fresh seed on a new DB will differ)

## B. Bay polygons

```bash
# grab one still frame (any method — e.g. ffmpeg or the agent's debug view)
python edge_agent/calibrate.py --image frame.jpg \
    --output edge_agent/calibration.json \
    --lot "Lot A" --bays A-01,A-02,A-03,...
```

- [ ] Every polygon fully inside its painted bay (2–3 px margin, not flush
      to the lines — paint bleed causes edge noise)
- [ ] Adjacent polygons **do not overlap** (a car in one bay must not vote
      in its neighbour)
- [ ] Gate region drawn around the stop line (`--gate-region` in the agent)
- [ ] `bay_id` values in the JSON are the API ids (they default to labels
      in calibrate.py — replace with real ids from
      `GET /api/v1/lots/{id}/bays` if you changed them)

## C. Baseline (empty-bay colour model)

```bash
python edge_agent/webcam_agent.py \
    --calibration edge_agent/calibration.json \
    --image empty_lot_frame.jpg \
    --save-baseline edge_agent/calibration.json
```

- [ ] Baseline frame taken from the **exact same camera position** as the
      polygons (same session, no moves in between)
- [ ] All bays report a baseline (`"baseline"` key present per bay)
- [ ] Place one car in each bay in turn → agent reports OCCUPIED
      (`--debug` overlay shows score > 0.45)
- [ ] Remove it → reports FREE (score < 0.35) — confirm both directions
      (hysteresis dead band is 0.35–0.45 by design)

## D. End-to-end verification (no hardware trust assumed)

```bash
# 1. mock device (pure HTTP): 11/11 expected
python scripts/mock_device.py $API --toggle-test

# 2. webcam agent on synthetic frames: 7/7 expected
python edge_agent/selftest.py $API

# 3. pytest
cd backend && python -m pytest -q        # 42 expected
```

- [ ] Live Lot Map reflects a test bay-event within one poll interval
      (≤ 5 s; SSE when connected)
- [ ] Admin → Devices shows the edge device `online` with a fresh
      `last_heartbeat`

## E. IR sensors (if attached)

- [ ] Each bay: hand (car) blocks sensor → event ≤ 1 s after debounce
- [ ] Serial monitor shows `bay-event … -> 200` (not 403/404/409)
- [ ] Remove hand → `occupied=false` arrives
- [ ] Bay labelled with its `bay_id` matches `BAY_MAP` in the sketch

## F. After demo / moving the board

Any of these invalidate the calibration — redo B + C:
- [ ] camera moved or refocused
- [ ] lighting changed (blinds, sun, lamps)
- [ ] bay paint/labels changed
