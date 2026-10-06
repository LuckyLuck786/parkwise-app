#!/usr/bin/env python3
"""ParkWise simulator — drives the SAME ingestion endpoints hardware uses.

There is no special-case code path for the simulator: every call here is an
HTTP POST to /api/v1/ingest/* authenticated with a device API key, exactly
like the ESP32 IR agent, the webcam edge agent or a manual admin override.

Examples
--------
    # one full arrival: gate scan-in (allotment) + sensor says the bay is now used
    python scripts/simulate.py arrival --tag KA-01-AB-1234 --dest "Medical Center" --lot "Lot A"

    # departure: sensor says the bay emptied, then the gate scan-out
    python scripts/simulate.py departure --tag KA-01-AB-1234

    # a raw IR/webcam style bay event
    python scripts/simulate.py bay-event --bay-id <uuid> --occupied true --source ir_sensor

    # morning rush: N vehicles, each through scan-in + arrival
    python scripts/simulate.py rush --count 20 --start 08:30 --admin admin@parkwise.edu:admin123

    # device heartbeat
    python scripts/simulate.py heartbeat
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

DEFAULT_BASE_URL = os.environ.get("PARKWISE_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_API_KEY = os.environ.get("PARKWISE_DEVICE_API_KEY", "sim-key-lot-a")


def _headers(api_key: str) -> Dict[str, str]:
    return {"X-API-Key": api_key}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class ParkWiseSim:
    def __init__(self, base_url: str, api_key: str, verbose: bool = True):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.verbose = verbose
        self.client = httpx.Client(timeout=20.0)

    # ------------------------------------------------------------- helpers --
    def log(self, *args: Any) -> None:
        if self.verbose:
            print(*args)

    def _check(self, resp: httpx.Response) -> Any:
        if resp.status_code >= 400:
            raise RuntimeError(f"{resp.request.method} {resp.url.path} -> "
                               f"{resp.status_code}: {resp.text[:400]}")
        return resp.json()

    def login(self, credentials: str) -> str:
        """email:password -> JWT (for admin-only lookups like the rush roster)."""
        email, _, password = credentials.partition(":")
        data = {"email": email, "password": password}
        resp = self.client.post(f"{self.base_url}/api/v1/auth/login", json=data)
        token = self._check(resp)["access_token"]
        return token

    def auth_headers(self, credentials: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.login(credentials)}"}

    # ---------------------------------------------------------- ingest API --
    def gate_scan(self, tag: str, direction: str = "in_scan",
                  dest: Optional[str] = None, lot: Optional[str] = None,
                  source: str = "simulator") -> Dict[str, Any]:
        payload = {
            "vehicle_tag_id": tag,
            "direction": direction,
            "source": source,
            "ts": _ts(),
        }
        if dest:
            payload["destination_building_id"] = dest
        if lot:
            payload["lot_preference_id"] = lot
        resp = self.client.post(
            f"{self.base_url}/api/v1/ingest/gate-scan",
            json=payload, headers=_headers(self.api_key),
        )
        return self._check(resp)

    def bay_event(self, bay_id: str, occupied: bool, confidence: float = 1.0,
                  source: str = "simulator") -> Dict[str, Any]:
        payload = {
            "bay_id": bay_id,
            "occupied": occupied,
            "source": source,
            "confidence": confidence,
            "ts": _ts(),
        }
        resp = self.client.post(
            f"{self.base_url}/api/v1/ingest/bay-event",
            json=payload, headers=_headers(self.api_key),
        )
        return self._check(resp)

    def heartbeat(self, status: str = "online") -> Dict[str, Any]:
        resp = self.client.post(
            f"{self.base_url}/api/v1/ingest/heartbeat",
            json={"device_id": "simulator", "status": status, "ts": _ts()},
            headers=_headers(self.api_key),
        )
        return self._check(resp)

    # -------------------------------------------------------- lookup helper --
    def resolve(self, name: str, kind: str) -> Optional[str]:
        """Resolve a human name ('Lot A', 'Medical Center') to an id."""
        path = "/api/v1/lots" if kind == "lot" else "/api/v1/buildings"
        resp = self.client.get(f"{self.base_url}{path}")
        for item in self._check(resp):
            if item["name"].lower() == name.lower():
                return item["id"]
        return None

    def vehicles(self, credentials: str) -> List[Dict[str, Any]]:
        resp = self.client.get(
            f"{self.base_url}/api/v1/staff/vehicles",
            headers=self.auth_headers(credentials),
        )
        return self._check(resp)

    # ------------------------------------------------------------- flows ----
    def arrival(self, tag: str, dest: Optional[str], lot: Optional[str],
                source: str = "simulator") -> Dict[str, Any]:
        dest_id = self.resolve(dest, "building") if dest else None
        lot_id = self.resolve(lot, "lot") if lot else None
        scan = self.gate_scan(tag, "in_scan", dest_id, lot_id, source)
        self.log(f"  scan-in {tag}: {scan['message']}")
        alloc = scan.get("allocation_result") or {}
        bay = (alloc.get("bay") or {}) if isinstance(alloc, dict) else None
        if bay:
            # the IR/webcam sensor now observes the car in the bay
            ev = self.bay_event(bay["id"], True, confidence=0.97, source=source)
            self.log(f"  sensor occupied {bay.get('lot_name')}/{bay.get('label')} "
                     f"(conflict={ev['conflict_detected']})")
        return scan

    def departure(self, tag: str, source: str = "simulator") -> Dict[str, Any]:
        # find the open allotment's bay via /me-style admin view if available
        scan = self.gate_scan(tag, "out_scan", source=source)
        self.log(f"  scan-out {tag}: {scan['message']}")
        return scan

    def rush(self, count: int, start: str, credentials: str,
             dest: Optional[str], lot: Optional[str], gap_seconds: float = 0.0,
             source: str = "simulator") -> List[Dict[str, Any]]:
        roster = self.vehicles(credentials)
        random.shuffle(roster)
        chosen = roster[:count]
        self.log(f"Morning rush: {len(chosen)} vehicles from {start}")
        results = []
        for i, veh in enumerate(chosen, 1):
            tag = veh["plate_or_tag_id"]
            try:
                res = self.arrival(tag, dest, lot, source)
                results.append(res)
            except RuntimeError as exc:
                self.log(f"  [{i}] {tag}: FAILED {exc}")
            if gap_seconds:
                time.sleep(gap_seconds)
        return results


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ParkWise simulator (HTTP ingestion endpoints)")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--api-key", default=DEFAULT_API_KEY)
    p.add_argument("--quiet", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan-in", help="gate scan-in (allotment)")
    s.add_argument("--tag", required=True)
    s.add_argument("--dest", help="building name")
    s.add_argument("--lot", help="lot name")
    s.add_argument("--source", default="simulator")

    s = sub.add_parser("scan-out", help="gate scan-out (release)")
    s.add_argument("--tag", required=True)
    s.add_argument("--source", default="simulator")

    s = sub.add_parser("arrival", help="scan-in + sensor occupancy in one step")
    s.add_argument("--tag", required=True)
    s.add_argument("--dest", help="building name")
    s.add_argument("--lot", help="lot name")
    s.add_argument("--source", default="simulator")

    s = sub.add_parser("departure", help="scan-out (frees the bay, notifies waitlist)")
    s.add_argument("--tag", required=True)
    s.add_argument("--source", default="simulator")

    s = sub.add_parser("bay-event", help="raw bay occupancy event")
    s.add_argument("--bay-id", required=True)
    s.add_argument("--occupied", required=True, choices=["true", "false"])
    s.add_argument("--confidence", type=float, default=1.0)
    s.add_argument("--source", default="simulator",
                   choices=["simulator", "ir_sensor", "webcam", "manual"])

    s = sub.add_parser("heartbeat", help="device heartbeat")
    s.add_argument("--status", default="online")

    s = sub.add_parser("rush", help="morning rush through the ingest endpoints")
    s.add_argument("--count", type=int, default=20)
    s.add_argument("--start", default="08:30")
    s.add_argument("--dest", help="building name")
    s.add_argument("--lot", help="lot name")
    s.add_argument("--admin", default="admin@parkwise.edu:admin123",
                   help="email:password used to fetch the vehicle roster")
    s.add_argument("--gap", type=float, default=0.0, help="seconds between vehicles")
    s.add_argument("--source", default="simulator")

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    sim = ParkWiseSim(args.base_url, args.api_key, verbose=not args.quiet)

    if args.cmd == "scan-in":
        out = sim.gate_scan(args.tag, "in_scan",
                            sim.resolve(args.dest, "building") if args.dest else None,
                            sim.resolve(args.lot, "lot") if args.lot else None,
                            args.source)
        print(json.dumps(out, indent=2, default=str))
    elif args.cmd == "scan-out":
        print(json.dumps(sim.gate_scan(args.tag, "out_scan", source=args.source),
                         indent=2, default=str))
    elif args.cmd == "arrival":
        sim.arrival(args.tag, args.dest, args.lot, args.source)
    elif args.cmd == "departure":
        sim.departure(args.tag, args.source)
    elif args.cmd == "bay-event":
        out = sim.bay_event(args.bay_id, args.occupied == "true",
                            args.confidence, args.source)
        print(json.dumps(out, indent=2, default=str))
    elif args.cmd == "heartbeat":
        print(json.dumps(sim.heartbeat(args.status), indent=2, default=str))
    elif args.cmd == "rush":
        sim.rush(args.count, args.start, args.admin, args.dest, args.lot,
                 args.gap, args.source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
