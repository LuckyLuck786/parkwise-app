/**
 * Live updates.
 *
 * Primary channel: Server-Sent Events on /api/v1/events/stream.
 * Fallback: polling /api/v1/events/poll every 5 seconds.
 *
 * The fallback engages automatically when SSE is unavailable (blocked by the
 * host, proxy buffering, connection drop) and recovers when SSE reconnects.
 * Both carry the same DB-backed state version, so the UI behaves identically.
 */

import { api } from "./api";

export type LiveStatus = "connecting" | "sse" | "polling" | "offline";

interface PollResponse {
  version: number;
  changed: boolean;
  since: number;
  server_time: string;
  last_kind?: string;
}

export interface LiveHandle {
  close: () => void;
}

export function subscribeLive(
  onVersion: (version: number) => void,
  onStatus?: (status: LiveStatus) => void,
): LiveHandle {
  let closed = false;
  let source: EventSource | null = null;
  let pollTimer: number | null = null;
  let since = 0;
  let sawFirstEvent = false;

  const startPolling = () => {
    if (closed || pollTimer !== null) return;
    onStatus?.("polling");
    const tick = async () => {
      if (closed) return;
      try {
        const res = await api<PollResponse>(`/api/v1/events/poll?since=${since}`, { auth: false });
        if (res.changed) {
          since = res.version;
          onVersion(res.version);
        } else {
          since = res.version;
        }
        onStatus?.("polling");
      } catch {
        onStatus?.("offline");
      }
    };
    tick();
    pollTimer = window.setInterval(tick, 5000);
  };

  const stopPolling = () => {
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  };

  const startSse = () => {
    if (closed || typeof EventSource === "undefined") {
      startPolling();
      return;
    }
    onStatus?.("connecting");
    source = new EventSource("/api/v1/events/stream");

    source.onopen = () => {
      if (!closed) onStatus?.("sse");
    };

    source.onmessage = (event) => {
      sawFirstEvent = true;
      try {
        const data = JSON.parse(event.data) as { version: number };
        if (typeof data.version === "number") {
          since = data.version;
          onVersion(data.version);
        }
        onStatus?.("sse");
      } catch {
        /* heartbeat comment frames land here */
      }
    };

    source.onerror = () => {
      // EventSource retries on its own; poll meanwhile so the UI never stalls.
      source?.close();
      source = null;
      startPolling();
      if (!closed) window.setTimeout(startSse, 8000);
    };
  };

  startSse();

  return {
    close() {
      closed = true;
      source?.close();
      stopPolling();
    },
  };
}
