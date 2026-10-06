import { ReactNode } from "react";
import { Loader2, AlertTriangle, Inbox } from "lucide-react";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div
      className="card flex items-center gap-3 text-slate-600"
      role="status"
      aria-live="polite"
    >
      <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="card flex flex-col items-center gap-2 py-10 text-center">
      <Inbox className="h-8 w-8 text-slate-400" aria-hidden />
      <p className="font-semibold text-slate-700">{title}</p>
      {hint && <p className="max-w-md text-sm text-slate-500">{hint}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      className="card flex flex-col gap-3 border-rose-300 bg-rose-50 sm:flex-row sm:items-center sm:justify-between"
      role="alert"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" aria-hidden />
        <div>
          <p className="font-semibold text-rose-800">Something went wrong</p>
          <p className="text-sm text-rose-700">{message}</p>
        </div>
      </div>
      {onRetry && (
        <button type="button" className="btn-secondary" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function SimulatedBadge({ note }: { note?: string }) {
  return (
    <span
      className="pill border border-violet-300 bg-violet-100 text-violet-800"
      title={
        note ??
        "This data comes from the ParkWise simulator / seeded demo data, not physical sensors."
      }
    >
      <span aria-hidden>◈</span> Simulated data
    </span>
  );
}

export function StatusPill({
  tone,
  children,
  icon,
}: {
  tone: "green" | "amber" | "slate" | "red" | "blue" | "purple";
  children: ReactNode;
  icon?: ReactNode;
}) {
  const tones: Record<string, string> = {
    green: "border-emerald-300 bg-emerald-100 text-emerald-900",
    amber: "border-amber-300 bg-amber-100 text-amber-900",
    slate: "border-slate-300 bg-slate-100 text-slate-800",
    red: "border-rose-300 bg-rose-100 text-rose-900",
    blue: "border-sky-300 bg-sky-100 text-sky-900",
    purple: "border-violet-300 bg-violet-100 text-violet-900",
  };
  return (
    <span className={`pill border ${tones[tone]}`}>
      {icon}
      {children}
    </span>
  );
}

export function FillGauge({
  used,
  capacity,
  label,
  warning,
}: {
  used: number;
  capacity: number;
  label: string;
  warning?: string;
}) {
  const pct = capacity > 0 ? Math.min(100, Math.round((used / capacity) * 100)) : 0;
  const tone =
    pct >= 100 ? "bg-rose-600" : pct >= 85 ? "bg-amber-500" : pct >= 60 ? "bg-sky-500" : "bg-emerald-500";
  return (
    <div className="w-full">
      <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
        <span className="font-semibold text-slate-700">{label}</span>
        <span className="tabular-nums text-slate-600">
          {used}/{capacity} ({pct}%)
          {pct >= 100 && <span className="ml-1 font-bold text-rose-700">FULL</span>}
        </span>
      </div>
      <div
        className="h-3 w-full overflow-hidden rounded-full border border-slate-300 bg-slate-100"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label} occupancy`}
      >
        <div className={`h-full ${tone} transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
      {warning && (
        <p className="mt-1 text-xs font-medium text-amber-700">
          <span aria-hidden>⚠</span> {warning}
        </p>
      )}
    </div>
  );
}
