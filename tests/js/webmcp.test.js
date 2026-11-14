// Tests for web/hud/webmcp.js (LowSight's Meta AI voice tools). Run: node --test tests/js/*.test.js
// (also run by pytest through tests/test_webmcp_js.py).
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const W = require(path.join(__dirname, "..", "..", "web", "hud", "webmcp.js"));

// Same helpers hud.js passes in.
const fmt = (mgdl, units) => (units === "mmol" ? (mgdl / 18).toFixed(1) : Math.round(mgdl).toString());
const unitLabel = (u) => (u === "mmol" ? "mmol/L" : "mg/dL");
const TREND_WORDS = {
  "⇈": "rising fast", "↑": "rising", "↗": "rising slowly", "→": "steady",
  "↘": "falling slowly", "↓": "falling", "⇊": "falling fast",
};
const NOW = "2026-01-01T08:00:00Z";

function makeState(over = {}) {
  return {
    now: NOW,
    reading: { t: NOW, mgdl: 83 },
    trend_mgdl_min: -3.2,
    arrow: "⇊",
    forecast: { t0: NOW, horizons_min: [10, 20, 30], mean: [65, 50, 40], lo: [58, 42, 40], hi: [72, 58, 48] },
    driving: { driving: true, in_vehicle: true, role: "driver" },
    alert: { level: "PULL_OVER", title: "PULL OVER", line: "Stop safely · fast carbs", acked: false, id: "a1" },
    units: "mmol",
    ...over,
  };
}

// A fake HUD: the same api object hud.js builds, with state the test controls.
function makeApi(state, { connected = true, ackConfirmMs = 200 } = {}) {
  const listeners = new Set();
  const api = {
    state,
    calls: { ack: 0, views: [], seats: [] },
    getState: () => api.state,
    onState: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
    emit(s) { api.state = s; listeners.forEach((fn) => fn(s)); },
    listenerCount: () => listeners.size,
    connected: () => connected,
    acknowledge: () => { api.calls.ack++; return true; },
    confirmSeat: (role) => { api.calls.seats.push(role); return true; },
    showView: (v) => api.calls.views.push(v),
    fmt, unitLabel, trendWords: TREND_WORDS, ackConfirmMs,
  };
  return api;
}

const tool = (api, name) => W.createTools(api).find((t) => t.name === name);
const parse = (r) => (typeof r === "string" ? JSON.parse(r) : r);

// ---- tool contract ----

test("tool names are unique, not reserved, and fit Meta AI's 57-character budget", () => {
  const reserved = ["openUrl", "goBack", "goForward", "reload", "getCurrentUrl", "getPageTitle", "getPageText"];
  const names = W.createTools(makeApi(null)).map((t) => t.name);
  assert.deepEqual(names, ["lowsight_get_status", "lowsight_acknowledge_alert", "lowsight_confirm_seat", "lowsight_show_view"]);
  assert.equal(new Set(names.map((n) => n.slice(0, 57))).size, names.length);
  for (const n of names) assert.ok(!reserved.includes(n) && n.length <= 57, n);
});

test("parameters are scalar only, descriptions fit the truncation limits", () => {
  for (const t of W.createTools(makeApi(null))) {
    assert.ok(t.description.length <= 1024, `${t.name} description too long`);
    for (const [k, p] of Object.entries(t.inputSchema.properties)) {
      assert.ok(["string", "number", "integer", "boolean"].includes(p.type), `${t.name}.${k}`);
      assert.ok(p.description.length <= 256);
    }
  }
});

test("status tool is marked read-only", () => {
  assert.equal(tool(makeApi(null), "lowsight_get_status").annotations.readOnlyHint, true);
});

// ---- registration must never break the HUD ----

const N_TOOLS = W.createTools(makeApi(null)).length;

function ctxReturning(fn) {
  const names = [];
  return { names, registerTool(t, opts) { names.push(t.name); return fn(t, opts); } };
}

test("registers every tool when registerTool returns undefined", () => {
  const ctx = ctxReturning(() => undefined);
  assert.equal(W.register(ctx, makeApi(null)), N_TOOLS);
  assert.equal(ctx.names.length, N_TOOLS);
});

test("registers every tool when registerTool returns a non-thenable handle", () => {
  const ctx = ctxReturning(() => ({ unregister() {} }));
  assert.equal(W.register(ctx, makeApi(null)), N_TOOLS);
});

