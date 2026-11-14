import { App } from "@wearables-ui-toolkit/mrbd";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Hud } from "./Hud";
import { PHONE_GRACE_MS } from "./useAlertAudio";
import { SEAT_SHOW_MS } from "./useSeatResult";
import { MockSocket, NOW, alert, appState, driving } from "./test/fixtures";

function open(speak = vi.fn()) {
  render(
    <App>
      <Hud url="ws://test/ws/state" speak={speak} />
    </App>,
  );
  const ws = MockSocket.instances[MockSocket.instances.length - 1];
  act(() => ws.open());
  const push = (s: Parameters<MockSocket["push"]>[0]) => act(() => ws.push(s));
  const key = (k: string) => fireEvent.keyDown(document.body, { key: k });
  return { ws, push, key, speak };
}

beforeEach(() => {
  MockSocket.instances = [];
  vi.stubGlobal("WebSocket", MockSocket);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("HUD", () => {
  it("shows the value, arrow and unit, and clears 'Connecting…' on the first state", () => {
    const { push } = open();
    expect(screen.getByTestId("status").textContent).toBe("Connecting…");
    push(appState());
    expect(screen.getByTestId("value").textContent).toBe("7.2"); // 128.8 mg/dL in mmol/L
    expect(screen.getByTestId("arrow").textContent).toBe("→");
    expect(screen.getByText("mmol/L")).toBeTruthy();
    expect(screen.queryByTestId("status")).toBeNull();
    push(appState({ units: "mgdl" }));
    expect(screen.getByTestId("value").textContent).toBe("129");
  });

  it("marks stale data and says when there is none", () => {
    const { push } = open();
    push(appState({ reading: { t: "2026-01-01T08:40:00Z", mgdl: 100 }, forecast: null }));
    expect(screen.getByTestId("age").textContent).toBe("20 min ago");
    expect(screen.queryByTestId("arrow")).toBeNull();
    push(appState({ reading: null, forecast: null }));
    expect(screen.getByTestId("value").textContent).toBe("--");
    expect(screen.getByText("No CGM data")).toBeTruthy();
  });

  it("shows the alert banner; Enter acknowledges the alert that is on screen", () => {
    const { ws, push, key } = open();
    push(appState({ alert: alert() }));
    const banner = screen.getByTestId("banner");
    expect(banner.textContent).toContain("PULL OVER");
    expect(banner.textContent).toContain("Stop safely · take fast carbs");
    expect(banner.textContent).toContain("Select to acknowledge");
    key("Enter");
    expect(ws.sent).toEqual([{ type: "ack", id: "e1-1-pull_over" }]);
    push(appState({ alert: alert({ acked: true }) }));
    expect(screen.getByTestId("banner").textContent).toContain("PULL OVER ✓");
    expect(screen.getByTestId("banner").textContent).not.toContain("Select to acknowledge");
    key("Enter"); // already acknowledged: nothing more to send
    expect(ws.sent).toHaveLength(1);
  });

  it("cycles views with ←/→ and jumps back to the glucose view on a new alert", () => {
    const { push, key } = open();
    push(appState());
    key("ArrowRight");
    expect(screen.getByText("Forecast")).toBeTruthy();
    expect(screen.getByText("+10 min")).toBeTruthy();
    key("ArrowRight");
    expect(screen.getByText(/Decision support only/)).toBeTruthy();
    key("ArrowRight");
    expect(screen.getByTestId("value")).toBeTruthy(); // wrapped to glucose
    key("ArrowLeft");
    expect(screen.getByText(/Decision support only/)).toBeTruthy();
    push(appState({ alert: alert({ level: "LOW_SOON", title: "LOW IN ~20 MIN", line: "Plan a stop", id: "e1-2" }) }));
    expect(screen.getByTestId("banner").textContent).toContain("LOW IN ~20 MIN");
  });

  it("counts the RECOVERING wait down on the demo clock", () => {
    const { push } = open();
    const until = new Date(Date.parse(NOW) + (12 * 60 + 30) * 1000).toISOString();
    const recovering = alert({ level: "RECOVERING", title: "WAIT · RECHECK", line: "Wait 15 min · recheck", until, id: "e1-3" });
    push(appState({ alert: recovering }));
    expect(screen.getByTestId("banner").textContent).toContain("Recheck in 12:30");
    push(appState({ now: until, alert: { ...recovering, line: "Recheck now" } }));
    expect(screen.getByTestId("banner").textContent).toContain("Recheck now");
  });

  it("speaks only if no phone reported speaking the alert within the grace period", () => {
    vi.useFakeTimers();
    const { push, speak } = open();
    push(appState({ alert: alert({ id: "a1" }) }));
    act(() => vi.advanceTimersByTime(PHONE_GRACE_MS + 10));
    expect(speak).toHaveBeenCalledTimes(1); // no phone: the HUD says it

    push(appState({ alert: alert({ id: "a2" }) }));
    push(appState({ alert: alert({ id: "a2", spoken: true }) })); // the phone said it in time
    act(() => vi.advanceTimersByTime(PHONE_GRACE_MS + 10));
    push(appState({ alert: alert({ id: "a3", speak: null }) })); // silent: already said this episode
    act(() => vi.advanceTimersByTime(PHONE_GRACE_MS + 10));
    expect(speak).toHaveBeenCalledTimes(1);
  });

  it("shows the seat check: checking, then the result for a few seconds", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW));
    const { push } = open();
    push(appState({ driving: driving({ role: "driver" }) }));
    expect(screen.queryByTestId("seat")).toBeNull(); // decided before the HUD opened: no announcement
    push(appState({ driving: driving({ role: "unknown", seat_checking: true }) }));
    expect(screen.getByTestId("seat").textContent).toBe("Checking seat…");
    push(appState({ driving: driving({ role: "driver" }) }));
    expect(screen.getByTestId("seat").textContent).toBe("Driver seat ✓");
    vi.setSystemTime(new Date(Date.parse(NOW) + SEAT_SHOW_MS + 1000));
    push(appState({ driving: driving({ role: "driver" }) }));
    expect(screen.queryByTestId("seat")).toBeNull();
  });

  it("shows who the wearer is in the car", () => {
    const { push } = open();
    push(appState({ driving: driving({ driving: true, in_vehicle: true }) }));
    expect(screen.getByTestId("badge").textContent).toContain("In car");
    push(appState({ driving: driving({ driving: true, in_vehicle: true, role: "driver" }) }));
    expect(screen.getByTestId("badge").textContent).toContain("Driver");
    push(appState({ driving: driving({ in_vehicle: true, role: "passenger" }) }));
    expect(screen.getByTestId("badge").textContent).toContain("Passenger");
    push(appState());
    expect(screen.queryByTestId("badge")).toBeNull();
  });

  it("says 'Reconnecting…', keeps the last value and reconnects with backoff", () => {
    vi.useFakeTimers();
    const { ws, push } = open();
    push(appState());
    act(() => ws.close());
    expect(screen.getByTestId("status").textContent).toBe("Reconnecting…");
    expect(screen.getByTestId("value").textContent).toBe("7.2");
    expect(MockSocket.instances).toHaveLength(1);
    act(() => vi.advanceTimersByTime(600));
    expect(MockSocket.instances).toHaveLength(2);
  });
});
