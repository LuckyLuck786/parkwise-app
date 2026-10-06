import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  GaugeCircle,
  ListOrdered,
  TimerOff,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
} from "recharts";
import { api, ApiError } from "../services/api";
import { useLive } from "../hooks/useLive";
import { ErrorState, FillGauge, LoadingState, SimulatedBadge, StatusPill } from "../components/ui";
import { Analytics, Conflict } from "../types";

function StatCard({
  icon,
  label,
  value,
  hint,
  tone = "slate",
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  hint?: string;
  tone?: "slate" | "red" | "amber" | "green";
}) {
  const tones = {
    slate: "text-slate-800",
    red: "text-rose-700",
    amber: "text-amber-700",
    green: "text-emerald-700",
  };
  return (
    <div className="card flex items-start gap-3">
      <span className="rounded-lg bg-slate-100 p-2 text-slate-600" aria-hidden>
        {icon}
      </span>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
        <p className={`text-2xl font-bold tabular-nums ${tones[tone]}`}>{value}</p>
        {hint && <p className="text-xs text-slate-500">{hint}</p>}
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Analytics>("/api/v1/admin/analytics")
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load analytics"));
  }, []);

  useLive(load);
  useEffect(load, [load]);

  const resolve = async (auditId: string) => {
    await api(`/api/v1/admin/conflicts/${auditId}/resolve`, { method: "POST" })
      .then(load)
      .catch(() => undefined);
  };

  if (error && !data) return <ErrorState message={error} onRetry={load} />;
  if (!data) return <LoadingState label="Loading dashboard…" />;

  const occupancyBars = data.lots.map((l) => ({
    name: l.name,
    occupied: l.counts.occupied,
    allotted: l.counts.allotted,
    free: l.counts.free,
  }));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Admin dashboard</h1>
          <p className="text-sm text-slate-600">
            Everything here is computed from the database — nothing is hardcoded.
          </p>
        </div>
        <SimulatedBadge />
      </div>

      {error && <ErrorState message={error} onRetry={load} />}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<ListOrdered className="h-5 w-5" />}
          label="Waitlist"
          value={data.queue_length}
          hint="vehicles waiting for a bay"
          tone={data.queue_length > 0 ? "amber" : "green"}
        />
        <StatCard
          icon={<AlertTriangle className="h-5 w-5" />}
          label="Open conflicts"
          value={data.conflict_count}
          hint="sensor vs scan disagreements"
          tone={data.conflict_count > 0 ? "red" : "green"}
        />
        <StatCard
          icon={<TimerOff className="h-5 w-5" />}
          label="No-show rate"
          value={`${data.no_show.no_show_rate_pct}%`}
          hint={data.no_show.definition}
        />
        <StatCard
          icon={<Cpu className="h-5 w-5" />}
          label="Devices online"
          value={`${data.devices.filter((d) => d.reachable).length}/${data.devices.length}`}
          hint="heartbeat-based"
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="card">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold text-slate-800">
            <GaugeCircle className="h-5 w-5 text-brand-600" aria-hidden /> Occupancy by lot
          </h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={occupancyBars} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Legend />
                <Bar dataKey="occupied" name="Occupied" stackId="a" fill="#475569" />
                <Bar dataKey="allotted" name="Allotted" stackId="a" fill="#f59e0b" />
                <Bar dataKey="free" name="Free" stackId="a" fill="#10b981" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="card">
          <h2 className="mb-3 text-lg font-bold text-slate-800">Utilisation (14 days)</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.utilization_series} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} />
                <YAxis unit="%" domain={[0, 100]} />
                <Tooltip formatter={(v: number) => `${v}%`} />
                <Line type="monotone" dataKey="utilization_pct" name="Utilisation" stroke="#2563eb" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Occupied bay-minutes ÷ (capacity × day), from recorded allotments.
          </p>
        </section>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="card">
          <h2 className="mb-3 text-lg font-bold text-slate-800">Lots</h2>
          <ul className="space-y-3">
            {data.lots.map((lot) => (
              <li key={lot.id}>
                <FillGauge
                  used={lot.used}
                  capacity={lot.capacity}
                  label={lot.name}
                  warning={lot.warning?.active ? lot.warning.message : undefined}
                />
              </li>
            ))}
          </ul>

          <h3 className="mt-5 mb-2 text-sm font-semibold uppercase text-slate-500">
            Allotments today by tier
          </h3>
          <ul className="flex flex-wrap gap-2 text-sm">
            {Object.entries(data.tier_summary_today).length === 0 && (
              <li className="text-slate-500">No allotments yet today.</li>
            )}
            {Object.entries(data.tier_summary_today).map(([tier, count]) => (
              <li key={tier}>
                <StatusPill tone="blue">{tier.replace("_", " ")}: {count}</StatusPill>
              </li>
            ))}
          </ul>
        </section>

        <section className="card">
          <h2 className="mb-3 text-lg font-bold text-slate-800">
            Conflicts & alerts ({data.conflict_count})
          </h2>
          {data.conflicts.length === 0 ? (
            <p className="text-sm text-slate-500">
              No open conflicts. Disagreements between scans and sensors show up here — they are
              never auto-punished.
            </p>
          ) : (
            <ul className="space-y-3">
              {data.conflicts.map((c: Conflict) => (
                <li key={c.audit_id} className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-amber-900">
                      {c.conflict_type.replace(/_/g, " ")} · {c.bay_label ?? "—"}
                    </p>
                    <StatusPill tone={c.severity === "warning" ? "red" : "slate"}>
                      {c.severity ?? "info"}
                    </StatusPill>
                  </div>
                  <p className="mt-1 text-sm text-amber-900">{c.message}</p>
                  {c.recommended_action && (
                    <p className="mt-1 text-xs text-amber-800">→ {c.recommended_action}</p>
                  )}
                  <button
                    type="button"
                    className="btn-secondary mt-2 !py-1 text-xs"
                    onClick={() => resolve(c.audit_id)}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Mark resolved
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="card">
        <h2 className="mb-3 text-lg font-bold text-slate-800">Devices</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-200">
                <th className="th">Device</th>
                <th className="th">Kind</th>
                <th className="th">Status</th>
                <th className="th">Last heartbeat</th>
                <th className="th">Age</th>
              </tr>
            </thead>
            <tbody>
              {data.devices.map((d) => (
                <tr key={d.id} className="border-b border-slate-100">
                  <td className="td font-medium">{d.name}</td>
                  <td className="td">{d.kind ?? "—"}</td>
                  <td className="td">
                    <StatusPill tone={d.reachable ? "green" : "red"}>{d.status}</StatusPill>
                  </td>
                  <td className="td">{d.last_heartbeat ? new Date(d.last_heartbeat + "Z").toLocaleTimeString() : "never"}</td>
                  <td className="td">{d.heartbeat_age_seconds != null ? `${d.heartbeat_age_seconds}s` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h2 className="mb-3 text-lg font-bold text-slate-800">Audit log</h2>
        <p className="mb-2 text-sm text-slate-500">
          Every decision with the explanation attached. {data.totals.users} users ·{" "}
          {data.totals.vehicles} vehicles · {data.totals.bays} bays ·{" "}
          {data.totals.allotments_all_time} allotments all time.
        </p>
        <div className="max-h-[28rem] overflow-y-auto">
          <table className="w-full text-left">
            <thead className="sticky top-0 bg-white">
              <tr className="border-b border-slate-200">
                <th className="th">When</th>
                <th className="th">Actor</th>
                <th className="th">Action</th>
                <th className="th">Details</th>
              </tr>
            </thead>
            <tbody>
              {data.audit.map((entry) => (
                <tr key={entry.id} className="border-b border-slate-100 align-top">
                  <td className="td whitespace-nowrap">{entry.ts ? new Date(entry.ts + "Z").toLocaleString() : ""}</td>
                  <td className="td">{entry.actor}</td>
                  <td className="td font-medium">{entry.action}</td>
                  <td className="td">
                    <details>
                      <summary className="cursor-pointer text-xs text-brand-700">view</summary>
                      <pre className="mt-1 max-w-xl overflow-x-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">
                        {JSON.stringify(entry.details, null, 2)}
                      </pre>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
