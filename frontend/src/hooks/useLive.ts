import { useEffect, useRef, useState } from "react";
import { subscribeLive, LiveStatus } from "../services/live";

/**
 * Subscribe to backend state changes. `onChange` fires whenever the DB state
 * version bumps (allocation, bay event, rules edit, demo action...).
 *
 * Uses SSE with an automatic polling fallback — see services/live.ts.
 */
export function useLive(onChange: () => void): LiveStatus {
  const cbRef = useRef(onChange);
  cbRef.current = onChange;
  const [status, setStatus] = useState<LiveStatus>("connecting");

  useEffect(() => {
    const handle = subscribeLive(
      () => cbRef.current(),
      (s) => setStatus(s),
    );
    return () => handle.close();
  }, []);

  return status;
}

/** Debounced refetch helper: collapse bursts of live updates into one call. */
export function useDebouncedRefresh(fn: () => void, delay = 400) {
  const timer = useRef<number | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  return () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => fnRef.current(), delay);
  };
}
