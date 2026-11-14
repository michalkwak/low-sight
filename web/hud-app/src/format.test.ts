import { describe, expect, it } from "vitest";
import { alertLine, contextBadge, fmt, readout } from "./format";
import { NOW, alert, appState, driving } from "./test/fixtures";

describe("format", () => {
  it("converts units", () => {
    expect(fmt(90, "mmol")).toBe("5.0");
    expect(fmt(70.4, "mgdl")).toBe("70");
  });

  it("dims a reading that is old or has no forecast", () => {
    expect(readout(appState()).stale).toBe(false);
    const old = readout(appState({ reading: { t: "2026-01-01T08:44:00Z", mgdl: 100 } }));
    expect(old).toMatchObject({ stale: true, age: "16 min ago", arrow: "" });
    expect(readout(appState({ forecast: null })).stale).toBe(true);
    expect(readout(appState({ reading: null }))).toMatchObject({ value: "--", age: "No CGM data" });
  });

  it("formats the RECOVERING countdown and leaves other lines alone", () => {
    const until = new Date(Date.parse(NOW) + 65_000).toISOString();
    const rec = alert({ level: "RECOVERING", line: "Wait 15 min · recheck", until });
    expect(alertLine(rec, NOW)).toBe("Recheck in 01:05");
    expect(alertLine({ ...rec, line: "Recheck now" }, until)).toBe("Recheck now");
    expect(alertLine(alert(), NOW)).toBe("Stop safely · take fast carbs");
  });

  it("only badges a wearer who is in a car", () => {
    expect(contextBadge(driving())).toBeNull();
    expect(contextBadge(driving({ role: "driver" }))).toBeNull(); // parked: the seat line covers it
    expect(contextBadge(driving({ driving: true, in_vehicle: true }))?.text).toBe("● In car");
  });
});
