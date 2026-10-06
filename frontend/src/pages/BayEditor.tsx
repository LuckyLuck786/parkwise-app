import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Copy, Plus, Save, Trash2 } from "lucide-react";
import { api, ApiError } from "../services/api";
import { useLive } from "../hooks/useLive";
import BayGrid from "../components/BayGrid";
import { ErrorState, LoadingState, SimulatedBadge, StatusPill } from "../components/ui";
import { Bay, Building, LotSummary, VehicleType } from "../types";

interface AdminBay {
  id: string;
  lot_id: string;
  label: string;
  type: VehicleType;
  x: number;
  y: number;
  is_accessible: boolean;
  reserved_tier?: number | null;
  nearest_building_id?: string | null;
  state: string;
}

const EMPTY_FORM = {
  label: "",
  type: "four_wheeler" as VehicleType,
  x: 0,
  y: 0,
  is_accessible: false,
  reserved_tier: "",
  nearest_building_id: "",
};

export default function BayEditor() {
  const [lots, setLots] = useState<LotSummary[]>([]);
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [bays, setBays] = useState<AdminBay[] | null>(null);
  const [lotId, setLotId] = useState<string>("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    Promise.all([
      api<AdminBay[]>("/api/v1/admin/bays"),
      api<LotSummary[]>("/api/v1/lots", { auth: false }),
      api<Building[]>("/api/v1/buildings", { auth: false }),
    ])
      .then(([bayData, lotData, buildingData]) => {
        setBays(bayData);
        setLots(lotData);
        setBuildings(buildingData);
        setLotId((cur) => cur || lotData[0]?.id || "");
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load layout"));
  }, []);

  useLive(load);
  useEffect(load, [load]);

  const selected = useMemo(
    () => bays?.find((b) => b.id === selectedId) ?? null,
    [bays, selectedId],
  );

  const lotBays = useMemo(() => {
    if (!bays || !lotId) return [];
    return bays
      .filter((b) => b.lot_id === lotId)
      .map((b) => ({
        ...b,
        state: (["free", "allotted", "occupied", "blocked", "unknown"].includes(b.state)
          ? b.state
          : "unknown") as Bay["state"],
        confidence: 1,
        state_source: "initial",
        low_confidence: false,
      })) as unknown as Bay[];
  }, [bays, lotId]);

  const selectBay = (bay: Bay) => {
    const admin = bays?.find((b) => b.id === bay.id);
    if (!admin) return;
    setSelectedId(admin.id);
    setForm({
      label: admin.label,
      type: admin.type,
      x: admin.x,
      y: admin.y,
      is_accessible: admin.is_accessible,
      reserved_tier: admin.reserved_tier ? String(admin.reserved_tier) : "",
      nearest_building_id: admin.nearest_building_id ?? "",
    });
    setMessage(null);
  };

  const resetForm = () => {
    setSelectedId(null);
    setForm({ ...EMPTY_FORM });
    setMessage(null);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!lotId) return;
    setBusy(true);
    setError(null);
    const body = {
      lot_id: lotId,
      label: form.label.trim().toUpperCase(),
      type: form.type,
      x: Number(form.x),
      y: Number(form.y),
      is_accessible: form.is_accessible,
      reserved_tier: form.reserved_tier === "" ? null : Number(form.reserved_tier),
      nearest_building_id: form.nearest_building_id || null,
    };
    try {
      if (selectedId) {
        const { lot_id, ...patch } = body;
        await api(`/api/v1/admin/bays/${selectedId}`, { method: "PATCH", body: patch });
        setMessage(`Saved bay ${body.label}`);
      } else {
        await api("/api/v1/admin/bays", { method: "POST", body });
        setMessage(`Created bay ${body.label}`);
      }
      resetForm();
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save bay");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!selectedId) return;
    setBusy(true);
    try {
      await api(`/api/v1/admin/bays/${selectedId}`, { method: "DELETE" });
      resetForm();
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete bay");
    } finally {
      setBusy(false);
    }
  };

  if (error && !bays) return <ErrorState message={error} onRetry={load} />;
  if (!bays) return <LoadingState label="Loading layout…" />;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Bay editor</h1>
          <p className="text-sm text-slate-600">
            Place and edit bays on the grid. This layout is also the reference for mirroring the
            thermocol model later.
          </p>
        </div>
        <SimulatedBadge note="Layout changes affect live allocation immediately." />
      </div>

      {error && <ErrorState message={error} onRetry={load} />}
      {message && (
        <p className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800" role="status">
          {message}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="lotselect" className="text-sm font-medium text-slate-700">Lot:</label>
        <select id="lotselect" className="input max-w-xs" value={lotId} onChange={(e) => { setLotId(e.target.value); resetForm(); }}>
          {lots.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name} — {l.capacity} bays
            </option>
          ))}
        </select>
        <StatusPill tone="blue">{lotBays.length} bays in view</StatusPill>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <section className="card lg:col-span-2">
          <BayGrid
            bays={lotBays}
            title={lots.find((l) => l.id === lotId)?.name}
            selectedId={selectedId}
            onSelect={selectBay}
          />
          <p className="mt-3 text-xs text-slate-500">
            Click a bay to edit it. Coordinates are grid cells (x = column, y = row), the same
            coordinates the SVG map and the physical model use.
          </p>
        </section>

        <aside className="card">
          <h2 className="mb-3 text-lg font-bold text-slate-800">
            {selectedId ? "Edit bay" : "New bay"}
          </h2>
          <form onSubmit={submit} className="space-y-3">
            <div>
              <label className="label" htmlFor="label">Label</label>
              <input
                id="label"
                className="input font-mono uppercase"
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                required
                placeholder="A-25"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label" htmlFor="bx">Column (x)</label>
                <input id="bx" type="number" min={0} className="input" value={form.x}
                  onChange={(e) => setForm({ ...form, x: Number(e.target.value) })} required />
              </div>
              <div>
                <label className="label" htmlFor="by">Row (y)</label>
                <input id="by" type="number" min={0} className="input" value={form.y}
                  onChange={(e) => setForm({ ...form, y: Number(e.target.value) })} required />
              </div>
            </div>
            <div>
              <label className="label" htmlFor="btype">Vehicle type</label>
              <select id="btype" className="input" value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value as VehicleType })}>
                <option value="four_wheeler">Four-wheeler</option>
                <option value="two_wheeler">Two-wheeler</option>
              </select>
            </div>
            <div>
              <label className="label" htmlFor="bres">Reserved for tier</label>
              <select id="bres" className="input" value={form.reserved_tier}
                onChange={(e) => setForm({ ...form, reserved_tier: e.target.value })}>
                <option value="">No reservation</option>
                <option value="1">Tier 1 (accessible/medical)</option>
                <option value="2">Tier 2 (faculty/staff/service)</option>
                <option value="3">Tier 3</option>
              </select>
            </div>
            <div>
              <label className="label" htmlFor="bldg">Nearest building</label>
              <select id="bldg" className="input" value={form.nearest_building_id}
                onChange={(e) => setForm({ ...form, nearest_building_id: e.target.value })}>
                <option value="">—</option>
                {buildings.map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" className="h-4 w-4" checked={form.is_accessible}
                onChange={(e) => setForm({ ...form, is_accessible: e.target.checked })} />
              Accessible bay (step-free entrance, Tier 1 quota)
            </label>

            <div className="flex flex-wrap gap-2 pt-1">
              <button type="submit" className="btn-primary" disabled={busy}>
                {selectedId ? <Save className="h-4 w-4" aria-hidden /> : <Plus className="h-4 w-4" aria-hidden />}
                {selectedId ? "Save changes" : "Create bay"}
              </button>
              {selectedId && (
                <>
                  <button type="button" className="btn-secondary" onClick={resetForm}>Cancel</button>
                  <button type="button" className="btn-danger" onClick={remove} disabled={busy}>
                    <Trash2 className="h-4 w-4" aria-hidden /> Delete
                  </button>
                </>
              )}
            </div>
          </form>

          <p className="mt-4 flex items-start gap-2 rounded-lg bg-slate-50 p-2 text-xs text-slate-600">
            <Copy className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            Tip: the layout API accepts a full lot layout at
            <code className="mx-1 rounded bg-white px-1">PUT /api/v1/admin/bays/layout/{"{lot}"}</code>
            which makes mirroring the physical thermocol grid a single call.
          </p>
        </aside>
      </div>
    </div>
  );
}
