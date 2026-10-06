import { useCallback, useEffect, useState } from "react";
import { RefreshCw, AlertTriangle, Radio } from "lucide-react";
import { api, ApiError } from "../services/api";
import { useLive } from "../hooks/useLive";
import BayGrid, { BayLegend } from "../components/BayGrid";
import { EmptyState, ErrorState, FillGauge, LoadingState, SimulatedBadge, StatusPill } from "../components/ui";
import { Bay, Building, LotBaysResponse, LotSummary } from "../types";

export default function LiveLotMap() {
  const [lots, setLots] = useState<LotSummary[] | null>(null);
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [selectedLotId, setSelectedLotId] = useState<string | null>(null);
  const [payload, setPayload] = useState<LotBaysResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedBay, setSelectedBay] = useState<Bay | null>(null);

  const loadLots = useCallback(() => {
    api<LotSummary[]>("/api/v1/lots", { auth: false })
      .then((data) => {
        setLots(data);
        setError(null);
        setSelectedLotId((current) => current ?? data[0]?.id ?? null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load lots"));
  }, []);

  const loadBays = useCallback((lotId: string) => {
    api<LotBaysResponse>(`/api/v1/lots/${lotId}/bays`, { auth: false })
      .then((data) => {
        setPayload(data);
        setSelectedBay(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load bays"));
  }, []);

  const refreshAll = useCallback(() => {
    loadLots();
    if (selectedLotId) loadBays(selectedLotId);
  }, [loadLots, loadBays, selectedLotId]);

  const liveStatus = useLive(refreshAll);

  useEffect(() => {
    api<Building[]>("/api/v1/buildings", { auth: false }).then(setBuildings).catch(() => undefined);
    loadLots();
  }, [loadLots]);

  useEffect(() => {
    if (selectedLotId) loadBays(selectedLotId);
  }, [selectedLotId, loadBays]);

  if (error && !lots) return <ErrorState message={error} onRetry={refreshAll} />;
  if (!lots) return <LoadingState label="Loading live lot status…" />;

  const active = lots.find((l) => l.id === selectedLotId) ?? lots[0];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Live lot map</h1>
          <p className="text-sm text-slate-600">
            Bay-level status, updated as scans and sensors report in. Read-only and public.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SimulatedBadge />
          <StatusPill tone={liveStatus === "sse" ? "green" : liveStatus === "polling" ? "amber" : "slate"}
            icon={<Radio className="h-3 w-3" aria-hidden />}>
            {liveStatus === "sse" ? "Streaming" : liveStatus === "polling" ? "Polling" : "Reconnecting"}
          </StatusPill>
          <button type="button" className="btn-secondary" onClick={refreshAll}>
            <RefreshCw className="h-4 w-4" aria-hidden /> Refresh
          </button>
        </div>
      </div>

      {error && <ErrorState message={error} onRetry={refreshAll} />}

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Choose a lot">
        {lots.map((lot) => (
          <button
            key={lot.id}
            type="button"
            role="tab"
            aria-selected={lot.id === active?.id}
            className={
              lot.id === active?.id
                ? "btn-primary"
                : "btn-secondary"
            }
            onClick={() => setSelectedLotId(lot.id)}
          >
            {lot.name}
            <span className="rounded-full bg-white/25 px-2 text-xs tabular-nums">
              {lot.free}/{lot.capacity}
            </span>
            {lot.is_full && <span className="rounded bg-rose-700 px-1.5 text-xs">FULL</span>}
          </button>
        ))}
      </div>

      {!active && <EmptyState title="No lots configured yet" hint="Seed the database or add lots in the admin API." />}

      {active && (
        <div className="grid gap-5 lg:grid-cols-3">
          <section className="card lg:col-span-2">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-bold text-slate-800">{active.name}</h2>
              <div className="flex flex-wrap gap-2">
                {active.low_confidence_bays > 0 && (
                  <StatusPill tone="amber" icon={<AlertTriangle className="h-3 w-3" aria-hidden />}>
                    {active.low_confidence_bays} low-confidence {active.low_confidence_bays === 1 ? "bay" : "bays"}
                  </StatusPill>
                )}
                <StatusPill tone={active.is_full ? "red" : "green"}>
                  {active.is_full ? "Full" : `${active.free} free`}
                </StatusPill>
              </div>
            </div>

            <FillGauge
              used={active.used}
              capacity={active.capacity}
              label={`${active.name} occupancy`}
              warning={active.warning?.active ? active.warning.message : undefined}
            />

            <div className="mt-4">
              {!payload ? (
                <LoadingState label="Loading bays…" />
              ) : (
                <BayGrid
                  bays={payload.bays}
                  title={active.name}
                  selectedId={selectedBay?.id ?? null}
                  onSelect={(bay) => setSelectedBay((cur) => (cur?.id === bay.id ? null : bay))}
                />
              )}
            </div>

            <div className="mt-3 border-t border-slate-100 pt-3">
              <BayLegend />
            </div>

            {selectedBay && (
              <dl className="mt-3 grid gap-x-6 gap-y-1 rounded-lg bg-slate-50 p-3 text-sm sm:grid-cols-2">
                <div><dt className="inline font-semibold text-slate-700">Bay: </dt><dd className="inline">{selectedBay.label}</dd></div>
                <div><dt className="inline font-semibold text-slate-700">State: </dt><dd className="inline capitalize">{selectedBay.state}</dd></div>
                <div><dt className="inline font-semibold text-slate-700">Type: </dt><dd className="inline">{selectedBay.type === "two_wheeler" ? "Two-wheeler" : "Four-wheeler"}</dd></div>
                <div><dt className="inline font-semibold text-slate-700">Nearest building: </dt><dd className="inline">{selectedBay.nearest_building ?? "—"}</dd></div>
                <div><dt className="inline font-semibold text-slate-700">Confidence: </dt>
                  <dd className="inline">
                    {Math.round(selectedBay.confidence * 100)}% · {selectedBay.state_source}
                    {selectedBay.low_confidence && " (low confidence)"}
                  </dd>
                </div>
                {selectedBay.allotment?.plate && (
                  <div><dt className="inline font-semibold text-slate-700">Vehicle: </dt><dd className="inline font-mono">{selectedBay.allotment.plate}</dd></div>
                )}
              </dl>
            )}
          </section>

          <aside className="space-y-4">
            <section className="card">
              <h2 className="mb-2 text-lg font-bold text-slate-800">Prediction</h2>
              {active.prediction ? (
                <div className="space-y-2 text-sm">
                  <p className="font-semibold text-slate-800">{active.prediction.warning_message}</p>
                  <p className="text-slate-600">
                    Confidence: <strong className="capitalize">{active.prediction.confidence}</strong>
                  </p>
                  <p className="text-xs text-slate-500">{active.prediction.confidence_note}</p>
                  <StatusPill tone="purple">{active.prediction.heuristic_label}</StatusPill>
                  <p className="text-xs text-slate-500">
                    Heuristic from historical arrival patterns — statistics, not machine learning.
                  </p>
                </div>
              ) : (
                <p className="text-sm text-slate-500">No prediction available.</p>
              )}
            </section>

            <section className="card">
              <h2 className="mb-2 text-lg font-bold text-slate-800">All lots</h2>
              <ul className="space-y-3">
                {lots.map((lot) => (
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
            </section>

            <section className="card text-sm text-slate-600">
              <h2 className="mb-2 text-lg font-bold text-slate-800">Buildings</h2>
              <ul className="list-inside list-disc">
                {buildings.map((b) => (
                  <li key={b.id}>{b.name}</li>
                ))}
              </ul>
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}
