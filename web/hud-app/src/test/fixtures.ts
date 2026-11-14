import type { Alert, AppState, DrivingState } from "../types";

export const NOW = "2026-01-01T09:00:00Z";
const at = (min: number) => new Date(Date.parse(NOW) + min * 60e3).toISOString();

export function alert(over: Partial<Alert> = {}): Alert {
  return {
    level: "PULL_OVER",
    title: "PULL OVER",
    line: "Stop safely · take fast carbs",
    speak: "Your glucose is low. Pull over when it's safe and take fast-acting sugar.",
    acked: false,
    id: "e1-1-pull_over",
    since: NOW,
    until: null,
    spoken: false,
    ...over,
  };
}

export function driving(over: Partial<DrivingState> = {}): DrivingState {
  return {
    driving: false,
    in_vehicle: false,
    role: "unknown",
    p_driver: 0.5,
    speed_kmh: null,
    car_connected: false,
    phone_stale: true,
    source: "phone",
    since: NOW,
    seat_checking: false,
    ...over,
  };
}

export function appState(over: Partial<AppState> = {}): AppState {
  return {
    now: NOW,
    reading: { t: NOW, mgdl: 128.8 },
    trend_mgdl_min: 0,
    arrow: "→",
    forecast: { t0: NOW, horizons_min: [10, 20, 30], mean: [128, 127, 126], lo: [122, 115, 106], hi: [134, 139, 146] },
    driving: driving(),
    alert: { ...alert(), level: "NONE", title: "", line: "", speak: null, id: "" },
    history: [-20, -15, -10, -5, 0].map((m) => ({ t: at(m), mgdl: 130 - m / 5 })),
    units: "mmol",
    scenario: "falling_while_driving",
    speed: 30,
    paused: false,
    ...over,
  };
}

/** Stand-in for the browser WebSocket: tests open it, push states and read what was sent. */
export class MockSocket {
  static instances: MockSocket[] = [];
  static readonly OPEN = 1;
  readyState = 0;
  sent: unknown[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    MockSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  push(state: AppState) {
    this.onmessage?.({ data: JSON.stringify(state) });
  }
}
