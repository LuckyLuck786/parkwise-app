import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LogIn, UserPlus } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../services/api";

const DEMO_ACCOUNTS = [
  { label: "Admin", email: "admin@parkwise.edu", password: "admin123" },
  { label: "Gate operator", email: "gate1@parkwise.edu", password: "gate123" },
  { label: "Tier 1 driver (accessible)", email: "priya.sharma@example.com", password: "pass123" },
  { label: "Tier 2 faculty", email: "anand.rao@example.com", password: "pass123" },
  { label: "Tier 3 driver", email: "amit.kumar@example.com", password: "pass123" },
];

export default function Login() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [tier, setTier] = useState(3);
  const [needsAccessible, setNeedsAccessible] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") {
        const user = await login(email, password);
        navigate(user.role === "admin" ? "/admin" : "/", { replace: true });
      } else {
        await register({
          name,
          email,
          password,
          priority_tier: tier,
          needs_accessible: needsAccessible,
        });
        navigate("/", { replace: true });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unexpected error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-2">
      <section className="card">
        <div className="mb-4 flex gap-2">
          <button
            type="button"
            className={mode === "login" ? "btn-primary" : "btn-secondary"}
            onClick={() => setMode("login")}
            aria-pressed={mode === "login"}
          >
            <LogIn className="h-4 w-4" aria-hidden /> Sign in
          </button>
          <button
            type="button"
            className={mode === "register" ? "btn-primary" : "btn-secondary"}
            onClick={() => setMode("register")}
            aria-pressed={mode === "register"}
          >
            <UserPlus className="h-4 w-4" aria-hidden /> Register
          </button>
        </div>

        <form onSubmit={submit} className="space-y-4">
          {mode === "register" && (
            <div>
              <label className="label" htmlFor="name">Full name</label>
              <input
                id="name"
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                minLength={2}
                autoComplete="name"
              />
            </div>
          )}

          <div>
            <label className="label" htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>

          <div>
            <label className="label" htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
          </div>

          {mode === "register" && (
            <>
              <div>
                <label className="label" htmlFor="tier">Priority tier</label>
                <select
                  id="tier"
                  className="input"
                  value={tier}
                  onChange={(e) => setTier(Number(e.target.value))}
                >
                  <option value={1}>Tier 1 — accessibility / medical need</option>
                  <option value={2}>Tier 2 — faculty, staff, service vehicle</option>
                  <option value={3}>Tier 3 — everyone else</option>
                </select>
                <p className="mt-1 text-xs text-slate-500">
                  Demo shortcut: in production a Tier 1/2 tier is granted by an admin, not chosen
                  at signup.
                </p>
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={needsAccessible}
                  onChange={(e) => setNeedsAccessible(e.target.checked)}
                  className="h-4 w-4"
                />
                I need an accessible (step-free) bay
              </label>
            </>
          )}

          {error && (
            <p className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
      </section>

      <section className="card">
        <h2 className="mb-1 text-lg font-bold text-slate-800">Demo accounts</h2>
        <p className="mb-3 text-sm text-slate-500">
          Click an account to fill the form. All data in this environment is simulated.
        </p>
        <ul className="space-y-2">
          {DEMO_ACCOUNTS.map((acct) => (
            <li key={acct.email}>
              <button
                type="button"
                className="btn-secondary w-full justify-between"
                onClick={() => {
                  setMode("login");
                  setEmail(acct.email);
                  setPassword(acct.password);
                }}
              >
                <span className="font-semibold">{acct.label}</span>
                <span className="font-mono text-xs text-slate-500">{acct.email}</span>
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs text-slate-500">
          Driver password for every seeded driver: <code className="rounded bg-slate-100 px-1">pass123</code>
        </p>
      </section>
    </div>
  );
}
