# ParkWise

Priority-based campus parking allocation. A vehicle is scanned at the gate;
ParkWise allots the best bay it *can* justify — vehicle type, destination
walking distance, priority tier quotas — and explains every decision. When a
lot fills, drivers get an immediate alternative or a waitlist place with a
notification the moment a bay frees.

Runs entirely on **simulated data** today (simulator + demo controls), and
every input — simulator, IR sensors, webcam, manual override — goes through
**one ingestion interface**, so hardware plugs in later without touching the
core.

**Live:** https://parkwise-theta.vercel.app · **Repo:** https://github.com/LuckyLuck786/parkwise-app

---

## Quick start (local, one command each)

```bash
# 0) one-time setup
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm install && cd ..

# 1) seed (idempotent — safe to run twice): 3 lots, 62 bays, 27 users, 14 days of history
.venv/bin/python scripts/seed.py

# 2) backend + frontend
.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8010
cd frontend && npm run dev        # http://localhost:5310
```

The Vite dev server proxies `/api` to `:8010`. Optional env: see
[.env.example](.env.example).

**Demo logins**

| Role | Email | Password |
|---|---|---|
| Admin | `admin@parkwise.edu` | `admin123` |
| Gate operator | `gate1@parkwise.edu` | `gate123` |
| Driver — Tier 1 (accessible) | `priya.sharma@parkwise.edu` | `pass123` |
| Driver — Tier 2 (faculty) | `anand.rao@parkwise.edu` | `pass123` |
| Driver — Tier 3 (student) | `amit.kumar@parkwise.edu` | `pass123` |

The login page has one-click demo buttons that fill these in.

**Verify**

```bash
cd backend && ../.venv/bin/python -m pytest -q     # 42 tests
.venv/bin/python scripts/smoke_test.py http://127.0.0.1:8010   # 21 checks (any BASE_URL)
.venv/bin/python scripts/mock_device.py http://127.0.0.1:8010 --toggle-test  # 11 checks
.venv/bin/python edge_agent/selftest.py http://127.0.0.1:8010  # 7 checks, no webcam needed
```

---

## Architecture

```
browser (React + Vite + TS + Tailwind + Recharts)
   │  REST + SSE (polling fallback) + /api/v1/events/stream
   ▼
FastAPI (backend/app)
   ├── api/        auth, lots, gate, me, notifications, waitlist, admin, ingest
   ├── services/   allocation · rules · prediction · reconcile · notification
   │               input_source (demo kill-switch) · analytics · demo/simulation
   ├── adapters/   SensorAdapter interface — simulator implements it; IR/webcam
   │               speak the same normalized payloads over HTTP
   └── db/         SQLAlchemy models · idempotent deterministic seed
   ▲
   │  POST /api/v1/ingest/{bay-event,gate-scan,heartbeat}  (X-API-Key)
   │
[ simulator (admin panel) ] [ edge_agent/webcam_agent.py ] [ firmware/esp32_ir_bay ]
        all four produce identical normalized events — no special-case code path
```

Key properties:

- **One ingestion interface.** Every source posts the same
  `bay_occupancy / gate_scan` payloads; reconciliation, allocation and the
  Live Lot Map are source-agnostic. The simulator is just a device.
- **Explainable decisions.** Every allotment stores an explanation JSON
  (rule applied, candidates, why this bay, why others rejected) and writes
  an audit entry.
- **Tier quotas, never eviction.** Tier 1 = accessible bays nearest step-free
  entrances (held); Tier 2 = faculty/service quota held until the cut-off
  hour; Tier 3 = general pool. Quotas gate *assignment*, never move a parked
  car.
- **Deterministic seed (uuid5).** Two serverless instances seeding their own
  SQLite produce identical ids, so JWTs stay valid across cold starts.

## What is real vs simulated

| Real (production code paths) | Simulated (demo scaffolding) |
|---|---|
| Allocation engine, quotas, waitlist ordering, no-show release | All vehicles, users, arrivals (14-day synthetic history) |
| Fill-time prediction (hourly profile statistics from history) | The demo clock and "morning rush" generator |
| Reconciliation + conflict alerts + low-confidence fallback | In-app notifications (SMS/Telegram are stubs that log — no fake delivery) |
| JWT auth, role guards, audit log | Gate kiosk scans (they call the same `/ingest/gate-scan` a device would) |
| REST + SSE live updates, polling fallback | Bay occupancy streams from the simulator adapter |
| Ingestion endpoints + device API-key auth | **Not simulated:** `edge_agent/` and `firmware/` post real HTTP events (untested with physical hardware — see limitations) |
| Baseline-vs-ParkWise metrics (computed per run) | The baseline policy model assumptions (documented on the metrics page) |

