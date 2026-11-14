import { PaginationIndicator, PaginationMode, TextStyle, TextView } from "@wearables-ui-toolkit/mrbd";
import { useEffect, useRef, useState } from "react";
import { GlucoseView } from "./GlucoseView";
import { AboutView, ForecastView } from "./OtherViews";
import { speakHere, useAlertAudio } from "./useAlertAudio";
import { useLowSight } from "./useLowSight";
import { useSeatResult } from "./useSeatResult";
import type { Alert } from "./types";

export const VIEWS = ["glucose", "forecast", "about"] as const;

interface Props {
  url?: string; // state socket; defaults to same-origin /ws/state
  speak?: (a: Alert) => void;
}

/** The glasses app: a glanceable HUD. Input is the D-pad: ←/→ cycle views and Enter
 * (Neural Band select) acknowledges the current alert. The HUD has no focusable
 * controls, so it takes those keys itself (capture phase, before the toolkit's focus
 * navigation) and needs no focus target: the simulator and the glasses deliver plain
 * keydown events. */
export function Hud({ url, speak = speakHere }: Props) {
  const { state, status, send } = useLowSight(url);
  const [view, setView] = useState(0);
  const alert = state?.alert;
  const seatResult = useSeatResult(state?.driving.role);
  useAlertAudio(alert, speak);

  // Keep the latest alert for the key handler without re-binding it every second.
  const latestAlert = useRef(alert);
  latestAlert.current = alert;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") setView((v) => (v + 1) % VIEWS.length);
      else if (e.key === "ArrowLeft") setView((v) => (v + VIEWS.length - 1) % VIEWS.length);
      else if (e.key === "Enter") {
        const a = latestAlert.current;
        if (a && a.level !== "NONE" && !a.acked) {
          send({ type: "ack", id: a.id });
          setView(0);
        }
      } else return;
      e.preventDefault();
    };
    document.addEventListener("keydown", onKey, { capture: true });
    return () => document.removeEventListener("keydown", onKey, { capture: true });
  }, [send]);

  // A new alert is always visible, whatever view is open.
  const alertId = alert && alert.level !== "NONE" ? alert.id : "";
  useEffect(() => {
    if (alertId) setView(0);
  }, [alertId]);

  return (
    <main className={`hud${status ? " offline" : ""}`} aria-live="polite" aria-label="LowSight">
      {state && view === 0 && <GlucoseView state={state} seatResult={seatResult} />}
      {state && view === 1 && <ForecastView state={state} />}
      {view === 2 && <AboutView />}
      {!state && view !== 2 && (
        <section className="view" data-view="glucose">
          <div className="readout">
            <TextView textStyle={TextStyle.NUMERAL1} className="value" data-testid="value">
              --
            </TextView>
          </div>
        </section>
      )}
      {status && (
        <TextView textStyle={TextStyle.BODY2} className="status" data-testid="status">
          {status}
        </TextView>
      )}
      <PaginationIndicator
        className="dots"
        mode={PaginationMode.DOTS}
        pageCount={VIEWS.length}
        currentPage={view}
        aria-label={`View ${view + 1} of ${VIEWS.length}`}
      />
    </main>
  );
}
