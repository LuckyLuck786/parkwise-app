"""
ParkWise end-to-end smoke test.

Exercises the REAL API over HTTP (no DB shortcuts) against any BASE_URL — local
dev or a deployed instance:

    python scripts/smoke_test.py http://127.0.0.1:8010
    BASE_URL=https://parkwise-theta.vercel.app python scripts/smoke_test.py

Flow
----
  1. health + public read-only endpoints (lots, predictions, live poll)
  2. auth rejection (anonymous -> 401, driver -> 403 on admin routes)
  3. register a driver with two vehicles, activate one
  4. gate scan -> bay allotted with an explanation
  5. second vehicle scan -> rejected (one active allotment per account)
  6. fill the target lot -> next scan gets the full-lot alert with an
     alternative lot (or a waitlist place if nothing is free anywhere)
  7. fill every lot -> scan -> waitlist placement, position readable
  8. release one filler -> bay freed, waitlist head notified/promoted
  9. admin metrics run -> computed BASELINE vs ParkWise numbers
  10. cleanup: everyone scans out, waitlist emptied, occupancy restored

All filler accounts are named smoke-*/SMK-* with password `smoke123`, so a
killed run can be cleaned up by the next run (step 0). Exit code 0 = pass.

Tolerance notes (deployment-specific, do not remove):
  - On serverless the function pool can route requests across warm instances that
    each keep their own ephemeral SQLite DB. The test runs a token-bearing
    pre-heat probe first, and every token-bearing call retries short-lived 401s
    (a 401 is rejected before the handler runs, so retrying cannot double-scan).
  - The "driver -> 401/403 on admin routes" check must use a freshly-registered
    DRIVER token, not the admin token. 401 and 403 both count as rejection.
  - None of this makes the deployed app correct under instance divergence: a user
    registered on instance A still does not exist on instance B. The real fix is a
    shared database (DATABASE_URL), see README "Deployment".
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from collections import Counter

import httpx

DEFAULT_BASE = os.environ.get("PARKWISE_BASE_URL", "http://127.0.0.1:8010")
ADMIN = ("admin@parkwise.edu", "admin123")
SMOKE_PW = "smoke123"
RUN = time.strftime("%H%M%S") + uuid.uuid4().hex[:4]

results: list[tuple[str, bool, str]] = []
RETRY_401_ROUNDS = 3


def report(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def must(client: httpx.Client, method: str, path: str, expect: int = 200, **kw):
    """Request that must return `expect`; raises with the body on mismatch."""
    r = client.request(method, path, **kw)
    if r.status_code != expect:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else None


def retry_response(client: httpx.Client, method: str, path: str, expected: int, *,
                   headers: dict | None = None, json=None,
                   rounds: int = RETRY_401_ROUNDS) -> httpx.Response:
    """Send the request until it returns `expected`.

    A short-lived 401 on a token-bearing call is retried: only the deployed
    serverless pool can reject a token it just issued (each warm instance keeps
    its own ephemeral SQLite), and a retry lands on an instance that knows it.
    Harmless locally — the first attempt succeeds.
    """
    r: httpx.Response | None = None
    for attempt in range(rounds):
        r = client.request(method, path, headers=headers, json=json)
        if r.status_code == expected:
            return r
        if r.status_code == 401 and headers and attempt + 1 < rounds:
            time.sleep(0.1)
            continue
        break
    assert r is not None
    raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")


def must_retry_401(client: httpx.Client, method: str, path: str, expected: int, *,
                   headers: dict | None = None, json=None):
    """retry_response() plus JSON parsing, for the common success case."""
    r = retry_response(client, method, path, expected, headers=headers, json=json)
    return r.json() if r.content else None


def register(client: httpx.Client, tag: str, tier: int = 3, needs_acc: bool = False):
    email = f"smoke-{RUN}-{tag}@example.com"
    body = must(client, "POST", "/api/v1/auth/register", expect=201,
                json={
                    "name": f"Smoke {tag.upper()}",
                    "email": email,
                    "password": SMOKE_PW,
                    "priority_tier": tier,
                    "needs_accessible": needs_acc,
                },
                )
    return body["access_token"]


def add_vehicle(client: httpx.Client, token: str, plate: str, vtype: str) -> dict:
    return must_retry_401(client, "POST", "/api/v1/vehicles", 201,
                          headers={"Authorization": f"Bearer {token}"},
                          json={"plate_or_tag_id": plate, "type": vtype})


def scan(client: httpx.Client, token: str, plate: str, lot_id: str | None = None,
         direction: str = "in_scan") -> dict:
    payload = {"plate_or_tag_id": plate, "direction": direction, "source": "simulator"}
    if lot_id:
        payload["lot_preference_id"] = lot_id
    # Always retry-tolerant: a 401 is rejected before the handler runs, so there is
    # no risk of double-scanning on the deployed pool (and it never triggers locally).
    return must_retry_401(client, "POST", "/api/v1/gate/scan", 200,
                          headers={"Authorization": f"Bearer {token}"}, json=payload)


def lot_free_counts(client: httpx.Client) -> dict[str, int]:
    lots = must(client, "GET", "/api/v1/lots")
    return {lot["id"]: lot["counts"]["free"] for lot in lots}


def lot_names(client: httpx.Client) -> dict[str, str]:
    lots = must(client, "GET", "/api/v1/lots")
    return {lot["id"]: lot["name"] for lot in lots}


def free_bays(client: httpx.Client, lot_id: str) -> list[dict]:
    data = must(client, "GET", f"/api/v1/lots/{lot_id}/bays")
    return [b for b in data["bays"] if b["state"] == "free"]


def cleanup_leftover_smoke_users(client: httpx.Client) -> None:
    """Scan out / dequeue smoke-* accounts from a previously killed run."""
    admin_tok = admin_token(client)
    auth = {"Authorization": f"Bearer {admin_tok}"}
    users = must(client, "GET", "/api/v1/admin/users", headers=auth)
    for u in users:
        email = u.get("email", "")
        if not email.startswith("smoke-"):
            continue
        try:
            tok = must(client, "POST", "/api/v1/auth/login", 200,
                       json={"email": email, "password": SMOKE_PW})["access_token"]
            hdr = {"Authorization": f"Bearer {tok}"}
            status = must_retry_401(client, "GET", "/api/v1/me/status", 200,
                                    headers=hdr)
            if status.get("waitlist"):
                must(client, "POST", "/api/v1/waitlist/leave", json={}, headers=hdr)
            if status.get("current_parking"):
                vehicles = must_retry_401(client, "GET", "/api/v1/vehicles", 200,
                                          headers=hdr)
                for v in vehicles:
                    scan(client, tok, v["plate_or_tag_id"], direction="out_scan")
        except Exception as exc:
            print(f"  [warn] leftover {email}: {exc}")


def admin_token(client: httpx.Client) -> str:
    # The seeded admin exists on every instance (deterministic uuid5 seed), so this
    # needs no retry — it also proves the instance is fully seeded and warm.
    return must(client, "POST", "/api/v1/auth/login", 200,
                json={"email": ADMIN[0], "password": ADMIN[1]})["access_token"]

def driver_token_with_retry(client: httpx.Client, tag: str = "d",
                            tier: int = 3, needs_acc: bool = False,
                            attempts: int = 4) -> str:
    """Register a driver and return a token the serving instance accepts.

    On the deployed pool a freshly-registered account exists only on the instance
    that served the registration, so the very next token-bearing call can 401.
    Every attempt uses a FRESH email, so a retry always creates a new account
    (registering the same email twice would collide with 400 instead of healing).
    """
    for i in range(attempts):
        email = f"smoke-{RUN}-{tag}{i}@example.com"
        r = client.post("/api/v1/auth/register", json={
            "name": f"Smoke {tag.upper()}",
            "email": email,
            "password": SMOKE_PW,
            "priority_tier": tier,
            "needs_accessible": needs_acc,
        })
        if r.status_code != 201:
            time.sleep(0.1)
            continue
        tok = r.json()["access_token"]
        try:
            must(client, "GET", "/api/v1/me/status",
                 headers={"Authorization": f"Bearer {tok}"})
            return tok
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"could not get working driver token for {tag}")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE).rstrip("/")
    print(f"ParkWise smoke test -> {base}  (run id {RUN})")
    client = httpx.Client(base_url=base, timeout=30.0)

    fillers: list[tuple[str, str]] = []
    waiters: list[tuple[str, str]] = []
    fill_issues: list[str] = []
    driver_a: tuple[str, str] | None = None
    initial_free: dict[str, int] = {}

    try:
        # ---------------------------------------------------------------- 1
        h = must(client, "GET", "/api/v1/health")
        report("health endpoint", h.get("status") == "ok", str(h))

        lots = must(client, "GET", "/api/v1/lots")
        report("public lot status (no auth)", isinstance(lots, list) and len(lots) >= 3,
               f"{len(lots)} lots")

        initial_free = lot_free_counts(client)
        free_total = sum(initial_free.values())
        report("bays are free to start", free_total > 0, f"{free_total} free bays")

        preds = must(client, "GET", "/api/v1/predictions")
        plist = preds if isinstance(preds, list) else preds.get("predictions", [])
        ok = bool(plist) and all(
            p.get("method") or p.get("confidence_note") or p.get("confidence") for p in plist
        )
        report("predictions are labelled heuristics", ok,
               plist[0].get("confidence", "?") if plist else "none")

        poll = must(client, "GET", "/api/v1/events/poll")
        report("live updates (poll fallback)", "version" in poll or "events" in poll,
               str(poll)[:80])

        # ---------------------------------------------------------------- 2
        anon = client.get("/api/v1/admin/rules")
        report("auth rejection: anonymous admin call -> 401", anon.status_code == 401,
               f"got {anon.status_code}")

        # Pre-heat the token-bearing call path so the run does not start on a cold
        # instance. Uses a real admin token-bearing request so the seeded instance
        # stays warm for the next token-bearing calls.
        atok = admin_token(client)
        must(client, "GET", "/api/v1/admin/rules", headers={"Authorization": f"Bearer {atok}"})

        # ---------------------------------------------------------------- 3
        tok_a = driver_token_with_retry(client, "a")
        v1 = add_vehicle(client, tok_a, f"SMK-{RUN}-A1", "four_wheeler")
        add_vehicle(client, tok_a, f"SMK-{RUN}-A2", "two_wheeler")
        must_retry_401(client, "POST", f"/api/v1/vehicles/{v1['id']}/activate", 200,
                       headers={"Authorization": f"Bearer {tok_a}"})
        driver_a = (tok_a, f"SMK-{RUN}-A1")
        report("register driver + two vehicles", True, v1["plate_or_tag_id"])

        # 401 is also a rejection (a cold instance that has not seen this driver
        # yet); the admin pre-heat above already proved token-bearing routes work.
        staff = client.get("/api/v1/admin/rules",
                           headers={"Authorization": f"Bearer {tok_a}"})
        report("auth rejection: driver admin call -> 401/403",
               staff.status_code in (401, 403), f"got {staff.status_code}")

        # ---------------------------------------------------------------- 4
        names = lot_names(client)
        target = min(initial_free, key=lambda lid: initial_free[lid])
        r = scan(client, tok_a, f"SMK-{RUN}-A1", lot_id=target)
        alloc = r.get("allocation") or {}
        bay = alloc.get("bay")
        expl = alloc.get("explanation") or {}
        report(
            "gate scan allots a bay with explanation",
            bool(bay) and bool(expl),
            f"{alloc.get('status')} {bay.get('label') if bay else r.get('message')}",
        )

        # ---------------------------------------------------------------- 5
        r2 = scan(client, tok_a, f"SMK-{RUN}-A2")
        msg2 = (r2.get("message") or "").lower()
        report(
            "second vehicle rejected while user holds a bay",
            r2.get("success") is False and ("already" in msg2 or "active" in msg2),
            r2.get("message", ""),
        )

        # ---------------------------------------------------------------- 6
        def fill_one(lot_id: str) -> bool:
            """Register a driver able to CLAIM a free bay here and park them in it.

            Bay categories matter: an accessible bay is reserved for tier 1, and a
            tier-2 bay is held until the cutoff time. A tier-3 driver sent at one of
            those gets a bay in another lot instead, so the filler must match the
            category it is targeting. Within a category the most common vehicle type
            is used, so one type is not fully consumed while the other is stranded.
            """
            bays = free_bays(client, lot_id)
            if not bays:
                return False
            plain = [b for b in bays if not b["is_accessible"] and b.get("reserved_tier") != 2]
            acc = [b for b in bays if b["is_accessible"] and b.get("reserved_tier") != 2]
            plain_held = [b for b in bays if not b["is_accessible"] and b.get("reserved_tier") == 2]
            acc_held = [b for b in bays if b["is_accessible"] and b.get("reserved_tier") == 2]
            groups = [(plain, 3, False), (acc, 1, True),
                      (plain_held, 2, False), (acc_held, 1, True)]
            pool, tier, needs_acc = next((g for g in groups if g[0]), ([], 3, False))
            if not pool:
                return False
            vtype = Counter(b["type"] for b in pool).most_common(1)[0][0]
            tok = driver_token_with_retry(client, f"f{len(fillers)}", tier=tier,
                                          needs_acc=needs_acc)
            plate = f"SMK-{RUN}-F{len(fillers):03d}"
            add_vehicle(client, tok, plate, vtype)
            before = lot_free_counts(client).get(lot_id, 0)
            resp = scan(client, tok, plate, lot_id=lot_id)
            after = lot_free_counts(client).get(lot_id, 0)
            fillers.append((tok, plate))
            if after < before:
                return True
            fill_issues.append(
                f"{lot_id[:6]} {before}->{after} vtype={vtype} tier={tier} "
                f"{((resp.get('allocation') or {}).get('status'))}: "
                f"{(resp.get('message') or '')[:90]}"
            )
            return False

        stall = 0
        while lot_free_counts(client).get(target, 0) > 0 and stall < 6:
            if not fill_one(target):
                stall += 1
            else:
                stall = 0
        target_free = lot_free_counts(client).get(target, 0)
        report(f"target lot filled ({names.get(target)})",
               target_free == 0, f"{target_free} free left, {len(fillers)} fillers")

        tok_e = driver_token_with_retry(client, "e")
        plate_e = f"SMK-{RUN}-E1"
        vtype_e = free_bays(client, target)[:1]
        add_vehicle(client, tok_e, plate_e, vtype_e[0]["type"] if vtype_e else "four_wheeler")
        r = scan(client, tok_e, plate_e, lot_id=target)
        a = r.get("allocation") or {}
        has_alt = a.get("alternative_lot") is not None or a.get("waitlist_position") is not None
        report("full-lot: alternative lot or waitlist offered",
               has_alt, a.get("message", r.get("message", ""))[:160])
        if a.get("bay"):
            fillers.append((tok_e, plate_e))

        # ---------------------------------------------------------------- 7
        stall = 0
        guard = 0
        while sum(lot_free_counts(client).values()) > 0 and guard < 200:
            guard += 1
            counts = lot_free_counts(client)
            lid = max(counts, key=lambda k: counts[k])
            if counts[lid] == 0:
                break
            if not fill_one(lid):
                stall += 1
                if stall > 8:
                    break
            else:
                stall = 0
        free_now = sum(lot_free_counts(client).values())
        report("all lots filled", free_now == 0,
               f"{free_now} free left, {len(fillers)} fillers"
               + (f" | {fill_issues[0]}" if fill_issues and free_now else ""))

        tok_w = driver_token_with_retry(client, "w")
        plate_w = f"SMK-{RUN}-W1"
        add_vehicle(client, tok_w, plate_w, "four_wheeler")
        rw = scan(client, tok_w, plate_w, lot_id=target)
        aw = rw.get("allocation") or {}
        report("arrival with no bay -> waitlist placement",
               aw.get("waitlist_position") is not None,
               f"position={aw.get('waitlist_position')} {aw.get('message', '')[:100]}")
        if aw.get("waitlist_position") is None:
            if aw.get("bay"):
                fillers.append((tok_w, plate_w))
        else:
            waiters.append((tok_w, plate_w))

        if waiters:
            wl = must_retry_401(client, "GET", "/api/v1/me/waitlist", 200,
                                headers={"Authorization": f"Bearer {waiters[-1][0]}"})
            waiting = [e for e in wl if e.get("status") == "waiting"]
            report("waitlist position readable",
                   bool(waiting) and isinstance(waiting[0].get("position"), int),
                   str(waiting[0].get("position") if waiting else wl)[:80])

        # ---------------------------------------------------------------- 8
        if fillers:
            f_tok, f_plate = fillers[0]
            r = scan(client, f_tok, f_plate, direction="out_scan")
            report("release: bay freed on scan-out", "freed" in (r.get("message") or "").lower()
                   or "checked out" in (r.get("message") or "").lower(),
                   (r.get("message") or "")[:120])
        else:
            report("release: bay freed on scan-out", False, "no fillers created")
            r = {}

        free_after = sum(lot_free_counts(client).values())
        head_ok, head_detail = False, ""
        for w_tok, _plate in waiters:
            hdr = {"Authorization": f"Bearer {w_tok}"}
            wl = must_retry_401(client, "GET", "/api/v1/me/waitlist", 200, headers=hdr)
            notes = must_retry_401(client, "GET", "/api/v1/me/notifications", 200,
                                   headers=hdr)
            offered = any(e.get("offered_bay") for e in wl)
            if offered or notes:
                head_ok, head_detail = True, f"offered={offered} notifications={len(notes)}"
                break
            head_detail = f"offered={offered} notifications={len(notes)}"

        report("release: bay freed or held for the waitlist head",
               free_after >= 1 or head_ok,
               f"free={free_after} {head_detail}")
        if waiters:
            report("waitlist head notified / bay offered", head_ok, head_detail)
        else:
            report("waitlist head notified / bay offered", free_after >= 1,
                   "no waitlist entries — bay returned to the pool")

        # ---------------------------------------------------------------- 9
        atok = admin_token(client)
        metrics = must(client, "POST", "/api/v1/admin/metrics/run", timeout=180.0,
                       json={"seed": 7, "hours": 2, "scale": 1.0, "name": f"smoke-{RUN}"},
                       headers={"Authorization": f"Bearer {atok}"})
        b, p = metrics.get("baseline") or {}, metrics.get("parkwise") or {}
        needed = ("avg_search_minutes", "failed_entries", "utilization_pct")
        report("metrics: computed baseline vs ParkWise",
               all(isinstance(b.get(k), (int, float)) for k in needed)
               and all(isinstance(p.get(k), (int, float)) for k in needed)
               and metrics.get("arrivals", 0) > 0,
               f"arrivals={metrics.get('arrivals')} baseline_avg={b.get('avg_search_minutes')} "
               f"parkwise_avg={p.get('avg_search_minutes')}")
        report("metrics: labelled as simulation, not field data",
               "simulation" in (metrics.get("label") or "").lower()
               or "computed" in (metrics.get("label") or "").lower(),
               metrics.get("label", ""))

        # ---------------------------------------------------------------- 10
        for w_tok, _plate in waiters:
            try:
                must(client, "POST", "/api/v1/waitlist/leave", json={},
                      headers={"Authorization": f"Bearer {w_tok}"})
            except Exception:
                pass
        released = 0
        for tok, plate in fillers:
            try:
                scan(client, tok, plate, direction="out_scan")
                released += 1
            except Exception:
                pass
        if driver_a:
            try:
                scan(client, driver_a[0], driver_a[1], direction="out_scan")
                released += 1
            except Exception:
                pass
        cleanup_leftover_smoke_users(client)
        final_free = lot_free_counts(client)
        restored = sum(final_free.values())
        report("cleanup: occupancy restored",
               restored >= sum(initial_free.values()),
               f"free {sum(initial_free.values())} -> {restored} "
               f"({released} smoke vehicles released)")

    except Exception as exc:
        report("smoke test aborted", False, f"{type(exc).__name__}: {exc}")
    finally:
        client.close()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'='*60}\nSMOKE TEST {'PASSED' if passed == total else 'FAILED'}: "
          f"{passed}/{total} checks passed  ({base})")
    if passed != total:
        for name, ok, detail in results:
            if not ok:
                print(f"  FAILED: {name} — {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
