import { useState } from "react";
import { ChevronDown, ChevronUp, CheckCircle2, HelpCircle } from "lucide-react";
import { Explanation } from "../types";

/**
 * Renders the engine's decision explanation: rule applied, candidates
 * considered, why this bay, why the others were rejected.
 */
export default function ExplanationPanel({ explanation }: { explanation: Explanation }) {
  const [open, setOpen] = useState(false);
  const rejections = Object.entries(explanation.rejections ?? {});
  const rules = (explanation.rules_in_effect ?? {}) as Record<string, unknown>;

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <HelpCircle className="h-4 w-4 text-brand-600" aria-hidden />
          Why this decision?
        </span>
        {open ? (
          <ChevronUp className="h-4 w-4 text-slate-500" aria-hidden />
        ) : (
          <ChevronDown className="h-4 w-4 text-slate-500" aria-hidden />
        )}
      </button>

      {open && (
        <div className="mt-3 space-y-3 text-sm text-slate-700">
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
            <div>
              <dt className="text-xs font-semibold uppercase text-slate-500">Rule applied</dt>
              <dd>{String(explanation.rule_applied)}</dd>
            </div>
            {explanation.user_tier !== undefined && (
              <div>
                <dt className="text-xs font-semibold uppercase text-slate-500">Your tier</dt>
                <dd>Tier {explanation.user_tier}</dd>
              </div>
            )}
            {explanation.preferred_lot && (
              <div>
                <dt className="text-xs font-semibold uppercase text-slate-500">Preferred lot</dt>
                <dd>{explanation.preferred_lot}</dd>
              </div>
            )}
            {explanation.destination && (
              <div>
                <dt className="text-xs font-semibold uppercase text-slate-500">Destination</dt>
                <dd>{explanation.destination}</dd>
              </div>
            )}
            {explanation.candidates_considered !== undefined && (
              <div>
                <dt className="text-xs font-semibold uppercase text-slate-500">Bays considered</dt>
                <dd>{explanation.candidates_considered}</dd>
              </div>
            )}
          </dl>

          {explanation.chosen && (
            <p className="flex items-start gap-2 rounded-md border border-emerald-200 bg-emerald-50 p-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
              <span>
                <strong>{explanation.chosen.lot} / {explanation.chosen.bay}</strong> — {explanation.chosen.reason}
              </span>
            </p>
          )}

          {rejections.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase text-slate-500">
                Bays rejected ({rejections.reduce((sum, [, n]) => sum + n, 0)})
              </p>
              <ul className="flex flex-wrap gap-1.5">
                {rejections.map(([reason, count]) => (
                  <li
                    key={reason}
                    className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs"
                  >
                    {reason} <span className="font-semibold">×{count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {Array.isArray(explanation.alternatives) && explanation.alternatives.length > 0 && (
            <p className="text-xs">
              Alternative offered:{" "}
              {explanation.alternatives.map(
                (alt) =>
                  `${alt.lot} (${alt.free_bays} free, ~${alt.estimated_drive_time_mins} min drive)`,
              ).join("; ")}
            </p>
          )}

          {Object.keys(rules).length > 0 && (
            <details className="text-xs text-slate-600">
              <summary className="cursor-pointer font-semibold">Rules in effect</summary>
              <ul className="mt-1 list-inside list-disc">
                {Object.entries(rules).map(([k, v]) => (
                  <li key={k}>
                    {k} = {String(v)}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
