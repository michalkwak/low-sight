import { ActionHint, Tag, TextColor, TextStyle, TextView } from "@wearables-ui-toolkit/mrbd";
import { alertLine, contextBadge, readout, unitLabel } from "./format";
import { Sparkline } from "./Sparkline";
import type { Alert, AppState } from "./types";

interface Props {
  state: AppState;
  seatResult: "driver" | "passenger" | null;
}

/** View 0: value + arrow top right, alert banner at the bottom (outline only: the
 * display is additive, so no large bright fills). */
export function GlucoseView({ state, seatResult }: Props) {
  const r = readout(state);
  const d = state.driving;
  const alert = state.alert;
  const alerting = alert.level !== "NONE";
  const badge = contextBadge(d);
  // No sparkline while driving or alerting: minimal visual load, room for the banner.
  const quiet = !d.driving && !alerting;

  let seatLine: { text: string; cls: string } | null = null;
  if (seatResult === "driver") seatLine = { text: "Driver seat ✓", cls: "seat" };
  else if (seatResult === "passenger") seatLine = { text: "Passenger seat", cls: "seat muted" };
  else if (d.seat_checking) seatLine = { text: "Checking seat…", cls: "seat muted" };

  return (
    <section className="view glucose" data-view="glucose">
      {alerting && <Banner alert={alert} now={state.now} />}
      <div className={`readout${r.stale ? " stale" : ""}`}>
        <div className="value-row">
          <TextView textStyle={TextStyle.NUMERAL1} className="value" data-testid="value">
            {r.value}
          </TextView>
          {r.arrow && (
            <TextView textStyle={TextStyle.NUMERAL2} className="arrow" data-testid="arrow">
              {r.arrow}
            </TextView>
          )}
        </div>
        <div className="meta-row">
          <TextView textStyle={TextStyle.BODY2} textColor={TextColor.SECONDARY}>
            {unitLabel(state.units)}
          </TextView>
          {r.age && (
            <TextView textStyle={TextStyle.BODY2} textColor={TextColor.SECONDARY} data-testid="age">
              {r.age}
            </TextView>
          )}
        </div>
        {quiet && <Sparkline state={state} />}
        {badge && <Tag text={badge.text} className={`badge ${badge.tone}`} data-testid="badge" />}
        {seatLine && (
          <TextView as="div" textStyle={TextStyle.BODY2_EMPHASIZED} className={seatLine.cls} data-testid="seat">
            {seatLine.text}
          </TextView>
        )}
      </div>
    </section>
  );
}

function Banner({ alert, now }: { alert: Alert; now: string }) {
  return (
    <div className={`banner ${alert.level}${alert.acked ? " acked" : ""}`} role="alert" data-testid="banner">
      <TextView as="div" textStyle={TextStyle.HEADING1} className="banner-title">
        {alert.acked ? `${alert.title} ✓` : alert.title}
      </TextView>
      <TextView as="div" textStyle={TextStyle.BODY1} className="banner-line">
        {alertLine(alert, now)}
      </TextView>
      {!alert.acked && <ActionHint text="Select to acknowledge" className="banner-hint" />}
    </div>
  );
}
