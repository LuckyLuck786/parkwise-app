import { ReactNode, useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import {
  Car,
  LayoutDashboard,
  LogOut,
  Map as MapIcon,
  ParkingMeter,
  Settings2,
  ShieldAlert,
  SlidersHorizontal,
  Timer,
  Contrast,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useLive } from "../hooks/useLive";
import { StatusPill } from "./ui";
import { api } from "../services/api";

interface Snapshot {
  version: number;
  clock: string;
  waitlist_length: number;
}

function useContrast(): [boolean, () => void] {
  const [high, setHigh] = useState(
    () => localStorage.getItem("parkwise.contrast") === "high",
  );
  useEffect(() => {
    document.documentElement.dataset.contrast = high ? "high" : "normal";
    localStorage.setItem("parkwise.contrast", high ? "high" : "normal");
  }, [high]);
  return [high, () => setHigh((v) => !v)];
}

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const [highContrast, toggleContrast] = useContrast();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const location = useLocation();

  const refreshSnapshot = () => {
    api<Snapshot>("/api/v1/live/snapshot", { auth: false })
      .then(setSnapshot)
      .catch(() => setSnapshot(null));
  };

  const liveStatus = useLive(refreshSnapshot);

  useEffect(() => {
    refreshSnapshot();
    const id = window.setInterval(refreshSnapshot, 30000);
    return () => window.clearInterval(id);
  }, []);

  const role = user?.role;
  const navItemClass = ({ isActive }: { isActive: boolean }) =>
    `inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
      isActive
        ? "bg-brand-700 text-white"
        : "text-slate-700 hover:bg-slate-200/70"
    }`;

  const clock = snapshot ? new Date(snapshot.clock + "Z") : null;

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        Skip to main content
      </a>

      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
          <Link to="/live" className="flex items-center gap-2 text-lg font-bold text-brand-700">
            <ParkingMeter className="h-6 w-6" aria-hidden />
            ParkWise
          </Link>

          <nav aria-label="Main" className="flex flex-1 flex-wrap items-center gap-1">
            <NavLink to="/live" className={navItemClass}>
              <MapIcon className="h-4 w-4" aria-hidden /> Live map
            </NavLink>
            {user && (
              <NavLink to="/" end className={navItemClass}>
                <Car className="h-4 w-4" aria-hidden /> My parking
              </NavLink>
            )}
            {user && (
              <NavLink to="/vehicles" className={navItemClass}>
                Vehicles
              </NavLink>
            )}
            {user && (
              <NavLink to="/kiosk" className={navItemClass}>
                Gate kiosk
              </NavLink>
            )}
            {role === "admin" && (
              <>
                <NavLink to="/admin" end className={navItemClass}>
                  <LayoutDashboard className="h-4 w-4" aria-hidden /> Dashboard
                </NavLink>
                <NavLink to="/admin/simulator" className={navItemClass}>
                  <Timer className="h-4 w-4" aria-hidden /> Simulator
                </NavLink>
                <NavLink to="/admin/rules" className={navItemClass}>
                  <Settings2 className="h-4 w-4" aria-hidden /> Rules
                </NavLink>
                <NavLink to="/admin/bays" className={navItemClass}>
                  <SlidersHorizontal className="h-4 w-4" aria-hidden /> Bay editor
                </NavLink>
                <NavLink to="/admin/metrics" className={navItemClass}>
                  <ShieldAlert className="h-4 w-4" aria-hidden /> Metrics
                </NavLink>
              </>
            )}
          </nav>

          <div className="flex items-center gap-2">
            <span
              className={`hidden items-center gap-1.5 text-xs font-medium sm:inline-flex ${
                liveStatus === "sse"
                  ? "text-emerald-700"
                  : liveStatus === "polling"
                    ? "text-amber-700"
                    : "text-slate-500"
              }`}
              title={`Live updates: ${liveStatus === "sse" ? "streaming (SSE)" : liveStatus === "polling" ? "polling fallback" : liveStatus}`}
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  liveStatus === "sse"
                    ? "bg-emerald-500"
                    : liveStatus === "polling"
                      ? "bg-amber-500"
                      : "bg-slate-400"
                }`}
                aria-hidden
              />
              {liveStatus === "sse" ? "Live" : liveStatus === "polling" ? "Polling" : "Offline"}
            </span>

            {clock && (
              <span
                className="pill border border-slate-300 bg-slate-100 text-slate-700 tabular-nums"
                title="Demo clock (virtual time)"
              >
                {Number.isNaN(clock.getTime()) ? snapshot?.clock : clock.toISOString().slice(11, 16)} UTC
              </span>
            )}

            <button
              type="button"
              onClick={toggleContrast}
              className="btn-secondary !px-2.5"
              aria-pressed={highContrast}
              title="Toggle high contrast mode"
            >
              <Contrast className="h-4 w-4" aria-hidden />
              <span className="sr-only">Toggle high contrast</span>
            </button>

            {user ? (
              <div className="flex items-center gap-2">
                <span className="hidden text-sm text-slate-600 sm:inline">
                  {user.name}
                  <span className="ml-1 rounded bg-slate-200 px-1.5 py-0.5 text-xs font-semibold uppercase">
                    {user.role === "gate_operator" ? "gate" : user.role}
                    {user.priority_tier ? ` · T${user.priority_tier}` : ""}
                  </span>
                </span>
                <button type="button" onClick={logout} className="btn-secondary !px-2.5">
                  <LogOut className="h-4 w-4" aria-hidden />
                  <span className="sr-only">Sign out</span>
                </button>
              </div>
            ) : (
              <Link to="/login" className="btn-primary">
                Sign in
              </Link>
            )}
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        {children}
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-3 text-xs text-slate-500">
          <span>
            ParkWise — priority-based campus parking. Decisions are rules-based and audit-logged.
          </span>
          <StatusPill tone="purple">Simulated data in demo mode</StatusPill>
        </div>
      </footer>
    </div>
  );
}
