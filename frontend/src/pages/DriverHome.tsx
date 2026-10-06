import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bell,
  Car,
  CheckCheck,
  Clock,
  MapPin,
  ParkingSquare,
  Ticket,
  X,
} from "lucide-react";
import { api, ApiError } from "../services/api";
import { useLive } from "../hooks/useLive";
import { useAuth } from "../context/AuthContext";
import ExplanationPanel from "../components/ExplanationPanel";
import { EmptyState, ErrorState, LoadingState, SimulatedBadge, StatusPill } from "../components/ui";
import { AppNotification, Building, MeStatus, Vehicle } from "../types";

export default function DriverHome() {
  const { user } = useAuth();
  const [status, setStatus] = useState<MeStatus | null>(null);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<MeStatus>("/api/v1/me/status")
      .then((data) => {
        setStatus(data);
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load status"));
    api<Vehicle[]>("/api/v1/vehicles").then(setVehicles).catch(() => undefined);
    api<AppNotification[]>("/api/v1/me/notifications?limit=20")
      .then(setNotifications)
      .catch(() => undefined);
    api<Building[]>("/api/v1/buildings", { auth: false })
      .then(setBuildings)
      .catch(() => undefined);
  }, []);

  useLive(load);
  useEffect(load, [load]);

  const setDestination = async (buildingId: string) => {
    setBusy(true);
    try {
      await api("/api/v1/me/destination", {
        method: "PUT",
        body: { building_id: buildingId || null },
      });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save destination");
    } finally {
      setBusy(false);
    }
  };

  const activateVehicle = async (id: string) => {
    setBusy(true);
    try {
      await api(`/api/v1/vehicles/${id}/activate`, { method: "POST" });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not switch vehicle");
    } finally {
      setBusy(false);
    }
  };

  const leaveWaitlist = async () => {
    setBusy(true);
    try {
      await api("/api/v1/waitlist/leave", { method: "POST", body: {} });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not leave the queue");
    } finally {
      setBusy(false);
    }
  };

  const markRead = async (id: string) => {
    await api(`/api/v1/me/notifications/${id}/read`, { method: "POST" }).catch(() => undefined);
    load();
  };

  if (!status && !error) return <LoadingState label="Loading your parking status…" />;
  if (!status && error) return <ErrorState message={error} onRetry={load} />;

  const parking = status?.current_parking ?? null;
  const waiting = status?.waitlist ?? null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">
            {user ? `Hello, ${user.name.split(" ")[0]}` : "My parking"}
          </h1>
          <p className="text-sm text-slate-600">Your bay, your queue place and your notifications.</p>
        </div>
        <div className="flex gap-2">
          <SimulatedBadge />
          <Link to="/kiosk" className="btn-primary">
            <ParkingSquare className="h-4 w-4" aria-hidden /> Open gate kiosk
          </Link>
        </div>
      </div>

      {error && <ErrorState message={error} onRetry={load} />}

      <div className="grid gap-5 lg:grid-cols-3">
        <section className="card lg:col-span-2">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold text-slate-800">
            <Car className="h-5 w-5 text-brand-600" aria-hidden /> My parking
          </h2>

          {parking ? (
            <div className="space-y-3">
              <div className="rounded-xl border-2 border-emerald-300 bg-emerald-50 p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-xl font-bold text-emerald-900">
                    {parking.bay.lot_name} · Bay {parking.bay.label}
                  </p>
                  <StatusPill tone={parking.status === "occupied" ? "green" : "amber"}>
                    {parking.status === "occupied" ? "Parked" : "Allotted — drive in now"}
                  </StatusPill>
                </div>
                <p className="mt-2 flex items-center gap-2 text-sm text-emerald-900">
                  <MapPin className="h-4 w-4" aria-hidden />
                  {parking.walk_hint.text}
                </p>
                <p className="text-xs text-emerald-800">{parking.walk_hint.note}</p>
                <p className="mt-2 flex items-center gap-2 text-sm text-emerald-900">
                  <Clock className="h-4 w-4" aria-hidden />
                  {status?.grace_minutes} minute grace period from allotment
                </p>
                {parking.bay.is_accessible && (
                  <p className="mt-2 text-sm font-semibold text-emerald-900">
                    ♿ Accessible bay held for you (step-free route)
                  </p>
                )}
                {parking.explanation && <ExplanationPanel explanation={parking.explanation} />}
              </div>
            </div>
          ) : waiting ? (
            <div className="rounded-xl border-2 border-amber-300 bg-amber-50 p-4">
              <p className="text-lg font-bold text-amber-900">
                You are #{waiting.position} on the waitlist
              </p>
              <p className="mt-1 text-sm text-amber-800">
                {waiting.preferred_lot ? `Preferred lot: ${waiting.preferred_lot}. ` : ""}
                You will get a notification the moment a bay frees up — it is then held for you
                for {status?.grace_minutes} minutes.
              </p>
              <div className="mt-3 flex gap-2">
                <button type="button" className="btn-secondary" onClick={leaveWaitlist} disabled={busy}>
                  <X className="h-4 w-4" aria-hidden /> Leave the queue
                </button>
              </div>
            </div>
          ) : (
            <EmptyState
              title="You don't hold a bay right now"
              hint="Scan your vehicle in at the gate kiosk to get an allotment with a full explanation."
              action={
                <Link to="/kiosk" className="btn-primary mt-2 inline-flex">
                  <ParkingSquare className="h-4 w-4" aria-hidden /> Scan in at the kiosk
                </Link>
              }
            />
          )}
        </section>

        <aside className="space-y-4">
          <section className="card">
            <h2 className="mb-2 flex items-center gap-2 text-lg font-bold text-slate-800">
              <Ticket className="h-5 w-5 text-brand-600" aria-hidden /> Today's vehicle
            </h2>
            {vehicles.length === 0 ? (
              <div className="text-sm text-slate-600">
                <p>No vehicles yet.</p>
                <Link to="/vehicles" className="btn-primary mt-2 inline-flex">
                  Register a vehicle
                </Link>
              </div>
            ) : (
              <ul className="space-y-2">
                {vehicles.map((v) => (
                  <li key={v.id}>
                    <button
                      type="button"
                      onClick={() => activateVehicle(v.id)}
                      disabled={busy}
                      aria-pressed={v.active_today}
                      className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-sm ${
                        v.active_today
                          ? "border-brand-500 bg-brand-50 font-semibold"
                          : "border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <span className="font-mono">{v.plate_or_tag_id}</span>
                      <span className="text-xs text-slate-500">
                        {v.type === "two_wheeler" ? "2-wheeler" : "4-wheeler"}
                        {v.active_today && " · active"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card">
            <h2 className="mb-2 text-lg font-bold text-slate-800">Destination</h2>
            <label className="label" htmlFor="destination">Building I'm heading to</label>
            <select
              id="destination"
              className="input"
              value={status?.destination_building_id ?? ""}
              onChange={(e) => setDestination(e.target.value)}
              disabled={busy}
            >
              <option value="">Not set</option>
              {buildings.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-slate-500">
              Used to rank bays by walking distance.
            </p>
          </section>
        </aside>
      </div>

      <section className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-bold text-slate-800">
            <Bell className="h-5 w-5 text-brand-600" aria-hidden /> Notifications
            {(status?.unread_notifications ?? 0) > 0 && (
              <span className="pill border border-rose-300 bg-rose-100 text-rose-800">
                {status?.unread_notifications} unread
              </span>
            )}
          </h2>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => api("/api/v1/me/notifications/read-all", { method: "POST" }).then(load)}
          >
            <CheckCheck className="h-4 w-4" aria-hidden /> Mark all read
          </button>
        </div>

        {notifications.length === 0 ? (
          <p className="text-sm text-slate-500">No notifications yet.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {notifications.map((n) => (
              <li key={n.id} className="flex items-start justify-between gap-3 py-2">
                <div>
                  <p className={`text-sm ${n.read ? "text-slate-600" : "font-semibold text-slate-900"}`}>
                    {!n.read && <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-brand-600" aria-label="unread" />}
                    {n.message}
                  </p>
                  <p className="text-xs text-slate-400">
                    {n.ts ? new Date(n.ts + "Z").toLocaleString() : ""} · {n.channel}
                    {n.channel !== "in_app" && " (simulated channel)"}
                  </p>
                </div>
                {!n.read && (
                  <button
                    type="button"
                    className="btn-secondary !px-2 !py-1 text-xs"
                    onClick={() => markRead(n.id)}
                  >
                    Mark read
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
