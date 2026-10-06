import { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { useAuth } from "./context/AuthContext";
import { LoadingState } from "./components/ui";
import Login from "./pages/Login";
import DriverHome from "./pages/DriverHome";
import Vehicles from "./pages/Vehicles";
import GateKiosk from "./pages/GateKiosk";
import LiveLotMap from "./pages/LiveLotMap";
import AdminDashboard from "./pages/AdminDashboard";
import Rules from "./pages/Rules";
import BayEditor from "./pages/BayEditor";
import Simulator from "./pages/Simulator";
import Metrics from "./pages/Metrics";

function RequireAuth({ children, roles }: { children: ReactNode; roles?: string[] }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <LoadingState label="Checking your session…" />;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (roles && !roles.includes(user.role)) {
    return (
      <div className="card border-amber-300 bg-amber-50" role="alert">
        <p className="font-semibold text-amber-900">Not allowed</p>
        <p className="text-sm text-amber-800">
          This page needs the {roles.join(" or ")} role. You are signed in as {user.role}.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/live" element={<LiveLotMap />} />

        <Route
          path="/"
          element={
            <RequireAuth>
              <DriverHome />
            </RequireAuth>
          }
        />
        <Route
          path="/vehicles"
          element={
            <RequireAuth>
              <Vehicles />
            </RequireAuth>
          }
        />
        <Route
          path="/kiosk"
          element={
            <RequireAuth>
              <GateKiosk />
            </RequireAuth>
          }
        />

        <Route
          path="/admin"
          element={
            <RequireAuth roles={["admin"]}>
              <AdminDashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/admin/rules"
          element={
            <RequireAuth roles={["admin"]}>
              <Rules />
            </RequireAuth>
          }
        />
        <Route
          path="/admin/bays"
          element={
            <RequireAuth roles={["admin"]}>
              <BayEditor />
            </RequireAuth>
          }
        />
        <Route
          path="/admin/simulator"
          element={
            <RequireAuth roles={["admin"]}>
              <Simulator />
            </RequireAuth>
          }
        />
        <Route
          path="/admin/metrics"
          element={
            <RequireAuth roles={["admin"]}>
              <Metrics />
            </RequireAuth>
          }
        />

        <Route
          path="*"
          element={
            <div className="card text-center">
              <p className="text-lg font-semibold">Page not found</p>
              <a className="btn-primary mt-3 inline-flex" href="/live">
                Go to the live map
              </a>
            </div>
          }
        />
      </Routes>
    </Layout>
  );
}
