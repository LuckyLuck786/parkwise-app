/**
 * Tiny fetch wrapper.
 *
 * - Attaches the JWT when present
 * - Turns FastAPI error payloads into Error objects with a readable message
 * - Retries a 401 briefly, then clears the session and sends the user to /login
 *
 * Why retry a 401: on the deployed serverless pool each warm instance keeps its
 * own SQLite file, so the first call after a fresh sign-up can land on an
 * instance that has not seen the new account yet. A genuinely expired token
 * still fails after the retries and logs out exactly as before.
 */

const TOKEN_KEY = "parkwise.token";
const USER_KEY = "parkwise.user";
const RETRY_401_ATTEMPTS = 3;
const RETRY_401_DELAY_MS = 250;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function getCachedUser<T>(): T | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function setCachedUser(user: unknown | null) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  else localStorage.removeItem(USER_KEY);
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean;
  signal?: AbortSignal;
}

async function extractMessage(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
    if (Array.isArray(data?.detail)) {
      return data.detail
        .map((d: { msg?: string; loc?: unknown[] }) => `${d.msg ?? ""}`)
        .join("; ");
    }
    if (typeof data?.message === "string") return data.message;
    return JSON.stringify(data);
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, auth = true, signal } = options;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (auth && token) headers.Authorization = `Bearer ${token}`;

  for (let attempt = 1; ; attempt++) {
    let res: Response;
    try {
      res = await fetch(path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      });
    } catch {
      throw new ApiError(0, "Cannot reach the ParkWise API. Is the backend running?");
    }

    if (res.status === 401 && auth && token) {
      // A 401 is rejected before the route handler runs, so retrying cannot
      // repeat a side effect — but it does not mask a genuinely bad token.
      if (attempt < RETRY_401_ATTEMPTS) {
        await sleep(RETRY_401_DELAY_MS * attempt);
        continue;
      }
      setToken(null);
      setCachedUser(null);
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
      throw new ApiError(401, "Session expired — please sign in again.");
    }

    if (!res.ok) {
      throw new ApiError(res.status, await extractMessage(res));
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }
}

/** API helper that never throws on 404 — returns null instead. */
export async function apiOrNull<T>(path: string, options: RequestOptions = {}): Promise<T | null> {
  try {
    return await api<T>(path, options);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}
