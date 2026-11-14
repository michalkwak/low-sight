// LowSight voice tools (WebMCP): the wearer asks Meta AI on the glasses, Meta AI calls these.
//   "What's my glucose?" / "Am I going low?" / "How long until I recheck?" → lowsight_get_status
//   "OK, I'm pulling over." / "Got it."                                    → lowsight_acknowledge_alert
//   "Show me the forecast."                                                → lowsight_show_view
//   "I'm driving." / "I'm a passenger."                                    → lowsight_confirm_seat
// Additive only: hud.js works fully by D-pad when document.modelContext is absent or a
// registration fails. This file touches no DOM; hud.js passes in the state and actions it owns,
// so the tools call the same paths as the D-pad and the screen re-renders as usual.
// Contract (Meta's WebMCP skill): scalar parameters only; `enum`/`default` are dropped, so
// constraints live in descriptions; no failure flag in results, so handled problems are
// ordinary JSON results with a next_action; throw only for cancellation.
(function (root) {
  "use strict";

  const GUARD =
    "Never give insulin or carbohydrate doses or other treatment advice beyond the alert's own " +
    "message, and never say it is safe to drive: report the numbers and alerts only.";
  const ACK_CONFIRM_MS = 4000; // wait this long for the backend to confirm an acknowledgement
  const VIEW_ALIASES = {
    glucose: "glucose", main: "glucose", home: "glucose", value: "glucose", number: "glucose", reading: "glucose",
    forecast: "forecast", graph: "forecast", chart: "forecast", prediction: "forecast", history: "forecast", trend: "forecast",
    about: "about", info: "about", help: "about", disclaimer: "about",
  };

  // Exact values only. Meta AI interprets what the wearer said ("I'm driving, not a
  // passenger") far better than a regex can; a wrong "passenger" would silence driving
  // alerts, so anything that isn't exactly "driver" or "passenger" is sent back as a question.
  function resolveSeat(text) {
    const s = String(text || "").trim().toLowerCase();
    return s === "driver" || s === "passenger" ? s : null;
  }

  // While these alerts are up, a wearer "passenger" is ignored (backend too): one stray
  // tap or misheard sentence must not clear an urgent warning.
  const URGENT = ["PULL_OVER", "PRE_DRIVE"];

  // A handled problem is an ordinary result (the host treats any fulfilled result as success
  // and JSON-stringifies it): Meta AI reads `error`, explains `message` and follows next_action.
  function problem(message, next_action) {
    return { error: true, message, next_action };
  }

  // ---- status: plain facts from the HUD's state, in the wearer's units ----
  function buildStatus(state, h) {
    if (!state) return { connection: "connecting", glucose: null, alert: null, forecast: [] };
    const units = h.unitLabel(state.units);
    const now = new Date(state.now);
    const r = state.reading;
    let glucose = null;
    if (r) {
      const minutesOld = Math.max(0, Math.round((now - new Date(r.t)) / 60000));
      const stale = minutesOld >= 15 || !state.forecast;
      glucose = { value: h.fmt(r.mgdl, state.units), units, minutes_old: minutesOld, stale };
      if (stale) {
        glucose.trend = "unknown (no current trend)";
      } else {
        glucose.trend = h.trendWords[state.arrow] || "unknown";
        const per10 = (state.trend_mgdl_min || 0) * 10;
        glucose.change_per_10_min = `${per10 < 0 ? "-" : "+"}${h.fmt(Math.abs(per10), state.units)} ${units}`;
      }
    }

    const fc = state.forecast;
    const forecast = fc
      ? fc.horizons_min.map((m, i) => ({
          in_minutes: m,
          expected: h.fmt(fc.mean[i], state.units),
          range: `${h.fmt(fc.lo[i], state.units)}–${h.fmt(fc.hi[i], state.units)}`,
        }))
      : [];

    const a = state.alert || { level: "NONE" };
    let alert = null;
    if (a.level && a.level !== "NONE") {
      alert = { level: a.level, title: a.title, message: a.line, acknowledged: !!a.acked };
      if (a.level === "RECOVERING" && a.until) {
        const left = Math.round((new Date(a.until) - now) / 60000);
        alert.recheck = left > 0 ? `in about ${left} min` : "now";
      }
    }

    const d = state.driving || {};
    return {
      connection: h.connected() ? "live" : "reconnecting (values may be out of date)",
      glucose,
      forecast,
      alert,
      driving: { in_car: !!d.in_vehicle, driving: !!d.driving, seat: d.role || "unknown" },
    };
  }

  // ---- tools ----
  function createTools(api) {
    const h = api;
    const status = () => buildStatus(api.getState(), h);

    // Resolve once the backend's state shows `test` true; reject on cancellation.
    function waitForState(test, ms, signal) {
      return new Promise((resolve, reject) => {
        let off = () => {};
        const finish = (ok) => { clearTimeout(timer); off(); signal && signal.removeEventListener("abort", onAbort); resolve(ok); };
        const onAbort = () => { clearTimeout(timer); off(); reject(signal.reason || new Error("aborted")); };
        const timer = setTimeout(() => finish(false), ms);
        if (signal) {
          if (signal.aborted) return onAbort();
          signal.addEventListener("abort", onAbort, { once: true });
        }
        off = api.onState((s) => { if (test(s)) finish(true); });
        if (test(api.getState())) finish(true);
      });
    }

    return [
      {
        name: "lowsight_get_status",
        description:
          "Current glucose reading, trend, short forecast and any active LowSight alert " +
          "(e.g. LOW_SOON, PULL_OVER, RECOVERING with its recheck time), plus whether the wearer is driving. " +
          "Call this first for any question about glucose, going low, alerts or rechecking. " + GUARD,
        inputSchema: { type: "object", properties: {} },
        annotations: { readOnlyHint: true },
        execute: async () => {
          api.showView("glucose"); // the detail goes on screen; the spoken line stays short
          const s = { ...status(), on_screen: "glucose" };
          if (!s.glucose) {
            return {
              ...s,
              next_action: s.connection === "connecting"
                ? "Say LowSight is still connecting and to ask again in a moment. Stop and talk."
                : "Say there is no current glucose reading from the sensor. Stop and talk.",
            };
          }
          return {
            ...s,
            next_action:
              "Say one short sentence: the value with its units and its trend, plus the alert's title if there is one " +
              "(or how old the reading is, if it is stale). The forecast and details are on screen: do not read them " +
              "out unless asked. " + GUARD + " Stop and talk.",
          };
        },
      },
      {
        name: "lowsight_acknowledge_alert",
        description:
          "Acknowledge the active LowSight alert when the wearer says they've got it (e.g. \"OK\", \"got it\", " +
          "\"I'm pulling over\"). Same as pressing Select: it stops the alert repeating; it does not clear it.",
        inputSchema: { type: "object", properties: {} },
        execute: async (_args, opts) => {
          const signal = opts && opts.signal;
          const s = api.getState();
          const a = s && s.alert;
          if (!a || !a.level || a.level === "NONE") {
            return problem("There is no active alert to acknowledge.", "Tell the wearer there's no alert right now. Stop and talk.");
          }
          if (a.acked) {
            return { acknowledged: true, already: true, alert: status().alert,
              next_action: "Say it was already acknowledged, in a few words. Stop and talk." };
          }
          if (!api.connected()) {
            return problem("LowSight is reconnecting, so the alert could not be acknowledged.",
              "Tell the wearer to pinch (Select) to acknowledge, or try again in a moment. Stop and talk.");
          }
          const id = a.id;
          if (!api.acknowledge()) {
            return problem("The acknowledgement could not be sent.", "Tell the wearer to pinch (Select) to acknowledge. Stop and talk.");
          }
          // The page is the referee: report success only once the backend's state confirms it.
          const ok = await waitForState(
            (st) => !!(st && st.alert && (st.alert.id !== id || st.alert.acked)), api.ackConfirmMs || ACK_CONFIRM_MS, signal);
          if (!ok) {
            return problem("LowSight did not confirm the acknowledgement.",
              "Tell the wearer to pinch (Select) to acknowledge. Stop and talk.");
          }
          return {
            acknowledged: true,
            alert: status().alert,
            next_action: "Confirm in one short sentence and repeat the alert's message. " + GUARD + " Stop and talk.",
          };
        },
      },
      {
        name: "lowsight_confirm_seat",
        description:
          "Record which seat the wearer is in, when they say so (e.g. \"I'm driving\", \"I'm the driver\", " +
          "\"I'm a passenger\", \"I'm not driving\"). driver: LowSight warns them about lows while the car moves. " +
          "passenger: driving alerts pause for this trip (their CGM's own alarms still apply). " +
          "Only call this when the wearer clearly states their seat; never guess it. If unsure, ask them.",
        inputSchema: {
          type: "object",
          properties: {
            seat: { type: "string", description: 'Exactly "driver" or "passenger" (decide from what the wearer said).' },
          },
          required: ["seat"],
        },
        execute: async (args, opts) => {
          const signal = opts && opts.signal;
          const seat = resolveSeat(args && args.seat);
          if (!seat) {
            return problem("The seat must be exactly \"driver\" or \"passenger\".",
              "Stop and ask, in one short question, whether they are driving or a passenger. When they answer, " +
              'call lowsight_confirm_seat with seat "driver" or "passenger".');
          }
          if (!api.connected()) {
            return problem("LowSight is reconnecting, so the seat could not be saved.",
              "Tell the wearer to try again in a moment. Stop and talk.");
          }
          const now = api.getState();
          if (now && now.driving && now.driving.role_source === "forced") {
            return problem("The seat is set by the demo control panel's override, so it can't be changed by voice.",
              "Tell the wearer the seat is fixed by an override right now. Stop and talk.");
          }
          if (seat === "passenger" && now && now.alert && URGENT.includes(now.alert.level)) {
            return problem("A pull-over or pre-drive alert is active, so LowSight won't switch to passenger now.",
              "Tell the wearer the alert stays on until their glucose recovers, and to pinch (Select) to acknowledge it. " +
              GUARD + " Stop and talk.");
          }
          if (!api.confirmSeat || !api.confirmSeat(seat)) {
            return problem("The seat could not be sent.", "Tell the wearer to try again in a moment. Stop and talk.");
          }
          const ok = await waitForState(
            (st) => !!(st && st.driving && st.driving.role === seat), api.ackConfirmMs || ACK_CONFIRM_MS, signal);
          if (!ok) {
            return problem("LowSight did not confirm the seat.", "Tell the wearer to try again in a moment. Stop and talk.");
          }
          // Return the state after the change, so the model never has to ask what happened:
          // saying "driver" while low raises CHECK BEFORE DRIVING, and that is what to say.
          const after = status();
          let next_action;
          if (after.alert && !after.alert.acknowledged) {
            next_action = "In one short sentence, say the seat is saved and give the alert's message. " + GUARD + " Stop and talk.";
          } else if (seat === "driver") {
            next_action = "Confirm in one short sentence that LowSight will warn them about lows while they drive. " + GUARD + " Stop and talk.";
          } else {
            next_action = "Confirm in one short sentence that LowSight won't give driving instructions this trip but will still warn about lows. " + GUARD + " Stop and talk.";
          }
          return { seat, alert: after.alert, driving: after.driving, next_action };
        },
      },
      {
        name: "lowsight_show_view",
        description:
          "Switch the glasses display to a view: glucose (value, trend ring and alert), " +
          "forecast (3-hour graph and the next 30 minutes), or about (disclaimer and controls).",
        inputSchema: {
          type: "object",
          properties: {
            view: { type: "string", description: 'One of "glucose", "forecast" or "about".' },
          },
          required: ["view"],
        },
        execute: async (args) => {
          const raw = String((args && args.view) || "").trim().toLowerCase();
          const view = VIEW_ALIASES[raw] || VIEW_ALIASES[raw.split(/\s+/).find((w) => VIEW_ALIASES[w]) || ""];
          if (!view) {
            return problem(`There is no "${raw}" view.`, 'Call again with view "glucose", "forecast" or "about".');
          }
          api.showView(view);
          const result = { showing: view, next_action: "Confirm in a few words. Stop and talk." };
          if (view === "forecast") result.forecast = status().forecast;
          return result;
        },
      },
    ];
  }

  // registerTool may throw, return a promise, a handle or nothing depending on the build.
  // One guarded call per tool, so one failure can't strand the others or break the HUD.
  function safeRegister(ctx, tool, signal) {
    try {
      const result = ctx.registerTool(tool, signal ? { signal } : undefined);
      if (result && typeof result.then === "function") {
        result.then(undefined, (err) => console.error(`${tool.name} registration failed`, err));
      }
      return true;
    } catch (err) {
      console.error(`${tool.name} registration failed`, err);
      return false;
    }
  }

  function register(ctx, api, signal) {
    if (!ctx || typeof ctx.registerTool !== "function") return 0;
    let n = 0;
    for (const tool of createTools(api)) if (safeRegister(ctx, tool, signal)) n++;
    return n;
  }

  // Dev only (/hud/?dev without a real modelContext): a minimal registry so /hud/dev.html can
  // call the tools the way Meta AI would. Never used on the glasses.
  function createLocalContext() {
    const tools = new Map();
    return {
      registerTool(tool) {
        if (!tool || !tool.name || typeof tool.execute !== "function") throw new TypeError("invalid tool");
        if (tools.has(tool.name)) throw new Error(`duplicate tool ${tool.name}`);
        tools.set(tool.name, tool);
      },
      async getTools() {
        return [...tools.values()].map(({ name, description, inputSchema }) => ({ name, description, inputSchema }));
      },
      // Mirrors the host: input is a JSON string, the result resolves to a JSON string. A result
      // with a `content` array is reduced to its concatenated text entries; anything else is
      // JSON-stringified. Missing required parameters are rejected before execute runs.
      async executeTool(toolOrName, inputJson, signal) {
        const name = typeof toolOrName === "string" ? toolOrName : toolOrName && toolOrName.name;
        const tool = tools.get(name);
        if (!tool) throw new Error(`no tool ${name}`);
        const input = inputJson ? JSON.parse(inputJson) : {};
        for (const key of (tool.inputSchema && tool.inputSchema.required) || []) {
          if (input[key] === undefined) throw new TypeError(`missing required parameter ${key}`);
        }
        const result = await tool.execute(input, { signal: signal || AbortSignal.timeout(10000) });
        if (result && Array.isArray(result.content)) {
          return result.content.filter((c) => c.type === "text").map((c) => c.text).join("");
        }
        return JSON.stringify(result);
      },
      async call(name, args) {
        const tool = tools.get(name);
        if (!tool) throw new Error(`no tool ${name}`);
        return tool.execute(args || {}, { signal: AbortSignal.timeout(10000) });
      },
    };
  }

  const API = { buildStatus, createTools, register, safeRegister, createLocalContext, resolveSeat, GUARD };
  root.LowSightWebMCP = API;
  if (typeof module === "object" && module.exports) module.exports = API;
})(typeof window !== "undefined" ? window : globalThis);
