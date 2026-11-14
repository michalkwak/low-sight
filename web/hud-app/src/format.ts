// Pure display helpers (unit-tested in format.test.ts).
import type { Alert, AppState, DrivingState, Units } from "./types";

export const fmt = (mgdl: number, units: Units): string =>
  units === "mmol" ? (mgdl / 18).toFixed(1) : String(Math.round(mgdl));

export const unitLabel = (units: Units): string => (units === "mmol" ? "mmol/L" : "mg/dL");

/** A reading older than this, or no forecast (sensor gap), is shown dimmed with its age. */
export const STALE_MIN = 15;

export interface ReadoutText {
  value: string;
  arrow: string;
  age: string; // "" when fresh
  stale: boolean;
}

export function readout(state: AppState): ReadoutText {
  const r = state.reading;
  if (!r) return { value: "--", arrow: "", age: "No CGM data", stale: true };
  const ageMin = Math.round((Date.parse(state.now) - Date.parse(r.t)) / 60000);
  const stale = ageMin >= STALE_MIN || !state.forecast;
  return {
    value: fmt(r.mgdl, state.units),
    arrow: stale ? "" : state.arrow,
    age: stale ? `${ageMin} min ago` : "",
    stale,
  };
}

/** RECOVERING: "Recheck in mm:ss" on the demo clock, then the engine's own line ("Recheck now"). */
export function alertLine(alert: Alert, now: string): string {
  if (alert.level !== "RECOVERING" || !alert.until) return alert.line;
  const left = Math.round((Date.parse(alert.until) - Date.parse(now)) / 1000);
  if (left <= 0) return alert.line;
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  return `Recheck in ${mm}:${ss}`;
}

export type BadgeTone = "active" | "muted";

/** Context badge: who the wearer is in the car, if they're in one. */
export function contextBadge(d: DrivingState): { text: string; tone: BadgeTone } | null {
  if (d.role === "driver" && (d.driving || d.in_vehicle)) return { text: "● Driver", tone: "active" };
  if (d.role === "passenger" && d.in_vehicle) return { text: "● Passenger", tone: "muted" };
  if (d.driving) return { text: "● In car", tone: "active" };
  return null;
}
