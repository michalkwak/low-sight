// Mirrors backend/models.py (AppState as pushed on /ws/state). All glucose values are mg/dL.
export type AlertLevel = "NONE" | "LOW_SOON" | "PRE_DRIVE" | "PULL_OVER" | "RECOVERING";
export type Units = "mmol" | "mgdl";
export type Role = "driver" | "passenger" | "unknown";

export interface CGMReading {
  t: string;
  mgdl: number;
}

export interface Forecast {
  t0: string;
  horizons_min: number[];
  mean: number[];
  lo: number[];
  hi: number[];
}

export interface DrivingState {
  driving: boolean;
  in_vehicle: boolean;
  role: Role;
  p_driver: number;
  speed_kmh: number | null;
  car_connected: boolean;
  phone_stale: boolean;
  source: "phone" | "forced";
  since: string;
  seat_checking: boolean;
}

export interface Alert {
  level: AlertLevel;
  title: string;
  line: string;
  speak: string | null;
  acked: boolean;
  id: string;
  since: string | null;
  until: string | null;
  spoken: boolean;
}

export interface AppState {
  now: string;
  reading: CGMReading | null;
  trend_mgdl_min: number;
  arrow: string;
  forecast: Forecast | null;
  driving: DrivingState;
  alert: Alert;
  history: CGMReading[];
  units: Units;
  scenario: string;
  speed: number;
  paused: boolean;
}

/** Client → server messages on /ws/state. */
export type ClientMessage = { type: "ack"; id: string } | { type: "spoken"; id: string };
