// LowSight HUD — 600×600 glasses app. Input: ←/→ cycle views, Enter = ack.
(() => {
  const $ = (id) => document.getElementById(id);
  const VIEWS = ["glucose", "forecast", "about"];
  let view = 0;
  let state = null;
  let ws = null;
  let backoff = 500;
  let lastAlertId = null;

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
    ws.onopen = () => { backoff = 500; setStatus(null); };
    ws.onmessage = (e) => { state = JSON.parse(e.data); render(); };
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

    if (r) {
      const ageMin = Math.round((now - new Date(r.t)) / 60000);
      const stale = ageMin >= 15 || !state.forecast;
      $("value").textContent = fmt(r.mgdl, u);
      $("arrow").textContent = stale ? "" : state.arrow;
      $("age").textContent = stale ? `${ageMin} min ago` : "";
      document.querySelector(".readout").classList.toggle("stale", stale);
    } else {
      $("value").textContent = "--";
      $("arrow").textContent = "";
      $("age").textContent = "No CGM data";
    }
    $("unit").textContent = unitLabel(u);

    const d = state.driving || {};
    const driving = !!d.driving;
    $("driving").classList.toggle("hidden", !driving);
    $("driving").textContent = d.role === "driver" ? "● Driver" : "● In car";
    // No sparkline while driving — minimal visual load.
    $("spark").classList.toggle("hidden", !!driving);
    if (!driving) drawSpark();

    renderBanner();
    renderForecast();
  }

  function renderBanner() {
    const a = state.alert;
    const el = $("banner");
    if (!a || a.level === "NONE") { el.classList.add("hidden"); return; }
    el.className = `banner ${a.level}${a.acked ? " acked" : ""}`;
    $("banner-title").textContent = a.title;
    $("banner-line").textContent = a.line;
    if (a.id && a.id !== lastAlertId) { lastAlertId = a.id; playAlert(a); }
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

  // ---- audio ----
  function playAlert(a) {
    const audio = $("audio");
    audio.src = `audio/${a.level.toLowerCase()}.mp3`;
    audio.play().catch(() => {
      if (a.speak && "speechSynthesis" in window) {
        speechSynthesis.cancel();
        speechSynthesis.speak(new SpeechSynthesisUtterance(a.speak));
      }
    });
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
    else if (e.key === "Enter") {
      if (ws && ws.readyState === 1 && state && state.alert && state.alert.level !== "NONE") {
        ws.send(JSON.stringify({ type: "ack", id: state.alert.id }));
      }
      e.preventDefault();
    }
  });

  setView(0);
  $("hud").focus();
  connect();
})();
