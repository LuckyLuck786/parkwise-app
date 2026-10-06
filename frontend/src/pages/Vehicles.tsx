import { FormEvent, useCallback, useEffect, useState } from "react";
import { Bike, Car, Plus, Trash2, CheckCircle2 } from "lucide-react";
import { api, ApiError } from "../services/api";
import { useLive } from "../hooks/useLive";
import { EmptyState, ErrorState, LoadingState, StatusPill } from "../components/ui";
import { Vehicle, VehicleType } from "../types";

export default function Vehicles() {
  const [vehicles, setVehicles] = useState<Vehicle[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [plate, setPlate] = useState("");
  const [type, setType] = useState<VehicleType>("four_wheeler");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<Vehicle[]>("/api/v1/vehicles")
      .then((data) => {
        setVehicles(data);
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load vehicles"));
  }, []);

  useLive(load);
  useEffect(load, [load]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/v1/vehicles", {
        method: "POST",
        body: { plate_or_tag_id: plate, type },
      });
      setPlate("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add vehicle");
    } finally {
      setBusy(false);
    }
  };

  const activate = async (id: string) => {
    await api(`/api/v1/vehicles/${id}/activate`, { method: "POST" }).then(load).catch(() => undefined);
  };

  const remove = async (id: string) => {
    setBusy(true);
    try {
      await api(`/api/v1/vehicles/${id}`, { method: "DELETE" });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove vehicle");
    } finally {
      setBusy(false);
    }
  };

  if (!vehicles && !error) return <LoadingState label="Loading vehicles…" />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">My vehicles</h1>
        <p className="text-sm text-slate-600">
          Up to three vehicles per account. Only one can hold a bay at a time.
        </p>
      </div>

      {error && <ErrorState message={error} onRetry={load} />}

      <section className="card">
        <h2 className="mb-3 text-lg font-bold text-slate-800">Register a vehicle</h2>
        <form onSubmit={add} className="flex flex-wrap items-end gap-3">
          <div className="min-w-[220px] flex-1">
            <label className="label" htmlFor="plate">Plate or tag ID</label>
            <input
              id="plate"
              className="input font-mono uppercase"
              placeholder="KA-01-AB-1234 or QR-TAG-001"
              value={plate}
              onChange={(e) => setPlate(e.target.value)}
              required
              minLength={3}
            />
          </div>
          <div>
            <label className="label" htmlFor="vtype">Type</label>
            <select id="vtype" className="input" value={type} onChange={(e) => setType(e.target.value as VehicleType)}>
              <option value="four_wheeler">Four-wheeler</option>
              <option value="two_wheeler">Two-wheeler</option>
            </select>
          </div>
          <button type="submit" className="btn-primary" disabled={busy}>
            <Plus className="h-4 w-4" aria-hidden /> Add
          </button>
        </form>
      </section>

      <section className="card">
        <h2 className="mb-3 text-lg font-bold text-slate-800">Registered vehicles</h2>
        {!vehicles || vehicles.length === 0 ? (
          <EmptyState
            title="No vehicles yet"
            hint="Add your car or bike above — you can then scan it in at the gate kiosk."
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {vehicles.map((v) => (
              <li key={v.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="flex items-center gap-3">
                  {v.type === "two_wheeler" ? (
                    <Bike className="h-5 w-5 text-slate-500" aria-hidden />
                  ) : (
                    <Car className="h-5 w-5 text-slate-500" aria-hidden />
                  )}
                  <div>
                    <p className="font-mono font-semibold text-slate-800">{v.plate_or_tag_id}</p>
                    <p className="text-xs text-slate-500">
                      {v.type === "two_wheeler" ? "Two-wheeler" : "Four-wheeler"}
                      {v.masked && " · plate masked"}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {v.active_today ? (
                    <StatusPill tone="green" icon={<CheckCircle2 className="h-3 w-3" aria-hidden />}>
                      Active today
                    </StatusPill>
                  ) : (
                    <button type="button" className="btn-secondary" onClick={() => activate(v.id)} disabled={busy}>
                      Use today
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn-secondary !px-2.5"
                    onClick={() => remove(v.id)}
                    disabled={busy}
                    aria-label={`Remove ${v.plate_or_tag_id}`}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