test("a rejected registration is logged, not thrown, and others still register", async () => {
  const errors = [];
  const orig = console.error;
  console.error = (...a) => errors.push(a.join(" "));
  try {
    const ctx = ctxReturning((t) => (t.name === "lowsight_get_status" ? Promise.reject(new Error("nope")) : Promise.resolve()));
    assert.equal(W.register(ctx, makeApi(null)), N_TOOLS);
    await new Promise((r) => setTimeout(r, 0));
    assert.ok(errors.some((e) => e.includes("lowsight_get_status registration failed")));
  } finally {
    console.error = orig;
  }
});

test("a synchronous throw on one tool does not strand the others", () => {
  const orig = console.error;
  console.error = () => {};
  try {
    const ctx = ctxReturning((t) => { if (t.name === "lowsight_get_status") throw new TypeError("bad"); });
    assert.equal(W.register(ctx, makeApi(null)), N_TOOLS - 1);
    assert.equal(ctx.names.length, N_TOOLS);
  } finally {
    console.error = orig;
  }
});

test("no model context: registers nothing and does not throw", () => {
  assert.equal(W.register(undefined, makeApi(null)), 0);
  assert.equal(W.register({}, makeApi(null)), 0);
});

// ---- lowsight_get_status ----

test("status reports value, trend, forecast and alert in the wearer's units", async () => {
  const r = parse(await tool(makeApi(makeState()), "lowsight_get_status").execute({}));
  assert.equal(r.connection, "live");
  assert.deepEqual(r.glucose, {
    value: "4.6", units: "mmol/L", minutes_old: 0, stale: false, trend: "falling fast", change_per_10_min: "-1.8 mmol/L",
  });
  assert.deepEqual(r.forecast[0], { in_minutes: 10, expected: "3.6", range: "3.2–4.0" });
  assert.deepEqual(r.alert, { level: "PULL_OVER", title: "PULL OVER", message: "Stop safely · fast carbs", acknowledged: false });
  assert.deepEqual(r.driving, { in_car: true, driving: true, seat: "driver" });
  assert.match(r.next_action, /never give insulin/i);
  assert.match(r.next_action, /never say it is safe to drive/i);
});

test("status in mg/dL", async () => {
  const r = parse(await tool(makeApi(makeState({ units: "mgdl" })), "lowsight_get_status").execute({}));
  assert.equal(r.glucose.value, "83");
  assert.equal(r.glucose.change_per_10_min, "-32 mg/dL");
});

test("stale reading: says how old, no trend", async () => {
  const st = makeState({ reading: { t: "2026-01-01T07:40:00Z", mgdl: 100 } });
  const r = parse(await tool(makeApi(st), "lowsight_get_status").execute({}));
  assert.equal(r.glucose.stale, true);
  assert.equal(r.glucose.minutes_old, 20);
  assert.match(r.glucose.trend, /unknown/);
  assert.equal(r.glucose.change_per_10_min, undefined);
});

test("no data and not yet connected are handled results", async () => {
  const none = parse(await tool(makeApi(makeState({ reading: null })), "lowsight_get_status").execute({}));
  assert.equal(none.glucose, null);
  assert.match(none.next_action, /no current glucose reading/);
  const connecting = parse(await tool(makeApi(null), "lowsight_get_status").execute({}));
  assert.match(connecting.next_action, /still connecting/);
});

test("RECOVERING reports the recheck time", async () => {
  const st = makeState({ alert: { level: "RECOVERING", title: "WAIT · RECHECK", line: "Recheck now", acked: true, id: "r1", until: "2026-01-01T08:12:00Z" } });
  const r = parse(await tool(makeApi(st), "lowsight_get_status").execute({}));
  assert.equal(r.alert.recheck, "in about 12 min");
});

test("reconnecting is flagged so the assistant doesn't present old values as live", async () => {
  const r = parse(await tool(makeApi(makeState(), { connected: false }), "lowsight_get_status").execute({}));
  assert.match(r.connection, /reconnecting/);
});

// ---- lowsight_acknowledge_alert ----

test("acknowledge succeeds only after the backend confirms", async () => {
  const api = makeApi(makeState());
  const pending = tool(api, "lowsight_acknowledge_alert").execute({}, {});
  assert.equal(api.calls.ack, 1);
  setTimeout(() => api.emit(makeState({ alert: { ...makeState().alert, acked: true } })), 10);
  const r = parse(await pending);
  assert.equal(r.acknowledged, true);
  assert.equal(r.alert.acknowledged, true);
  assert.equal(api.listenerCount(), 0, "listener cleaned up");
});

