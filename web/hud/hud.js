// LowSight HUD: the glasses app. 600×600 additive display, D-pad input.
// ←/→ cycle views, Enter (Neural Band select) acknowledges the alert.
// The simulator and the glasses deliver arrows and Enter as keydown events and nothing
// else, and this page has no native controls, so one page-wide key handler owns input.
(() => {
  const $ = (id) => document.getElementById(id);
  const VIEWS = ["glucose", "forecast", "about"];
  // Dev mode (/hud/?dev, embedded by /hud/dev.html): state comes from the dev page's
  // sliders via postMessage instead of the backend.
  const DEV = new URLSearchParams(location.search).has("dev");
  const PHONE_GRACE_MS = 2500; // the phone is the main audio path: give it time to report it spoke
  const SEAT_SHOW_MS = 6000; // how long "Driver seat ✓" stays after the check decides
  let view = 0;
  let state = null;
  let ws = null;
  let backoff = 500;
  let lastAlertId = null;
  let speakTimer = null;
  let prevRole = null;
  let seatResult = null; // { text, cls, until }
  const stateListeners = new Set(); // voice tools (webmcp.js) wait on these for confirmations

  const fmt = (mgdl, units) =>
    units === "mmol" ? (mgdl / 18).toFixed(1) : Math.round(mgdl).toString();
  const unitLabel = (u) => (u === "mmol" ? "mmol/L" : "mg/dL");

  // ---- connection ----
  function wsUrl() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/ws/state`;
  }
  function connect() {
    ws = new WebSocket(wsUrl());
    ws.onopen = () => { backoff = 500; };
    ws.onmessage = (e) => { state = JSON.parse(e.data); setStatus(null); render(); };
    ws.onclose = () => {
      setStatus("Reconnecting…");
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 8000);
    };
    ws.onerror = () => ws.close();
  }
  function setStatus(text) {
    const el = $("status");
    el.textContent = text || "";
    el.classList.toggle("hidden", !text);
    $("hud").classList.toggle("stale", !!text);
  }

  // ---- render ----
  function render() {
    if (!state) return;
    const u = state.units;
    const r = state.reading;
    const now = new Date(state.now);
    const a = state.alert || { level: "NONE" };
    const d = state.driving || {};

    renderGauge(r, now, u, a);
    renderContext(d);
    drawSpark();
    renderBanner(a);
    renderForecast();
    onAlert(a);
    stateListeners.forEach((fn) => { try { fn(state); } catch (err) { console.error(err); } });
  }

  // ---- trend spike ----
  // The spike orbits the ring like a CGM arrow: 0° = steady (pointing right), −90° = rising at
  // FULL_SLOPE or faster (straight up), +90° = falling at FULL_SLOPE or faster (straight down).
  // Between readings it glides to the new angle and its colour blends green → orange (rising)
  // or green → red (falling).
  const FULL_SLOPE = 3; // mg/dL/min; the "⇈ / ⇊" threshold
  const EASE_S = 0.6; // time constant of the glide
  const TREND_WORDS = {
    "⇈": "rising fast", "↑": "rising", "↗": "rising slowly", "→": "steady",
    "↘": "falling slowly", "↓": "falling", "⇊": "falling fast",
  };
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const spike = { angle: null, target: 0, raf: null, last: 0 };
  const css = getComputedStyle(document.documentElement);
  const C_STEADY = oklch(css.getPropertyValue("--steady"));
  const C_RISE = oklch(css.getPropertyValue("--rise"));
  const C_FALL = oklch(css.getPropertyValue("--fall"));

  function spikeTo(slope) {
    const s = Math.max(-1, Math.min(1, slope / FULL_SLOPE));
    spike.target = -s * 90;
    if (spike.angle === null || reduceMotion.matches) { spike.angle = spike.target; drawSpike(); return; }
    if (!spike.raf) { spike.last = performance.now(); spike.raf = requestAnimationFrame(stepSpike); }
  }
  function stepSpike(ts) {
    // Exponential easing is stable for any step, so a slow or throttled frame just catches up.
    const dt = Math.min(1, (ts - spike.last) / 1000);
    spike.last = ts;
    spike.angle += (spike.target - spike.angle) * (1 - Math.exp(-dt / EASE_S));
    if (Math.abs(spike.target - spike.angle) < 0.05) spike.angle = spike.target;
    drawSpike();
    spike.raf = spike.angle === spike.target ? null : requestAnimationFrame(stepSpike);
  }
  function drawSpike() {
    const el = $("spike");
    el.setAttribute("transform", `rotate(${spike.angle.toFixed(2)})`);
    // Mild trends stay green; colour commits as the spike swings toward vertical. Falling is
    // the dangerous direction, so it reaches full red by 45° (−1.5 mg/dL/min) and never rests
    // on the orange that means "rising".
    const u = -spike.angle / 90; // +1 rising fast … −1 falling fast
    const t = u > 0 ? smoothstep(0.1, 0.8, u) : smoothstep(0.05, 0.5, -u);
    el.style.stroke = mixOklch(C_STEADY, u > 0 ? C_RISE : C_FALL, t);
  }

  function renderGauge(r, now, u, a) {
    const g = $("gauge");
    let value = "--", age = "", stale = true;
    if (r) {
      const ageMin = Math.round((now - new Date(r.t)) / 60000);
      stale = ageMin >= 15 || !state.forecast;
      value = fmt(r.mgdl, u);
      if (stale) age = `${ageMin} min ago`;
    } else {
      age = "No CGM data";
    }
    $("value").textContent = value;
    $("value").classList.toggle("long", value.length >= 4);
    $("unit").textContent = unitLabel(u);
    $("age").textContent = age;
    $("age").classList.toggle("hidden", !age);
    g.classList.toggle("stale", stale);
    g.dataset.alert = a.level || "NONE";
    g.classList.toggle("acked", !!a.acked);
    if (!stale && typeof state.trend_mgdl_min === "number") spikeTo(state.trend_mgdl_min);

    const words = !stale && TREND_WORDS[state.arrow];
    $("gauge-label").textContent = r
      ? `Glucose ${value} ${unitLabel(u)}${words ? `, ${words}` : stale ? ", no current trend" : ""}`
      : "No glucose data";
  }

  // ---- colour helpers: blend in OKLCH so the in-between hues stay bright on the display ----
  function smoothstep(e0, e1, x) {
    const t = Math.max(0, Math.min(1, (x - e0) / (e1 - e0)));
    return t * t * (3 - 2 * t);
  }
  function oklch(hex) {
    const n = parseInt(hex.trim().slice(1), 16);
    const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => lin(c / 255));
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
    const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
    const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
    return [L, Math.hypot(A, B), Math.atan2(B, A)];
  }
  function mixOklch(c0, c1, t) {
    let dh = c1[2] - c0[2];
    if (dh > Math.PI) dh -= 2 * Math.PI;
    if (dh < -Math.PI) dh += 2 * Math.PI;
    const L = c0[0] + (c1[0] - c0[0]) * t;
    const C = c0[1] + (c1[1] - c0[1]) * t;
    const h = c0[2] + dh * t;
    const A = C * Math.cos(h), B = C * Math.sin(h);
    const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
    const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
    const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
    const enc = (c) => {
      c = Math.max(0, Math.min(1, c));
      return Math.round(255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055));
    };
    const rgb = [
      4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
      -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
      -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
    ].map(enc);
    return `rgb(${rgb.join(",")})`;
  }

  function renderContext(d) {
    const badge = $("badge");
    let text = "";
    let cls = "";
    if (d.role === "driver" && (d.driving || d.in_vehicle)) text = "Driver";
    else if (d.role === "passenger" && d.in_vehicle) { text = "Passenger"; cls = "passenger"; }
    else if (d.driving) text = "In car";
    badge.textContent = text;
    badge.className = `badge ${cls}`;
    badge.classList.toggle("hidden", !text);

    // Seat check feedback: "Checking seat…" while frames arrive, then the result briefly.
    if (prevRole !== null && d.role !== prevRole && d.role !== "unknown") {
      seatResult = d.role === "driver"
        ? { text: "Driver seat ✓", cls: "", until: Date.now() + SEAT_SHOW_MS }
        : { text: "Passenger seat", cls: "passenger", until: Date.now() + SEAT_SHOW_MS };
    }
    prevRole = d.role;
    const seat = $("seat");
    if (seatResult && Date.now() < seatResult.until) {
      seat.textContent = seatResult.text;
      seat.className = `seat ${seatResult.cls}`;
    } else if (d.seat_checking) {
      seat.textContent = "Checking seat…";
      seat.className = "seat checking";
    } else {
      seat.className = "seat hidden";
    }
  }

  function renderBanner(a) {
    const el = $("banner");
    if (!a || a.level === "NONE") { el.classList.add("hidden"); return; }
    el.className = `banner ${a.level}${a.acked ? " acked" : ""}`;
    $("banner-title").textContent = a.acked ? `${a.title} ✓` : a.title;
    $("banner-line").textContent = a.level === "RECOVERING" ? recoverLine(a) : a.line;
  }

  // RECOVERING: "Recheck in mm:ss" on the demo clock, then the engine's "Recheck now".
  function recoverLine(a) {
    if (!a.until) return a.line;
    const left = Math.round((new Date(a.until) - new Date(state.now)) / 1000);
    if (left <= 0) return a.line;
    const mm = String(Math.floor(left / 60)).padStart(2, "0");
    const ss = String(left % 60).padStart(2, "0");
    return `Recheck in ${mm}:${ss}`;
  }

  function renderForecast() {
    const fc = state.forecast;
    const rows = $("fc-rows");
    if (!fc) { rows.innerHTML = `<span class="h">No forecast</span><span></span>`; return; }
    rows.innerHTML = fc.horizons_min.map((h, i) =>
      `<span class="h">+${h} min</span><span>${fmt(fc.mean[i], state.units)}
        <span class="h">(${fmt(fc.lo[i], state.units)}–${fmt(fc.hi[i], state.units)})</span></span>`
    ).join("");
  }

  function drawSpark() {
    const svg = $("spark");
    const hist = state.history || [];
    if (hist.length < 2) { svg.innerHTML = ""; return; }
    const now = new Date(state.now).getTime();
    const fc = state.forecast;
    const t0 = now - 3 * 3600e3;
    const t1 = now + 30 * 60e3;
    const vals = hist.map((p) => p.mgdl).concat(fc ? fc.lo.concat(fc.hi) : []);
    const lo = Math.min(55, ...vals), hi = Math.max(200, ...vals);
    const X = (t) => ((t - t0) / (t1 - t0)) * 300;
    const Y = (v) => 110 - ((v - lo) / (hi - lo)) * 110;
    const pts = hist.map((p) => `${X(new Date(p.t).getTime()).toFixed(1)},${Y(p.mgdl).toFixed(1)}`);
    let out = `<line class="low" x1="0" x2="300" y1="${Y(70)}" y2="${Y(70)}"/>`;
    out += `<polyline class="line" points="${pts.join(" ")}"/>`;
    if (fc) {
      const base = new Date(fc.t0).getTime();
      const last = hist[hist.length - 1];
      const fx = fc.horizons_min.map((h) => X(base + h * 60e3));
      const up = fx.map((x, i) => `${x},${Y(fc.hi[i])}`);
      const dn = fx.map((x, i) => `${x},${Y(fc.lo[i])}`).reverse();
      const start = `${X(base)},${Y(last.mgdl)}`;
      out += `<polygon class="band" points="${[start, ...up, ...dn].join(" ")}"/>`;
      out += `<polyline class="fc" points="${[start, ...fx.map((x, i) => `${x},${Y(fc.mean[i])}`)].join(" ")}"/>`;
    }
    svg.innerHTML = out;
  }

  // ---- alerts and audio ----
  // The phone speaks every alert (its audio plays through the glasses speakers). The HUD
  // only speaks if no phone reported speaking this alert id within PHONE_GRACE_MS.
  function onAlert(a) {
    if (!a || a.level === "NONE" || !a.id || a.id === lastAlertId) return;
    lastAlertId = a.id;
    if (view !== 0) setView(0); // a new alert is always visible
    clearTimeout(speakTimer);
    if (!a.speak || a.spoken) return; // silent (already said this episode) or the phone said it
    speakTimer = setTimeout(() => {
      const cur = state && state.alert;
      if (cur && cur.id === a.id && !cur.spoken) speakHere(cur);
    }, PHONE_GRACE_MS);
  }

  function speakHere(a) {
    // speechSynthesis is supported on Meta Ray-Ban Display web apps (one en-US voice).
    if ("speechSynthesis" in window && "SpeechSynthesisUtterance" in window) {
      speechSynthesis.cancel(); // a newer alert replaces anything still being said
      const u = new SpeechSynthesisUtterance(a.speak);
      u.lang = "en-US";
      speechSynthesis.speak(u);
      return;
    }
    // Fallback: pre-generated clips in audio/ (none are shipped by default).
    const audio = $("audio");
    audio.src = `audio/${a.level.toLowerCase()}.mp3`;
    audio.play().catch(() => {});
  }

  // Returns true if an acknowledgement was sent (the backend confirms it in the next state).
  function acknowledge() {
    const a = state && state.alert;
    if (!a || a.level === "NONE" || a.acked) return false;
    let sent = false;
    if (DEV) { window.parent.postMessage({ type: "lowsight-dev-ack" }, location.origin); sent = true; }
    else if (ws && ws.readyState === 1) { ws.send(JSON.stringify({ type: "ack", id: a.id })); sent = true; }
    setView(0);
    return sent;
  }

  // ---- input (D-pad: arrows + Enter) ----
  function setView(i) {
    view = (i + VIEWS.length) % VIEWS.length;
    document.querySelectorAll(".view").forEach((el) =>
      el.classList.toggle("hidden", el.dataset.view !== VIEWS[view]));
    document.querySelectorAll(".dots i").forEach((d, j) => d.classList.toggle("on", j === view));
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") { setView(view + 1); e.preventDefault(); }
    else if (e.key === "ArrowLeft") { setView(view - 1); e.preventDefault(); }
    else if (e.key === "Enter") { acknowledge(); e.preventDefault(); }
  });

  // ---- voice: Meta AI tools over WebMCP (webmcp.js). Optional; the D-pad never depends on it. ----
  let devTools = null; // dev page only: a local registry standing in for Meta AI
  try {
    const tools = window.LowSightWebMCP;
    const api = {
      getState: () => state,
      onState: (fn) => { stateListeners.add(fn); return () => stateListeners.delete(fn); },
      connected: () => DEV || !!(ws && ws.readyState === 1),
      acknowledge,
      showView: (name) => setView(VIEWS.indexOf(name)),
      fmt, unitLabel, trendWords: TREND_WORDS,
    };
    if (tools && document.modelContext) tools.register(document.modelContext, api);
    else if (tools && DEV) { devTools = tools.createLocalContext(); tools.register(devTools, api); }
  } catch (err) {
    console.error("LowSight voice tools unavailable", err);
  }

  setView(0);
  $("hud").focus();
  if (DEV) {
    window.addEventListener("message", (e) => {
      if (e.origin !== location.origin || !e.data) return;
      if (e.data.type === "lowsight-dev-state") {
        state = e.data.state;
        setStatus(null);
        render();
      } else if (e.data.type === "lowsight-dev-tool" && devTools) {
        const { name, args, reqId } = e.data;
        const reply = (result, error) => window.parent.postMessage(
          { type: "lowsight-dev-tool-result", reqId, name, result, error }, location.origin);
        devTools.call(name, args).then((r) => reply(r), (err) => reply(undefined, String(err)));
      }
    });
    window.parent.postMessage({ type: "lowsight-dev-ready" }, location.origin);
  } else {
    connect();
  }
})();
