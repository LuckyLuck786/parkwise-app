import { useCallback, useEffect, useState } from "react";
import { Save, RotateCcw } from "lucide-react";
import { api, ApiError } from "../services/api";
import { useLive } from "../hooks/useLive";
import { ErrorState, LoadingState, SimulatedBadge } from "../components/ui";
import { RuleEntry } from "../types";

type RulesMap = Record<string, RuleEntry>;

export default function Rules() {
  const [rules, setRules] = useState<RulesMap | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<RulesMap>("/api/v1/admin/rules")
      .then((data) => {
        setRules(data);
        const initial: Record<string, string> = {};
        Object.entries(data).forEach(([key, entry]) => {
          initial[key] = typeof entry.value === "boolean" ? String(entry.value) : String(entry.value);
        });
        setDraft(initial);
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load rules"));
  }, []);

  useLive(load);
  useEffect(load, [load]);

  const save = async () => {
    if (!rules) return;
    setBusy(true);
    setSaved(null);
    setError(null);
    try {
      const updates: Record<string, unknown> = {};
      Object.entries(rules).forEach(([key, entry]) => {
        const raw = draft[key] ?? "";
        if (typeof entry.value === "number") {
          const n = Number(raw);
          if (!Number.isNaN(n) && n !== entry.value) updates[key] = n;
        } else if (typeof entry.value === "boolean") {
          const b = raw === "true";
          if (b !== entry.value) updates[key] = b;
        } else if (raw !== String(entry.value)) {
          updates[key] = raw;
        }
      });
      if (Object.keys(updates).length === 0) {
        setSaved("Nothing changed.");
        return;
      }
      await api("/api/v1/admin/rules", { method: "PUT", body: { updates } });
      setSaved(`Saved: ${Object.keys(updates).join(", ")}`);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save rules");
    } finally {
      setBusy(false);
    }
  };

  const resetDraft = () => {
    if (!rules) return;
    const initial: Record<string, string> = {};
    Object.entries(rules).forEach(([key, entry]) => {
      initial[key] = String(entry.value);
    });
    setDraft(initial);
    setSaved(null);
  };

  if (error && !rules) return <ErrorState message={error} onRetry={load} />;
  if (!rules) return <LoadingState label="Loading rules…" />;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Allocation rules</h1>
          <p className="text-sm text-slate-600">
            These values drive the engine directly — no restart needed, no code change.
          </p>
        </div>
        <SimulatedBadge note="Demo environment: rule edits are local to this database." />
      </div>

      {error && <ErrorState message={error} />}

      <section className="card">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <button type="button" className="btn-primary" onClick={save} disabled={busy}>
            <Save className="h-4 w-4" aria-hidden /> {busy ? "Saving…" : "Save changes"}
          </button>
          <button type="button" className="btn-secondary" onClick={resetDraft}>
            <RotateCcw className="h-4 w-4" aria-hidden /> Reset form
          </button>
          {saved && <span className="text-sm font-medium text-emerald-700">{saved}</span>}
        </div>

        <ul className="divide-y divide-slate-100">
          {Object.entries(rules).map(([key, entry]) => (
            <li key={key} className="grid gap-3 py-3 sm:grid-cols-[1fr_auto] sm:items-center">
              <div>
                <p className="font-semibold text-slate-800">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 text-sm">{key}</code>
                </p>
                <p className="text-sm text-slate-600">{entry.description}</p>
                <p className="text-xs text-slate-400">default: {String(entry.default)}</p>
              </div>
              <div className="min-w-[9rem]">
                {typeof entry.value === "boolean" ? (
                  <select
                    className="input"
                    aria-label={key}
                    value={draft[key] ?? String(entry.value)}
                    onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                  >
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : (
                  <input
                    className="input tabular-nums"
                    aria-label={key}
                    inputMode={typeof entry.value === "number" ? "numeric" : "text"}
                    value={draft[key] ?? String(entry.value)}
                    onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                  />
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="card text-sm text-slate-600">
        <h2 className="mb-2 text-lg font-bold text-slate-800">How the tiers work</h2>
        <ul className="list-inside list-disc space-y-1">
          <li><strong>Tier 1</strong> — accessibility/medical: reserved accessible bays nearest step-free entrances, never evicted.</li>
          <li><strong>Tier 2</strong> — faculty/staff/service: a reserved quota held until the cut-off hour, then opened to everyone.</li>
          <li><strong>Tier 3</strong> — everyone else: general bays, first-come-first-served within the rules.</li>
          <li>Tiers are a <strong>reserved quota</strong> — a bay already occupied is never taken away from a parked vehicle.</li>
        </ul>
      </section>
    </div>
  );
}