test("acknowledge without confirmation is a handled problem, not a success", async () => {
  const api = makeApi(makeState(), { ackConfirmMs: 30 });
  const r = parse(await tool(api, "lowsight_acknowledge_alert").execute({}, {}));
  assert.equal(r.error, true);
  assert.match(r.next_action, /pinch/);
  assert.equal(api.listenerCount(), 0);
});

test("acknowledge with no alert, already acked, or disconnected", async () => {
  const none = parse(await tool(makeApi(makeState({ alert: { level: "NONE" } })), "lowsight_acknowledge_alert").execute({}, {}));
  assert.equal(none.error, true);

  const acked = parse(await tool(makeApi(makeState({ alert: { ...makeState().alert, acked: true } })), "lowsight_acknowledge_alert").execute({}, {}));
  assert.equal(acked.already, true);

  const api = makeApi(makeState(), { connected: false });
  const off = parse(await tool(api, "lowsight_acknowledge_alert").execute({}, {}));
  assert.equal(off.error, true);
  assert.equal(api.calls.ack, 0);
});

test("acknowledge is cancelled when the assistant's deadline aborts it", async () => {
  const api = makeApi(makeState(), { ackConfirmMs: 5000 });
  const ac = new AbortController();
  const pending = tool(api, "lowsight_acknowledge_alert").execute({}, { signal: ac.signal });
  ac.abort();
  await assert.rejects(pending);
  assert.equal(api.listenerCount(), 0);
});

// ---- lowsight_show_view ----

test("show_view switches views, accepts spoken aliases, rejects unknown ones", async () => {
  const api = makeApi(makeState());
  const t = tool(api, "lowsight_show_view");
  const fc = parse(await t.execute({ view: "Forecast" }));
  assert.equal(fc.showing, "forecast");
  assert.equal(fc.forecast.length, 3);
  assert.equal(parse(await t.execute({ view: "the chart" })).showing, "forecast");
  assert.equal(parse(await t.execute({ view: "main" })).showing, "glucose");
  assert.deepEqual(api.calls.views, ["forecast", "forecast", "glucose"]);

  const bad = parse(await t.execute({ view: "settings" }));
  assert.equal(bad.error, true);
  assert.match(bad.next_action, /glucose.*forecast.*about/);
  const missing = parse(await t.execute(undefined));
  assert.equal(missing.error, true);
  assert.equal(api.calls.views.length, 3);
});

// ---- dev registry ----

test("dev local context calls tools like Meta AI and rejects duplicates", async () => {
  const ctx = W.createLocalContext();
  assert.equal(W.register(ctx, makeApi(makeState())), N_TOOLS);
  assert.equal((await ctx.getTools()).length, N_TOOLS);
  const r = parse(await ctx.call("lowsight_get_status", {}));
  assert.equal(r.glucose.value, "4.6");
  const orig = console.error;
  console.error = () => {};
  try { assert.equal(W.register(ctx, makeApi(makeState())), 0); } finally { console.error = orig; }
});

// ---- seat confirmation ("I'm driving" / "I'm a passenger") ----

test("seat must be exactly driver or passenger: free text is never guessed", () => {
  assert.equal(W.resolveSeat("driver"), "driver");
  assert.equal(W.resolveSeat(" Passenger "), "passenger");
  // Meta AI decides the seat; phrases (including negations that a regex got wrong) are sent back as a question.
  for (const t of ["I'm driving, not a passenger", "not the passenger", "I won't be driving", "my wife is driving",
                   "I'm not driving", "pilot", "", null, undefined]) assert.equal(W.resolveSeat(t), null, String(t));
});

test("confirm_seat succeeds only after the backend shows the new role, and returns the new state", async () => {
  const quiet = { level: "NONE" };
  const api = makeApi(makeState({ alert: quiet, driving: { driving: false, in_vehicle: false, role: "unknown" } }));
  const run = tool(api, "lowsight_confirm_seat").execute({ seat: "driver" });
  assert.deepEqual(api.calls.seats, ["driver"]);
  api.emit(makeState({ alert: quiet, driving: { driving: false, in_vehicle: false, role: "driver" } }));
  const r = parse(await run);
  assert.equal(r.seat, "driver");
  assert.equal(r.driving.seat, "driver");
  assert.equal(r.alert, null);
  assert.match(r.next_action, /warn them about lows/);
});

