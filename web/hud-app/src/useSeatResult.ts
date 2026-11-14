import { useState } from "react";
import type { Role } from "./types";

/** How long "Driver seat ✓" / "Passenger seat" stays after a seat check decides. */
export const SEAT_SHOW_MS = 6000;

/** The seat-check result to show briefly when the role changes while the HUD is open.
 * A role that was already decided when the HUD opened isn't announced again. The state
 * pushes (1 Hz) re-render the HUD, which hides the line once it has expired. */
export function useSeatResult(role: Role | undefined): "driver" | "passenger" | null {
  const [prevRole, setPrevRole] = useState(role);
  const [result, setResult] = useState<{ role: "driver" | "passenger"; until: number } | null>(null);
  if (role !== prevRole) {
    // Derived state from the previous render (React's recommended pattern; no effect needed).
    setPrevRole(role);
    const first = prevRole === undefined; // the first state after opening
    setResult(!first && (role === "driver" || role === "passenger") ? { role, until: Date.now() + SEAT_SHOW_MS } : null);
  }
  return result && Date.now() < result.until ? result.role : null;
}
