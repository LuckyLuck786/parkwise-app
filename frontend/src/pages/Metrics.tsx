import { FormEvent, useCallback, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Play, Info } from "lucide-react";
import { api, ApiError } from "../services/api";
import { ErrorState, LoadingState, SimulatedBadge, StatusPill } from "../components/ui";
import { MetricsRun, PolicyMetrics } from "../types";

interface MetricsResponse {
  run: MetricsRun | null;
  message?: string;
}

const ROWS: { key: keyof PolicyMetrics; label: string; format: (v: unknown) => string; better: "lower" | "higher" | "none" }[] = [
  { key: "parked", label: "Vehicles parked", format: (v) => String(v), better: "higher" },
  { key: "failed_entries", label: "Failed entries (gave up)", format: (v) => String(v), better: "lower" },
  { key: "wasted_entries", label: "Wasted lot entries", format: (v) => String(v), better: "lower" },
  { key: "avg_search_minutes", label: "Avg search time (min)", format: (v) => (v == null ? "—" : Number(v).toFixed(2)), better: "lower" },
  { key: "p90_search_minutes", label: "P90 search time (min)", format: (v) => (v == null ? "—" : Number(v).toFixed(2)), better: "lower" },
  { key: "utilization_pct", label: "Utilisation (%)", format: (v) => `${v}%`, better: "higher" },
  { key: "tier1_access_success_pct", label: "Tier 1 accessible-bay success (%)", format: (v) => `${v}%`, better: "higher" },
  { key: "waitlisted", label: "Waitlisted", format: (v) => String(v), better: "none" },
  { key: "waitlist_resolved", label: "Waitlist served", format: (v) => String(v), better: "higher" },
];