test("confirm_seat reports an alert the seat change raised (low + 'I'm driving')", async () => {
  const quiet = { level: "NONE" };
  const api = makeApi(makeState({ alert: quiet, driving: { role: "unknown" } }));
  const run = tool(api, "lowsight_confirm_seat").execute({ seat: "driver" });
  api.emit(makeState({
    driving: { driving: false, in_vehicle: false, role: "driver" },
    alert: { level: "PRE_DRIVE", title: "CHECK BEFORE DRIVING", line: "Treat before you set off", acked: false, id: "p1" },
  }));
  const r = parse(await run);
  assert.equal(r.alert.level, "PRE_DRIVE");
  assert.match(r.next_action, /alert's message/);
  assert.match(r.next_action, /Stop and talk/);
});

test("confirm_seat: unknown seat, disconnected, or unconfirmed are handled problems", async () => {
  const bad = parse(await tool(makeApi(makeState()), "lowsight_confirm_seat").execute({ seat: "pilot" }));
  assert.equal(bad.error, true);
  const off = parse(await tool(makeApi(makeState(), { connected: false }), "lowsight_confirm_seat").execute({ seat: "driver" }));
  assert.equal(off.error, true);
  const api = makeApi(makeState({ driving: { role: "unknown" } }), { ackConfirmMs: 50 });
  const silent = parse(await tool(api, "lowsight_confirm_seat").execute({ seat: "passenger" }));
  assert.equal(silent.error, true); // the backend never confirmed
});

test("confirm_seat refuses passenger during PULL_OVER/PRE_DRIVE, and explains an override", async () => {
  const api = makeApi(makeState()); // PULL_OVER active
  const r = parse(await tool(api, "lowsight_confirm_seat").execute({ seat: "passenger" }));
  assert.equal(r.error, true);
  assert.deepEqual(api.calls.seats, []); // nothing sent
  const forced = makeApi(makeState({ alert: { level: "NONE" }, driving: { role: "driver", role_source: "forced" } }));
  const f = parse(await tool(forced, "lowsight_confirm_seat").execute({ seat: "passenger" }));
  assert.equal(f.error, true);
  assert.match(f.message, /override/);
});

// ---- result contract ----

test("status puts the glucose view on screen and asks for one short sentence", async () => {
  const api = makeApi(makeState());
  const r = parse(await tool(api, "lowsight_get_status").execute({}));
  assert.deepEqual(api.calls.views, ["glucose"]);
  assert.equal(r.on_screen, "glucose");
  assert.match(r.next_action, /one short sentence/);
  assert.match(r.next_action, /do not read them out/);
});

test("handled problems are plain objects, so the host stringifies them once", async () => {
  const r = await tool(makeApi(makeState()), "lowsight_confirm_seat").execute({ seat: "pilot" });
  assert.equal(typeof r, "object");
  assert.equal(r.error, true);
  assert.ok(r.next_action);
});

test("every result from every tool ends with a next_action", async () => {
  const api = makeApi(makeState({ alert: { level: "NONE" } }), { ackConfirmMs: 20 });
  const calls = [["lowsight_get_status", {}], ["lowsight_acknowledge_alert", {}],
                 ["lowsight_confirm_seat", { seat: "nope" }], ["lowsight_show_view", { view: "nowhere" }],
                 ["lowsight_show_view", { view: "forecast" }]];
  for (const [name, args] of calls) {
    const r = parse(await tool(api, name).execute(args));
    assert.ok(typeof r.next_action === "string" && r.next_action.length > 0, name);
  }
});

test("host-style executeTool: JSON string in, JSON string out, required params enforced", async () => {
  const ctx = W.createLocalContext();
  const api = makeApi(makeState());
  W.register(ctx, api);
  const tools = await ctx.getTools();
  const view = tools.find((t) => t.name === "lowsight_show_view");
  assert.deepEqual(view.inputSchema.required, ["view"]);
  const out = await ctx.executeTool(view, JSON.stringify({ view: "forecast" }));
  assert.equal(typeof out, "string");
  assert.equal(JSON.parse(out).showing, "forecast");
  await assert.rejects(ctx.executeTool(view, "{}"), /missing required parameter view/);
});
