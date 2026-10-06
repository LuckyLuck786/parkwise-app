import { useCallback, useEffect, useState } from "react";
import {
  AlarmClock,
  CalendarClock,
  Play,
  RotateCcw,
  Timer,
  TriangleAlert,
  Zap,
} from "lucide-react";
import { api, ApiError } from "../services/api";
import { useLive } from "../hooks/useLive";
import { ErrorState, LoadingState, SimulatedBadge, StatusPill } from "../components/ui";
import { Building, DemoState, LotSummary } from "../types";

interface LogLine {
  id: number;
  label: string;
  detail: string;
  ok: boolean;
}

let logCounter = 0;

export default function Simulator() {
  const [state, setState] = useState<DemoState | null>(null);
  const [lots, setLots] = useState<LotSummary[]>([]);
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [log, setLog] = useState<LogLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [rushCount, setRushCount] = useState(15);
  const [rushGap, setRushGap] = useState(15);
  const [rushLot, setRushLot] = useState("");
  const [rushDest, setRushDest] = useState("");
  const [speed, setSpeed] = useState(1);
  const [setTime, setSetTime] = useState("");

  const load = useCallback(() => {
    api<DemoState>("/api/v1/admin/demo")
      .then((d) => {
        setState(d);
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load demo state"));
    api<LotSummary[]>("/api/v1/lots", { auth: false }).then(setLots).catch(() => undefined);
    api<Building[]>("/api/v1/buildings", { auth: false }).then(setBuildings).catch(() => undefined);
  }, []);

  useLive(load);
  useEffect(load, [load]);

  const addLog = (label: string, detail: string, ok = true) => {
    setLog((prev) => [{ id: ++logCounter, label, detail, ok }, ...prev].slice(0, 30));
  };

  const call = async (path: string, body: unknown, label: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await api<Record<string, unknown>>(path, { method: "POST", body });
      addLog(label, JSON.stringify(res).slice(0, 400), true);
      load();
      return res;
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Request failed";
      addLog(label, msg, false);
      setError(msg);
      return null;
    } finally {
      setBusy(false);
    }
  };

  const runRush = async () => {
    const res = await call(
      "/api/v1/admin/demo/rush",
      {
        count: rushCount,
        gap_seconds: rushGap,
        lot_id: rushLot || null,
        dest_building_id: rushDest || null,
      },
      `Morning rush (${rushCount} vehicles)`,
    );
    if (res) {
      addLog(
        "Rush result",
        `${res.allotted ?? "?"} allotted · ${res.waitlisted ?? "?"} waitlisted`,
        true,
      );
    }
  };

  if (error && !state) return <ErrorState message={error} onRetry={load} />;
  if (!state) return <LoadingState label="Loading simulator controls…" />;

  const clock = new Date(state.clock.virtual_now + "Z");
  const real = new Date(state.clock.real_now + "Z");
  const offsetMin = Math.round((clock.getTime() - real.getTime()) / 60000);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Simulator</h1>
          <p className="text-sm text-slate-600">
            Demo clock, rush scenarios and fault injection. Every action runs through the normal
            pipeline and is audit-logged.
          </p>
        </div>
        <SimulatedBadge note="Simulator actions drive the same ingestion and reconciliation code as hardware." />
      </div>

      {error && <ErrorState message={error} />}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="card">
          <p className="text-xs font-semibold uppercase text-slate-500">Virtual clock</p>
          <p className="text-2xl font-bold tabular-nums text-slate-900">
            {Number.isNaN(clock.getTime()) ? state.clock.virtual_now : clock.toISOString().slice(11, 19)}
          </p>
          <p className="text-xs text-slate-500">
            UTC · {offsetMin === 0 ? "in sync with real time" : `${offsetMin > 0 ? "+" : ""}${offsetMin} min vs real`}
          </p>
        </div>
        <div className="card">
          <p className="text-xs font-semibold uppercase text-slate-500">Free bays</p>
          <p className="text-2xl font-bold tabular-nums text-slate-900">{state.counts.free_bays}</p>
        </div>
        <div className="card">
          <p className="text-xs font-semibold uppercase text-slate-500">Active allotments</p>
          <p className="text-2xl font-bold tabular-nums text-slate-900">{state.counts.active_allotments}</p>
        </div>
        <div className="card">
          <p className="text-xs font-semibold uppercase text-slate-500">Waitlist</p>
          <p className="text-2xl font-bold tabular-nums text-slate-900">{state.counts.waitlist}</p>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="card">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold text-slate-800">
            <AlarmClock className="h-5 w-5 text-brand-600" aria-hidden /> Demo clock
          </h2>

          <label className="label" htmlFor="speed">Speed</label>
          <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Clock speed">
            {[1, 5, 30, 60, 300].map((s) => (
              <button
                key={s}
                type="button"
                className={speed === s ? "btn-primary" : "btn-secondary"}
                onClick={() => {
                  setSpeed(s);
                  void api("/api/v1/admin/demo/clock", { method: "POST", body: { speed: s } })
                    .then((r) => addLog("Clock speed", `${s}×`, true))
                    .then(load)
                    .catch((e) => addLog("Clock speed", String(e), false));
                }}
                aria-pressed={speed === s}
              >
                {s}×
              </button>
            ))}
          </div>

          <div className="mb-3 flex flex-wrap gap-2">
            {[
              ["−1h", -60, "back 1 hour"],
              ["−15m", -15, "back 15 minutes"],
              ["+15m", 15, "forward 15 minutes"],
              ["+1h", 60, "forward 1 hour"],
              ["+8h", 480, "forward 8 hours"],
            ].map(([label, mins, spoken]) => (
              <button
                key={String(label)}
                type="button"
                className="btn-secondary"
                onClick={() =>
                  void api("/api/v1/admin/demo/clock", { method: "POST", body: { jump_minutes: mins } })
                    .then(() => addLog("Clock jump", String(label), true))
                    .then(load)
                    .catch((e) => addLog("Clock jump", String(e), false))
                }
              >
                <span aria-hidden>{label}</span>
                <span className="sr-only">Jump clock {spoken}</span>
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-end gap-2">
            <div className="flex-1">
              <label className="label" htmlFor="settime">Set time</label>
              <input
                id="settime"
                type="datetime-local"
                className="input"
                value={setTime}
                onChange={(e) => setSetTime(e.target.value)}
              />
            </div>
            <button
              type="button"
              className="btn-primary"
              disabled={!setTime}
              onClick={() =>
                void api("/api/v1/admin/demo/clock", {
                  method: "POST",
                  body: { set_time: new Date(setTime + "Z").toISOString() },
                })
                  .then(() => addLog("Clock set", setTime, true))
                  .then(load)
                  .catch((e) => addLog("Clock set", String(e), false))
              }
            >
              <CalendarClock className="h-4 w-4" aria-hidden /> Apply
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() =>
                void api("/api/v1/admin/demo/clock", { method: "POST", body: { reset: true } })
                  .then(() => addLog("Clock reset", "back to real time", true))
                  .then(load)
                  .catch((e) => addLog("Clock reset", String(e), false))
              }
            >
              <RotateCcw className="h-4 w-4" aria-hidden /> Reset
            </button>
          </div>
        </section>

        <section className="card">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold text-slate-800">
            <Play className="h-5 w-5 text-brand-600" aria-hidden /> Morning rush
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="count">Vehicles</label>
              <input id="count" type="number" min={1} max={200} className="input" value={rushCount}
                onChange={(e) => setRushCount(Number(e.target.value))} />
            </div>
            <div>
              <label className="label" htmlFor="gap">Seconds between scans</label>
              <input id="gap" type="number" min={0} max={600} className="input" value={rushGap}
                onChange={(e) => setRushGap(Number(e.target.value))} />
            </div>
            <div>
              <label className="label" htmlFor="rushlot">Target lot</label>
              <select id="rushlot" className="input" value={rushLot} onChange={(e) => setRushLot(e.target.value)}>
                <option value="">Auto (by destination)</option>
                {lots.map((l) => (
                  <option key={l.id} value={l.id}>{l.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="rushdest">Destination</label>
              <select id="rushdest" className="input" value={rushDest} onChange={(e) => setRushDest(e.target.value)}>
                <option value="">Random</option>
                {buildings.map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
            </div>
          </div>
          <button type="button" className="btn-primary mt-3 w-full" onClick={runRush} disabled={busy}>
            <Zap className="h-4 w-4" aria-hidden /> {busy ? "Running…" : "Run morning rush"}
          </button>

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary"
              disabled={busy}
              onClick={() => void call("/api/v1/admin/demo/release-noshows", {}, "Release no-shows")}
            >
              <Timer className="h-4 w-4" aria-hidden /> Release no-shows now
            </button>
            <button
              type="button"
              className="btn-danger"
              disabled={busy}
              onClick={() => {
                if (window.confirm("Reset the demo? Live state clears; users, rules and history stay.")) {
                  void call("/api/v1/admin/demo/reset", {}, "Reset demo");
                }
              }}
            >
              <RotateCcw className="h-4 w-4" aria-hidden /> Reset demo
            </button>
          </div>
        </section>
      </div>

      <section className="card">
        <h2 className="mb-3 flex items-center gap-2 text-lg font-bold text-slate-800">
          <TriangleAlert className="h-5 w-5 text-amber-600" aria-hidden /> Inject faults
        </h2>
        <p className="mb-3 text-sm text-slate-600">
          Faults are applied the same way a real operator or a flaky sensor would change state —
          the reconcile layer decides what it means and raises the alert.
        </p>
        <div className="flex flex-wrap gap-2">
          {[
            ["sensor_offline", "Take a sensor offline"],
            ["sensor_online", "Bring sensors back online"],
            ["bay_blocked", "Block a bay"],
            ["bay_unblock", "Unblock a bay"],
            ["wrong_bay", "Wrong-bay parking"],
            ["unauthorized", "Occupied with no scan"],
          ].map(([fault, label]) => (
            <button
              key={fault}
              type="button"
              className={fault === "sensor_offline" || fault === "unauthorized" ? "btn-danger" : "btn-secondary"}
              disabled={busy}
              onClick={() => void call("/api/v1/admin/demo/fault", { fault }, `Fault: ${label}`)}
            >
              {label}
            </button>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-800">Activity log</h2>
          <StatusPill tone="slate">{log.length} entries</StatusPill>
        </div>
        {log.length === 0 ? (
          <p className="text-sm text-slate-500">Actions you run appear here.</p>
        ) : (
          <ul className="max-h-72 space-y-1 overflow-y-auto text-sm">
            {log.map((line) => (
              <li key={line.id} className={`rounded border px-2 py-1 ${line.ok ? "border-slate-200 bg-slate-50" : "border-rose-300 bg-rose-50"}`}>
                <span className="font-semibold">{line.label}</span>{" "}
                <span className={line.ok ? "text-slate-600" : "text-rose-700"}>{line.detail}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