Nothing on any page claims AI: prediction and metrics are labeled as
statistics/heuristics wherever they appear ("Simulated data" badges mark
demo data).

## Deployment

- **Vercel** (frontend static + FastAPI single function): see
  [vercel.json](vercel.json), [api/index.py](api/index.py),
  [requirements.txt](requirements.txt). `buildCommand` builds the frontend
  into `public/`; the FastAPI framework preset serves `/` with a SPA
  fallback rewrite (no `/api` rewrite needed — routes live under `/api/v1/*`
  on the app itself).
- **State:** deployed on ephemeral SQLite with a deterministic seed
  (resets on cold start; instance divergence handled by stable ids). Set
  `DATABASE_URL` (e.g. Neon Postgres) to make state durable — the code path
  already exists in `backend/app/core/config.py`; Mongo/other non-SQL stores
  are *not* supported (the schema is relational).
- **`SECRET_KEY`** is set as a Vercel production environment variable.
- **SSE:** `/api/v1/events/stream` works where functions allow long-lived
  responses; the frontend falls back to `GET /api/v1/events/poll`
  automatically.
- Edge agent and firmware are **not deployed** — they run on the laptop and
  ESP32 and POST to whichever API you point them at.

```bash
# smoke-test any deployment
.venv/bin/python scripts/smoke_test.py https://parkwise-theta.vercel.app
```

## Hardware roadmap (Phase 7 package — not required to run the app)

| Piece | Status |
|---|---|
| [scripts/mock_device.py](scripts/mock_device.py) | ✅ verified 11/11 — posts through the real ingest API, live map updates, toggle rejects hardware with 409 |
| [edge_agent/webcam_agent.py](edge_agent/webcam_agent.py) | ✅ verified 7/7 in `--image` mode (synthetic frames): baseline → occupied → free, all through the API |
| [edge_agent/calibrate.py](edge_agent/calibrate.py) | ✅ interactive polygon tool; [selftest.py](edge_agent/selftest.py) proves the pipeline without a webcam |
| [firmware/esp32_ir_bay.ino](firmware/esp32_ir_bay.ino) | 📝 written (debounce, Wi-Fi, POST + heartbeat, bay-ID map) — **not compiled/flashed here** (no Arduino toolchain in this environment) |
| [hardware/](hardware/) | 📝 [WIRING.md](hardware/WIRING.md), [THERMOCOL_LAYOUT.md](hardware/THERMOCOL_LAYOUT.md), [CALIBRATION_CHECKLIST.md](hardware/CALIBRATION_CHECKLIST.md), [DEMO_DAY_FAILURE_PLAN.md](hardware/DEMO_DAY_FAILURE_PLAN.md) |
| **Demo-day kill-switch** | ✅ Admin → Simulator → **Input source**: `live` ↔ `simulated_only` pauses `ir_sensor`/`webcam` events (HTTP 409) with one click; audited; simulator/manual unaffected |

Attach hardware later by: flashing the ESP32 with your Wi-Fi + bay ids, or
running `webcam_agent.py` on the laptop against the deployed URL — **no
backend changes**.

## Known limitations

- **Deployment state is ephemeral** on the default setup (SQLite per
  instance); set `DATABASE_URL` for durability. Seeded demo data regenerates
  deterministically otherwise.
- **ESP32 sketch is unverified on hardware** — written to spec, syntax
  sanity-checked, but never compiled/flashed (no Arduino toolchain here).
- **Webcam agent tested on synthetic images**, not a physical camera feed;
  detection is a color-baseline heuristic (no ML), so lighting changes after
  baseline capture require recalibration — see the checklist.
- **QR/ArUco tag reading** depends on OpenCV build features (aruco may be
  absent in some builds; QR is tried first, code degrades gracefully).
- **SMS/Telegram notifications are stubs** that log — deliberately no fake
  delivery.
- **Prediction is a heuristic**: hourly arrival profile × current occupancy.
  Honest label in UI; 14 days of synthetic history limits accuracy.
- **No real users/vehicles** — all demo identities are seeded; plates are
  masked for non-admin views by design.

## Repo layout

```
parkwise/
├── backend/app/{api,core,db,services,schemas,adapters}/
├── backend/tests/            # 42 pytest
├── frontend/src/{pages,components,hooks,services,types}/
├── edge_agent/               # laptop webcam agent + calibration + selftest
├── firmware/                 # ESP32 IR sketch
├── hardware/                 # wiring, thermocol, calibration, failure plan
├── scripts/                  # seed, simulate, smoke_test, mock_device
├── api/index.py  vercel.json # Vercel entry
├── README.md  DEMO_SCRIPT.md  .env.example
```

## License

Demo/academic project — no license attached yet.
