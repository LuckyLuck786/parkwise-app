# ParkWise — 3-Minute Demo Script

Runs on simulated data end-to-end. Hardware variant at the bottom.
Stage props: projector with the app open (deployed + local tabs warmed).

**Logins (demo):**

| Role | Email | Password |
|---|---|---|
| Admin | `admin@parkwise.edu` | `admin123` |
| Gate operator | `gate1@parkwise.edu` | `gate123` |
| Driver (Tier 1, accessible) | `priya.sharma@example.com` | `pass123` |
| Driver (Tier 2, faculty) | `anand.rao@example.com` | `pass123` |
| Driver (Tier 3, student) | `amit.kumar@example.com` | `pass123` |

In-app demo buttons on the login page fill these in with one click.

---

## 0:00 — The problem (15 s)

> "Campus parking at 9 AM: drivers circle full lots, an accessible bay is
> taken by someone who didn't need it, and the gate guard has no idea what's
> free. ParkWise allocates every bay by priority, distance and live sensor
> data — and can explain every decision."

**Show:** Live Lot Map (color-coded bays, fill gauges, predicted full time).

## 0:30 — Register, scan, allot with explanation (30 s)

1. Register a demo driver, add **two vehicles** (a car + a bike).
2. Pick today's vehicle, set destination = Engineering.
3. Gate Kiosk: scan vehicle #1 → **bay allotted (Lot A, nearest the
   destination)** with the explanation panel open:
   rule applied · candidates considered · why this bay · why others rejected.
4. Try scanning vehicle #2 → **rejected**: "one active allotment per
   account" (same account can't hold two bays).

> "Every line here is a rule you can read and edit — no black box."

## 1:00 — Morning rush fills the lot (30 s)

1. Admin → Simulator → **Run morning rush** (count 18, gap 2 s, Lot A).
2. Watch the Live Lot Map fill; predicted-full warning was already showing.
3. Next gate scan → **"Lot A is full"** + alternative lot offer with
   estimated drive time (or waitlist if everywhere is full).

> "Immediate notification, alternative offered — not a driver circling for
> 20 minutes."

## 1:45 — Tier 1 wins in a rush (30 s)

1. Log in as **Priya (Tier 1, needs accessible)** or scan her tag at the kiosk
   during the rush.
2. She gets the **nearest accessible bay** (reserved quota) despite the lot
   being effectively full for everyone else.

> "Tier quotas are held capacity, never eviction: nobody's car is ever
> moved. Faculty/service bays release after the 10:00 cut-off, accessible
> bays stay reserved."

## 2:15 — No-show released, waitlist notified (25 s)

1. Simulator → **Release no-shows now** (allotments past the 10-min grace
   with no arrival return to the pool — reason recorded).
2. The waitlist head gets an in-app notification ("bay held for you, 5 min
   to accept") and the bay shows as **offered**, then allotted.

> "A bay nobody occupies for ten minutes goes back to the pool and the next
> driver in line — ordered by tier, then arrival — is told immediately."

## 2:40 — Baseline vs ParkWise (20 s)

1. Admin → Metrics → **Run comparison** (same arrival sequence, two
   policies).
2. Read the computed numbers: average search time, failed/wasted entries,
   utilization, Tier-1 access success.

> "Same arrivals, simulated twice: first-come-first-served versus ParkWise.
> These numbers come out of the run — the model assumptions are labeled on
> the page. It's statistics and rules, not AI."

**Optional close (if time):** Admin → Audit log → open one entry →
"this is the whole decision trail."

---

## When the hardware is attached

Same beats, replace the simulated actions:

| Beat | Instead of… | Do… |
|---|---|---|
| 0:30 | kiosk button scan | place a toy car with QR tag on the gate line; webcam agent reads it and posts the gate scan (or press the IR trip on the gate sensor) |
| 1:00 rush | simulator rush | place cars one by one into bays — IR/webcam bay-events light up the Live Lot Map live |
| 1:45 | Priya's tag scan | move Priya's tagged car in; her accessible bay shows occupied by sensor within a beat |
| 2:15 | "release no-shows" | lift the no-show car out; sensor frees the bay, waitlist head notified automatically |
| failure | — | if a sensor misbehaves: Admin → Simulator → **Input source → Simulated only** (one click pauses hardware, keeps the demo running) — say it out loud, it's the failure plan working |

Pre-demo gate (10 min before): `scripts/smoke_test.py` 21/21,
`scripts/mock_device.py --toggle-test` 11/11, edge selftest 7/7.
Full ladder: `hardware/DEMO_DAY_FAILURE_PLAN.md`.
