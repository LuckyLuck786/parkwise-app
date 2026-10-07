# ParkWise — Demo-Day Failure Plan

Hardware fails in front of an audience. This plan means the demo still
lands. **One admin toggle is the centre of it.**

## The one switch

**Admin → Simulator panel → Input source**

| Mode | Effect |
|---|---|
| `live` (default) | simulator, IR, webcam and manual events all accepted |
| `simulated_only` | hardware sources (`ir_sensor`, `webcam`) rejected with 409 — a flaky device **cannot corrupt the demo**; simulator + manual keep working |

The toggle gates *ingestion only*. No code path changes, nothing restarts,
the Live Lot Map keeps updating. It is audited
(`input_source_changed` in the Audit Log) and exposed at
`GET/POST /api/v1/admin/input-source`.

Reversible in one click. This is the entire "hardware broke" remediation.

## Failure → response ladder

| # | Symptom | First move | Fallback |
|---|---|---|---|
| 1 | Webcam agent errors / wrong states | close the agent (it's a separate process — the API is unaffected) | Simulator panel → `simulated_only`, drive the demo with the rush simulator |
| 2 | ESP32 not posting (`-1`, `403`) | check Wi-Fi / key (see WIRING.md troubleshooting) | same toggle; IR bays go stale → server already shows them **low confidence** after missed heartbeats |
| 3 | Bay stuck in wrong state | Admin → Bay Editor → set state (manual source, still the same ingest path) | toggle `simulated_only` first if the sensor keeps flipping it back |
| 4 | Whole backend unreachable (local) | restart uvicorn (README one-liner) | switch frontend to the deployed URL — same app, same seed |
| 5 | Deployed API cold start slow | show the pre-opened dashboard tab (warm it 2 min before) | present from local `http://localhost:5310` |
| 6 | Total demo disaster | projector shows the deployed app; narrate a recorded walkthrough | — |

## Pre-demo gate (run 10 minutes before doors)

```bash
curl  $API/api/v1/health                      # ok
python scripts/smoke_test.py $API             # 21/21
python scripts/mock_device.py $API --toggle-test   # 11/11 (if hardware attached)
python edge_agent/selftest.py $API            # 7/7   (if webcam attached)
```

- Toggle test **must** be exercised once with hardware attached: set
  `simulated_only`, confirm a real device gets 409, set back to `live`.
  That's the exact motion you'll do on stage if a sensor misbehaves.
- Dashboard tab open and warmed; admin login already entered.
- Second laptop (or phone) on the deployed URL as backup.

## During the demo

1. Sensor misbehaving? → toggle `simulated_only`, say *"and that's the
   kill-switch — hardware input paused, simulation continues"*, keep going.
2. Allocation looks odd? → open the explanation panel; every decision
   carries its rule, candidates and rejection reasons — narrate it instead
   of hiding it.
3. Conflict alert appears? → that's reconciliation working; resolve it in
   Admin → Conflicts after the beat.
4. Never debug on stage beyond the toggle; anything deeper goes to the
   post-demo checklist.

## After the demo

- [ ] Set input source back to `live`
- [ ] `POST /api/v1/admin/demo/reset` to restore seeded occupancy
- [ ] Note what failed in `hardware/NOTES.md` (create if missing)
