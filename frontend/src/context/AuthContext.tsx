import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  ReactNode,
} from "react";
import { api, getCachedUser, setCachedUser, setToken, getToken } from "../services/api";
import { User } from "../types";

interface RegisterPayload {
  name: string;
  email: string;
  password: string;
  priority_tier?: number;
  needs_accessible?: boolean;
}

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (payload: RegisterPayload) => Promise<User>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => getCachedUser<User>());
  const [loading, setLoading] = useState<boolean>(Boolean(getToken()));

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api<User>("/api/v1/auth/me");
      setUser(me);
      setCachedUser(me);
    } catch {
      setUser(null);
      setCachedUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api<{ access_token: string; user: User }>("/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
      auth: false,
    });
    setToken(res.access_token);
    setCachedUser(res.user);
    setUser(res.user);
    return res.user;
  }, []);

  const register = useCallback(async (payload: RegisterPayload) => {
    const res = await api<{ access_token: string; user: User }>("/api/v1/auth/register", {
      method: "POST",
      body: payload,
      auth: false,
    });
    setToken(res.access_token);
    setCachedUser(res.user);
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setCachedUser(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout, refresh }),
    [user, loading, login, register, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