export default function Metrics() {
  const [run, setRun] = useState<MetricsRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [seed, setSeed] = useState(42);
  const [hours, setHours] = useState(5);
  const [scale, setScale] = useState(3);

  const load = useCallback(() => {
    api<MetricsResponse>("/api/v1/metrics", { auth: false })
      .then((res) => {
        setRun(res.run);
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load metrics"));
  }, []);

  useEffect(load, [load]);

  const startRun = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api<MetricsRun>("/api/v1/admin/metrics/run", {
        method: "POST",
        body: { seed, hours, scale, name: `manual-${seed}` },
      });
      setRun(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Simulation failed");
    } finally {
      setBusy(false);
    }
  };

  if (error && !run) return <ErrorState message={error} onRetry={load} />;
  if (!run && !error) return <LoadingState label="Loading metrics…" />;

  const chartData = run
    ? ROWS.filter((r) => ["failed_entries", "wasted_entries", "avg_search_minutes", "tier1_access_success_pct", "utilization_pct"].includes(r.key as string)).map((r) => ({
        metric: r.label.replace(" (%)", "").replace(" (min)", ""),
        baseline: Number((run.baseline[r.key] as number) ?? 0),
        parkwise: Number((run.parkwise[r.key] as number) ?? 0),
      }))
    : [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Baseline vs ParkWise</h1>
          <p className="text-sm text-slate-600">
            Both policies replay the identical arrival sequence over the same layout — the only
            difference is the allocation policy.
          </p>
        </div>
        <SimulatedBadge note="Metrics come from simulation runs of the same arrival sequence, not from measured field data." />
      </div>

      {error && <ErrorState message={error} />}

      <section className="card">
        <h2 className="mb-3 text-lg font-bold text-slate-800">Run a comparison</h2>
        <form onSubmit={startRun} className="flex flex-wrap items-end gap-3">
          <div>
            <label className="label" htmlFor="seed">Seed</label>
            <input id="seed" type="number" className="input w-28" value={seed}
              onChange={(e) => setSeed(Number(e.target.value))} />
          </div>
          <div>
            <label className="label" htmlFor="hours">Hours (from 07:00)</label>
            <input id="hours" type="number" min={1} max={24} className="input w-32" value={hours}
              onChange={(e) => setHours(Number(e.target.value))} />
          </div>
          <div>
            <label className="label" htmlFor="scale">Demand scale</label>
            <input id="scale" type="number" min={0.5} max={5} step={0.5} className="input w-32" value={scale}
              onChange={(e) => setScale(Number(e.target.value))} />
          </div>
          <button type="submit" className="btn-primary" disabled={busy}>
            <Play className="h-4 w-4" aria-hidden /> {busy ? "Simulating…" : "Run simulation"}
          </button>
        </form>
        <p className="mt-2 text-xs text-slate-500">
          Same seed + same parameters ⇒ the same arrival sequence, so runs are reproducible.
        </p>
      </section>

      {run && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="card">
              <p className="text-xs font-semibold uppercase text-slate-500">Arrivals replayed</p>
              <p className="text-3xl font-bold tabular-nums">{run.arrivals}</p>
              <p className="text-xs text-slate-500">seed {run.params.seed} · {run.params.hours}h · scale {run.params.scale}</p>
            </div>
            <div className="card">
              <p className="text-xs font-semibold uppercase text-slate-500">Arrival profile</p>
              <p className="text-sm font-semibold text-slate-800">{run.assumptions.arrival_profile ?? "history"}</p>
              <p className="text-xs text-slate-500">starts {new Date(run.params.start + "Z").toUTCString()}</p>
            </div>
            <div className="card">
              <p className="text-xs font-semibold uppercase text-slate-500">Generated</p>
              <p className="text-sm font-semibold text-slate-800">{new Date(run.generated_at + "Z").toLocaleString()}</p>
              <StatusPill tone="purple">{run.label}</StatusPill>
            </div>
          </div>

          <section className="card overflow-x-auto">
            <h2 className="mb-3 text-lg font-bold text-slate-800">Metric comparison</h2>
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-300">
                  <th className="th">Metric</th>
                  <th className="th">Baseline (FCFS, no info)</th>
                  <th className="th">ParkWise</th>
                  <th className="th">Difference</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map((row) => {
                  const b = run.baseline[row.key] as number | null;
                  const p = run.parkwise[row.key] as number | null;
                  const delta = b != null && p != null ? p - b : null;
                  const wins =
                    row.better !== "none" && delta !== null && delta !== 0
                      ? (row.better === "lower" ? delta < 0 : delta > 0)
                        ? "parkwise"
                        : "baseline"
                      : null;
                  return (
                    <tr key={String(row.key)} className="border-b border-slate-100">
                      <td className="td font-medium">{row.label}</td>
                      <td className="td tabular-nums">{row.format(b)}</td>
                      <td className={`td tabular-nums ${wins === "parkwise" ? "font-bold text-emerald-700" : ""}`}>
                        {row.format(p)}
                      </td>
                      <td className="td tabular-nums">
                        {delta === null ? "—" : `${delta > 0 ? "+" : ""}${Number(delta.toFixed(2))}`}
                        {wins === "parkwise" && <span className="ml-1 text-emerald-700" aria-label="better with ParkWise">◀ better</span>}
                        {wins === "baseline" && <span className="ml-1 text-slate-500">baseline better</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <section className="card">
            <h2 className="mb-3 text-lg font-bold text-slate-800">Side by side</h2>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 8, right: 8, left: -18, bottom: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="metric" angle={-20} textAnchor="end" interval={0} tick={{ fontSize: 11 }} />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="baseline" name="Baseline" fill="#94a3b8" />
                  <Bar dataKey="parkwise" name="ParkWise" fill="#2563eb" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="card">
            <h2 className="mb-2 flex items-center gap-2 text-lg font-bold text-slate-800">
              <Info className="h-5 w-5 text-brand-600" aria-hidden /> Model assumptions
            </h2>
            <p className="mb-2 text-sm text-slate-700">{run.assumptions.model}</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <p className="mb-1 text-sm font-semibold text-slate-800">Baseline policy</p>
                <p className="text-sm text-slate-600">{run.assumptions.baseline}</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <p className="mb-1 text-sm font-semibold text-slate-800">ParkWise policy</p>
                <p className="text-sm text-slate-600">{run.assumptions.parkwise}</p>
              </div>
            </div>
            <details className="mt-3">
              <summary className="cursor-pointer text-sm font-semibold text-brand-700">
                Numeric model parameters
              </summary>
              <ul className="mt-2 list-inside list-disc text-sm text-slate-600">
                {Object.entries(run.assumptions.parameters).map(([k, v]) => (
                  <li key={k}>
                    <code className="rounded bg-slate-100 px-1">{k}</code> = {String(v)}
                  </li>
                ))}
              </ul>
            </details>
            <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              {run.label} The baseline model is a stated assumption (drivers search blindly), not a
              measurement of real drivers.
            </p>
          </section>
        </>
      )}

      {!run && !error && (
        <LoadingState label="No run yet…" />
      )}
    </div>
  );
}
