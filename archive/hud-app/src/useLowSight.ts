import { useCallback, useEffect, useRef, useState } from "react";
import type { AppState, ClientMessage } from "./types";

/** Same-origin state socket: wss: when the page is served over https (tunnel, glasses). */
export function defaultWsUrl(): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/state`;
}

const MAX_BACKOFF_MS = 8000;

/** Live AppState from the backend. Reconnects with backoff and keeps the last state
 * on screen (marked by ``status``) while disconnected. */
export function useLowSight(url: string = defaultWsUrl()) {
  const [state, setState] = useState<AppState | null>(null);
  const [status, setStatus] = useState<string | null>("Connecting…");
  const socket = useRef<WebSocket | null>(null);

  useEffect(() => {
    let backoff = 500;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const connect = () => {
      const ws = new WebSocket(url);
      socket.current = ws;
      ws.onopen = () => {
        backoff = 500;
      };
      ws.onmessage = (e: MessageEvent<string>) => {
        setState(JSON.parse(e.data) as AppState);
        setStatus(null);
      };
      ws.onclose = () => {
        if (stopped) return;
        setStatus("Reconnecting…");
        retry = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      socket.current?.close();
    };
  }, [url]);

  const send = useCallback((msg: ClientMessage) => {
    const ws = socket.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }, []);

  return { state, status, send };
}
