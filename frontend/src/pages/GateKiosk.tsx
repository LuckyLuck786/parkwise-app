import { FormEvent, useEffect, useMemo, useState } from "react";
import { LogIn, LogOut, ScanLine, AlertTriangle, Route } from "lucide-react";
import { api, ApiError } from "../services/api";
import { useAuth } from "../context/AuthContext";
import ExplanationPanel from "../components/ExplanationPanel";
import { ErrorState, LoadingState, SimulatedBadge, StatusPill } from "../components/ui";
import { AllocationResult, Building, GateScanResponse, LotSummary, Vehicle } from "../types";

type RosterVehicle = Vehicle & { owner?: string; tier?: number };

export default function GateKiosk() {
  const { user } = useAuth();
  const isStaff = user?.role === "admin" || user?.role === "gate_operator";

  const [roster, setRoster] = useState<RosterVehicle[] | null>(null);
  const [lots, setLots] = useState<LotSummary[]>([]);
  const [buildings, setBuildings] = useState<Building[]>([]);

  const [tag, setTag] = useState("");
  const [direction, setDirection] = useState<"in_scan" | "out_scan">("in_scan");
  const [buildingId, setBuildingId] = useState("");
  const [lotId, setLotId] = useState("");
  const [source, setSource] = useState<"simulator" | "manual">("simulator");

  const [result, setResult] = useState<GateScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadRoster = () => {
    const path = isStaff ? "/api/v1/staff/vehicles" : "/api/v1/vehicles";
    api<RosterVehicle[]>(path).then(setRoster).catch(() => setRoster([]));
    api<LotSummary[]>("/api/v1/lots", { auth: false }).then(setLots).catch(() => undefined);
    api<Building[]>("/api/v1/buildings", { auth: false }).then(setBuildings).catch(() => undefined);
  };

  useEffect(loadRoster, []);

  const lotName = useMemo(() => lots.find((l) => l.id === lotId)?.name, [lots, lotId]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!tag.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<GateScanResponse>("/api/v1/gate/scan", {
        method: "POST",
        body: {
          plate_or_tag_id: tag.trim().toUpperCase(),
          direction,
          destination_building_id: buildingId || null,
          lot_preference_id: lotId || null,
          source,
        },
      });
      setResult(res);
      loadRoster();
    } catch (err) {
      setResult(null);
      setError(err instanceof ApiError ? err.message : "Scan failed");
    } finally {
      setBusy(false);
    }
  };

  const allocation: AllocationResult | null = result?.allocation ?? null;
  const fullLot = allocation?.status === "offered_alternative" || allocation?.status === "waitlisted";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Gate kiosk</h1>
          <p className="text-sm text-slate-600">
            Scan a vehicle in or out. Runs through the same ingestion pipeline the hardware uses.
          </p>
        </div>
        <SimulatedBadge note="Scans here are simulated gate events (or a real operator entry) — both take the same code path." />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="card">
          <h2 className="mb-3 text-lg font-bold text-slate-800">Scan</h2>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="label" htmlFor="tag">Vehicle plate / tag</label>
              {roster && roster.length > 0 ? (
                <select
                  id="tag"
                  className="input"
                  value={tag}
                  onChange={(e) => setTag(e.target.value)}
                  required
                >
                  <option value="">Pick a vehicle…</option>
                  {roster.map((v) => (
                    <option key={v.id} value={v.plate_or_tag_id}>
                      {v.plate_or_tag_id} — {v.type === "two_wheeler" ? "2W" : "4W"}
                      {v.owner ? ` · ${v.owner}` : ""}
                      {v.tier ? ` · T${v.tier}` : ""}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  id="tag"
                  className="input font-mono"
                  placeholder="KA-01-AB-1234"
                  value={tag}
                  onChange={(e) => setTag(e.target.value)}
                  required
                />
              )}
              <p className="mt-1 text-xs text-slate-500">
                {roster && roster.length > 0
                  ? "…or type any registered tag directly."
                  : "Enter a registered tag."}
              </p>
            </div>

            <fieldset>
              <legend className="label">Direction</legend>
              <div className="flex gap-2">
                <button
                  type="button"
                  className={direction === "in_scan" ? "btn-primary flex-1 !py-3" : "btn-secondary flex-1 !py-3"}
                  onClick={() => setDirection("in_scan")}
                  aria-pressed={direction === "in_scan"}
                >
                  <LogIn className="h-5 w-5" aria-hidden /> Arriving
                </button>
                <button
                  type="button"
                  className={direction === "out_scan" ? "btn-primary flex-1 !py-3" : "btn-secondary flex-1 !py-3"}
                  onClick={() => setDirection("out_scan")}
                  aria-pressed={direction === "out_scan"}
                >
                  <LogOut className="h-5 w-5" aria-hidden /> Leaving
                </button>
              </div>
            </fieldset>

            {direction === "in_scan" && (
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="dest">Destination building</label>
                  <select id="dest" className="input" value={buildingId} onChange={(e) => setBuildingId(e.target.value)}>
                    <option value="">Nearest lot (auto)</option>
                    {buildings.map((b) => (
                      <option key={b.id} value={b.id}>{b.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor="lot">Preferred lot</label>
                  <select id="lot" className="input" value={lotId} onChange={(e) => setLotId(e.target.value)}>
                    <option value="">Auto</option>
                    {lots.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name} ({l.free} free)
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            <div>
              <label className="label" htmlFor="source">Event source</label>
              <select id="source" className="input" value={source} onChange={(e) => setSource(e.target.value as "simulator" | "manual")}>
                <option value="simulator">simulator (default demo device)</option>
                <option value="manual">manual (operator entry)</option>
              </select>
            </div>

            <button type="submit" className="btn-primary w-full !py-4 text-base" disabled={busy}>
              <ScanLine className="h-5 w-5" aria-hidden />
              {busy ? "Scanning…" : direction === "in_scan" ? "SCAN IN" : "SCAN OUT"}
            </button>
          </form>
        </section>

        <section className="space-y-4" aria-live="polite">
          {error && <ErrorState message={error} />}
          {busy && !result && <LoadingState label="Allocating a bay…" />}

          {!result && !error && !busy && (
            <div className="card flex min-h-[220px] flex-col items-center justify-center text-center text-slate-500">
              <ScanLine className="mb-2 h-8 w-8 text-slate-300" aria-hidden />
              <p className="text-sm">Scan a vehicle to see the allotment result here.</p>
            </div>
          )}

          {result && (
            <div
              className={`card ${
                result.success && !fullLot
                  ? "border-emerald-300"
                  : allocation?.status === "waitlisted" || allocation?.status === "rejected"
                    ? "border-amber-300"
                    : "border-sky-300"
              }`}
            >
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-lg font-bold text-slate-900">
                  {allocation?.status === "allotted" && "Bay allotted"}
                  {allocation?.status === "offered_alternative" && "Lot full — alternative offered"}
                  {allocation?.status === "waitlisted" && "All lots full — waitlisted"}
                  {allocation?.status === "rejected" && "Scan rejected"}
                  {!allocation && "Scan complete"}
                </h2>
                {allocation?.bay && (
                  <StatusPill tone="green">
                    {allocation.bay.lot_name} · {allocation.bay.label}
                  </StatusPill>
                )}
              </div>

              <p className="text-sm text-slate-700">{result.message}</p>

              {allocation?.status === "offered_alternative" && allocation.alternative_lot && (
                <div className="mt-3 flex items-start gap-2 rounded-lg border border-sky-300 bg-sky-50 p-3 text-sm text-sky-900">
                  <Route className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  <div>
                    <p className="font-semibold">
                      Alternative: {allocation.alternative_lot.name}
                    </p>
                    <p>
                      {allocation.alternative_lot.estimated_drive_time_mins} min drive ·{" "}
                      {allocation.alternative_lot.available_bays} bays free — head there now, the bay
                      is held for you.
                    </p>
                  </div>
                </div>
              )}

              {allocation?.status === "waitlisted" && (
                <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  <div>
                    <p className="font-semibold">Position #{allocation.waitlist_position} in the queue</p>
                    <p>
                      Priority order is tier first, then arrival time. You are notified the moment a
                      bay frees up.
                    </p>
                  </div>
                </div>
              )}

              {allocation?.explanation && <div className="mt-3"><ExplanationPanel explanation={allocation.explanation} /></div>}

              {lotName && direction === "in_scan" && (
                <p className="mt-3 text-xs text-slate-500">
                  Requested lot: {lotName}
                </p>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
