# ParkWise — Wiring Guide (ESP32 + IR obstacle sensors)

One IR sensor per bay. One ESP32 can serve 4–6 bays (one GPIO each) or use
one ESP32 per bay for the demo board — both work with the same sketch.

## Parts per bay

| Part | Qty | Notes |
|---|---|---|
| ESP32 DevKit (ESP32-WROOM) | 1 per 4–6 bays | any common DevKit v1 |
| IR obstacle avoidance module | 1 | 3–5 V, digital OUT, adjustable pot |
| Dupont wires M-F | 3 | VCC, GND, OUT |
| USB cable (data) | 1 | power + flash |

## Connections

```
IR module          ESP32 DevKit
---------          ------------
VCC   ───────────  5V  (VIN)      some modules accept 3V3 — check your module
GND   ───────────  GND
OUT   ───────────  GPIO 13        (default BAY_MAP[0].pin in the sketch)
```

- Default pin is **GPIO 13**; additional bays on the same ESP32: GPIO 14, 15,
  26, 27, 32 (avoid 0, 2, 15 — boot-strapping pins; avoid 34–39 — input-only,
  no pull-ups).
- The sketch uses `INPUT_PULLUP` and treats **LOW = obstacle detected**.
  Most IR obstacle modules pull LOW when the beam is broken. If your module
  is active-HIGH, change `IR_TRIGGER_LEVEL` to `HIGH`.
- Aim the IR pair across the bay at ~15–25 cm above the board surface so a
  toy car blocks it but a hand reaching over the lane does not.

## Flashing

1. Install ESP32 board support in Arduino IDE (Boards Manager → "esp32").
2. Install libraries: **WiFi** (bundled), **HTTPClient** (bundled),
   **ArduinoJson** (Library Manager).
3. Open `firmware/esp32_ir_bay.ino`, set:
   - `WIFI_SSID` / `WIFI_PASS`
   - `API_BASE` — `http://<your-laptop-ip>:8010` for local dev, or
     `https://parkwise-theta.vercel.app` for the deployed API
   - `DEVICE_API_KEY` — seeded key for the lot
     (`sim-key-lot-a` / `sim-key-lot-b` / `sim-key-lot-c`)
   - `BAY_MAP` — the `bay_id` for this sensor's bay. Get ids from
     `GET /api/v1/lots/{lot_id}/bays` (the `id` field), or from the
     Bay Editor's inspect view.
4. Upload. Open Serial Monitor at 115200 to confirm
   `wifi ok` and watch `bay-event … -> 200`.

## Health indicators

| Symptom | Likely cause | Fix |
|---|---|---|
| `heartbeat -> -1` | Wi-Fi down / wrong API_BASE | check SSID, laptop IP, firewall |
| `heartbeat -> 403` | wrong API key | re-check `DEVICE_API_KEY` |
| `bay-event -> 409` | admin paused hardware input | this is the demo-day toggle — expected; re-enable in Simulator panel |
| `bay-event -> 404` | `BAY_MAP` bay_id not in DB | re-copy bay id after any re-seed |
| state flapping | debounce too short / IR too sensitive | raise `DEBOUNCE_MS`, trim pot on module |

## Power

- Demo board: USB powered (each ESP32 ≈ 100–250 mA when transmitting).
- Longer runs: one 5 V / 3 A supply sharing rails for up to 6 ESP32s.

Safety: no mains wiring anywhere; everything is 5 V USB.
