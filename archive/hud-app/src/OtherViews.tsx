import { TextColor, TextStyle, TextView } from "@wearables-ui-toolkit/mrbd";
import { fmt } from "./format";
import type { AppState } from "./types";

/** View 1: the +10/+20/+30 min forecast with its band. */
export function ForecastView({ state }: { state: AppState }) {
  const fc = state.forecast;
  return (
    <section className="view" data-view="forecast">
      <TextView as="h1" textStyle={TextStyle.HEADING1} className="view-title">
        Forecast
      </TextView>
      {!fc ? (
        <TextView textStyle={TextStyle.BODY1} textColor={TextColor.SECONDARY}>
          No forecast
        </TextView>
      ) : (
        <div className="fc-rows">
          {fc.horizons_min.map((h, i) => (
            <div className="fc-row" key={h}>
              <TextView textStyle={TextStyle.BODY1} textColor={TextColor.SECONDARY}>
                +{h} min
              </TextView>
              <TextView textStyle={TextStyle.BODY1_EMPHASIZED}>{fmt(fc.mean[i], state.units)}</TextView>
              <TextView textStyle={TextStyle.BODY2} textColor={TextColor.SECONDARY}>
                ({fmt(fc.lo[i], state.units)}–{fmt(fc.hi[i], state.units)})
              </TextView>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** View 2: what LowSight is, the disclaimer, and the controls. */
export function AboutView() {
  return (
    <section className="view" data-view="about">
      <TextView as="h1" textStyle={TextStyle.HEADING1} className="view-title">
        LowSight
      </TextView>
      <TextView as="p" textStyle={TextStyle.BODY1} className="about">
        Low-glucose alerts while driving.
      </TextView>
      <TextView as="p" textStyle={TextStyle.BODY1} textColor={TextColor.SECONDARY} className="about">
        Decision support only. Not medical advice. Never suggests insulin doses.
      </TextView>
      <TextView as="p" textStyle={TextStyle.BODY2} textColor={TextColor.SECONDARY} className="about">
        Select: acknowledge alert · ◀ ▶ switch views
      </TextView>
    </section>
  );
}
