// LowSight simulator (control page): guided stories for newcomers, driver actions, plain-language
// live status, a live preview of the glasses view, and the operator's controls under "Advanced".
(() => {
  const $ = (id) => document.getElementById(id);
  const post = (body) =>
    fetch("/api/control", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const log = (msg) => { $("log").textContent = `${new Date().toLocaleTimeString()}  ${msg}\n` + $("log").textContent; };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let ws = null;
  const sendWs = (msg) => ws && ws.readyState === 1 && ws.send(JSON.stringify(msg));

  // ---- 1. Stories: one click sets everything up from a clean start ----
  const BASE = { reset: true, speed: 30, pause: false };
  const STORIES = {
    falling: {
      steps: [{ ...BASE, scenario: "falling_while_driving", force_driving: "on", force_role: "auto" }, { seek_to_crossing_min: 20 }],
      expect: "Within ~10 s: amber “LOW IN ~30 MIN – plan a stop”. About 20 s later: red “PULL OVER”, spoken, then repeated once. " +
        "Press <b>Acknowledge alert</b> to stop the repeat.",
    },
    predrive: {
      steps: [{ ...BASE, scenario: "low_before_drive", force_driving: "off", force_role: "auto" }],
      seat: "driver",
      expect: "Parked, blood sugar already low. The seat check confirms the driver's seat, so LowSight raises amber " +
        "“CHECK BEFORE DRIVING – treat before you set off”, before the car moves.",
    },
    recover: {
      steps: [{ ...BASE, scenario: "treated_recovery", force_driving: "on", force_role: "auto" }, { seek_min: 15 }],
      expect: "Red “PULL OVER” within ~10 s. Press <b>Acknowledge alert</b> (they've pulled over and taken sugar). " +
        "About 50 s later, as glucose rises, it turns cyan: “WAIT · RECHECK” with a 15-minute countdown.",
    },
    passenger: {
      steps: [{ ...BASE, scenario: "falling_while_driving", force_driving: "on", force_role: "passenger" }, { seek_to_crossing_min: 20 }],
      expect: "The same drop, but the wearer is a passenger: a gentle “LOW IN ~30 MIN – treat when you can”, then " +
        "“LOW GLUCOSE – treat when you can”. Never “PULL OVER”: no driving instructions for someone not driving.",
    },
    stable: {
      steps: [{ ...BASE, scenario: "stable_drive", force_driving: "on", force_role: "auto" }],
      expect: "Blood sugar stays in range during the drive: no warnings at all. LowSight doesn't cry wolf.",
    },
  };
  let busy = false;
  $("stories").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-story]");
    if (!btn || busy) return;
    const story = STORIES[btn.dataset.story];
    busy = true;
    primeSpeech();
    document.querySelectorAll(".story").forEach((b) => b.classList.toggle("on", b === btn));
    $("expect").innerHTML = `<b>What to expect:</b> ${story.expect}`;
    log(`story → ${btn.querySelector("b").textContent}`);
    try {
      for (const step of story.steps) {
        const body = Object.fromEntries(Object.entries(step).filter(([, v]) => v !== undefined));
        await post(body);
      }
      if (story.seat) { await sleep(800); sendWs({ type: "seat", role: story.seat }); }
    } finally {
      busy = false;
    }
  });

  // ---- 2. Driver actions ----
  $("ack").onclick = () => { primeSpeech(); post({ ack: true }); log("acknowledged"); };
  $("seat-driver").onclick = () => { sendWs({ type: "seat", role: "driver" }); log("wearer: I'm the driver"); };
  $("seat-passenger").onclick = () => { sendWs({ type: "seat", role: "passenger" }); log("wearer: I'm a passenger"); };

  // Sound: speak each new alert on this computer (the glasses preview is muted, so nothing doubles).
  // Browsers only allow speech after a click, so the first click anywhere on the page primes it.
  let sound = true;
  let primed = false;
  function primeSpeech() {
    if (primed || !("speechSynthesis" in window)) return;
    primed = true;
    speechSynthesis.speak(new SpeechSynthesisUtterance(""));
  }
  document.addEventListener("click", primeSpeech, { once: true });
  $("sound").onclick = () => {
    sound = !sound;
    $("sound").classList.toggle("on", sound);
    $("sound").firstChild.textContent = sound ? "🔊 Sound on" : "🔇 Sound off";
    if (!sound && "speechSynthesis" in window) speechSynthesis.cancel();
  };

  // ---- Advanced (operator) controls ----
  fetch("/api/scenarios").then((r) => r.json()).then(({ scenarios, current }) => {
    $("scenario").innerHTML = scenarios.map((s) => `<option ${s === current ? "selected" : ""}>${s}</option>`).join("");
  });
  $("scenario").onchange = (e) => { post({ scenario: e.target.value }); log(`scenario → ${e.target.value}`); };
  $("reset").onclick = () => { post({ reset: true }); log("reset"); };
  $("pause").onclick = () => post({ pause: true });
  $("play").onclick = () => post({ pause: false });
  $("jump").onclick = () => { post({ seek_to_crossing_min: 5 }); log("jump to −5 min before the low"); };
  $("jump20").onclick = () => { post({ seek_to_crossing_min: 20 }); log("jump to −20 min before the low"); };
  const groups = { speed: (v) => ({ speed: Number(v) }), force: (v) => ({ force_driving: v }), role: (v) => ({ force_role: v }), units: (v) => ({ units: v }) };
  document.querySelectorAll("[data-group]").forEach((g) => {
    g.addEventListener("click", (e) => {
      const v = e.target.dataset.v;
      if (!v) return;
      post(groups[g.dataset.group](v));
      log(`${g.dataset.group} → ${v}`);
    });
  });
  const mark = (group, val) =>
    document.querySelectorAll(`[data-group=${group}] button`).forEach((b) => b.classList.toggle("on", b.dataset.v === String(val)));

  // ---- 3. Live status in plain language ----
  const TREND = { "⇈": "rising fast", "↑": "rising", "↗": "rising slowly", "→": "steady", "↘": "falling slowly", "↓": "falling", "⇊": "falling fast" };
  const MEANING = {
    NONE: ["No warning", "Blood sugar is fine for driving right now."],
    LOW_SOON: [null, "The forecast says blood sugar will go low soon, so the driver is told early, while there's time to plan a stop."],
    PULL_OVER: [null, "Blood sugar is low or about to be. The driver is told to stop safely and take fast-acting sugar."],
    PRE_DRIVE: [null, "The driver is about to set off while low or dropping, and is told to treat it first."],
    RECOVERING: [null, "After treatment: blood sugar is rising, but they should wait and recheck before driving on."],
  };
  let lastId = null;
  let lastLevel = null;
  let speaking = null;

  // Colour by range, in mg/dL: below 70 is low (red), 70–90 is below the "five to drive" line
  // (amber), 90–180 is in range (green), above 180 is high (amber).
  const rangeClass = (mgdl) => (mgdl < 70 ? "bad" : mgdl < 90 || mgdl > 180 ? "warn" : "ok");

  // Blood sugar chart: last 3 h (solid), the 30-min forecast (dashed, with its band), the target
  // range (70–180) and the low line (70). Fixed scale so stories are comparable.
  function drawChart(s, mm) {
    const svg = $("chart");
    const W = 600, H = 170, PADL = 40, PADR = 8, PADT = 8, PADB = 18;
    const now = Date.parse(s.now), t0 = now - 3 * 3600e3, t1 = now + 35 * 60e3;
    const lo = 40, hi = 250;
    const X = (t) => PADL + ((t - t0) / (t1 - t0)) * (W - PADL - PADR);
    const Y = (v) => PADT + (1 - (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo)) * (H - PADT - PADB);
    let out = `<rect x="${PADL}" y="${Y(180)}" width="${W - PADL - PADR}" height="${Y(70) - Y(180)}" fill="rgba(126,217,87,0.08)"/>`;
    for (const v of [70, 180]) {
      out += `<line x1="${PADL}" x2="${W - PADR}" y1="${Y(v)}" y2="${Y(v)}" stroke="${v === 70 ? "#ff5a36" : "rgba(126,217,87,0.35)"}" stroke-width="1.5" stroke-dasharray="${v === 70 ? "5 5" : "2 6"}" vector-effect="non-scaling-stroke"/>`;
      out += `<text x="${PADL - 6}" y="${Y(v) + 4}" fill="#6b7686" font-size="11" text-anchor="end">${mm(v)}</text>`;
    }
    for (const h of [-3, -2, -1, 0]) {
      const x = X(now + h * 3600e3);
      out += `<text x="${x}" y="${H - 4}" fill="#6b7686" font-size="11" text-anchor="middle">${h === 0 ? "now" : `${h} h`}</text>`;
    }
    out += `<line x1="${X(now)}" x2="${X(now)}" y1="${PADT}" y2="${H - PADB}" stroke="rgba(255,255,255,0.18)" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
    const hist = (s.history || []).filter((p) => Date.parse(p.t) >= t0);
    if (hist.length > 1) {
      const pts = hist.map((p) => `${X(Date.parse(p.t)).toFixed(1)},${Y(p.mgdl).toFixed(1)}`).join(" ");
      out += `<polyline points="${PADL},${H - PADB} ${pts} ${X(Date.parse(hist[hist.length - 1].t)).toFixed(1)},${H - PADB}" fill="url(#area)" stroke="none"/>`;
      out += `<polyline points="${pts}" fill="none" stroke="#3ee6c1" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`;
      const last = hist[hist.length - 1];
      const fc = s.forecast;
      if (fc) {
        const base = Date.parse(fc.t0), x0 = X(base), y0 = Y(last.mgdl);
        const fx = fc.horizons_min.map((m) => X(base + m * 60e3));
        const band = [`${x0},${y0}`, ...fx.map((x, i) => `${x},${Y(fc.hi[i])}`), ...fx.map((x, i) => `${x},${Y(fc.lo[i])}`).reverse()].join(" ");
        out += `<polygon points="${band}" fill="rgba(255,255,255,0.08)"/>`;
        out += `<polyline points="${[`${x0},${y0}`, ...fx.map((x, i) => `${x},${Y(fc.mean[i])}`)].join(" ")}" fill="none" stroke="#fff" stroke-width="2" stroke-dasharray="5 5" vector-effect="non-scaling-stroke"/>`;
      }
      const col = { ok: "#7ed957", warn: "#ffb020", bad: "#ff5a36" }[rangeClass(last.mgdl)];
      out += `<circle cx="${X(Date.parse(last.t))}" cy="${Y(last.mgdl)}" r="5" fill="${col}" stroke="#0b0e14" stroke-width="2"/>`;
    }
    svg.innerHTML = `<defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3ee6c1" stop-opacity="0.25"/><stop offset="1" stop-color="#3ee6c1" stop-opacity="0"/></linearGradient></defs>${out}`;
  }

  function render(s) {
    const mm = (v) => (s.units === "mmol" ? (v / 18).toFixed(1) : String(Math.round(v)));
    const unit = s.units === "mmol" ? "mmol/L" : "mg/dL";
    const fresh = s.reading && s.forecast;
    $("r-value").innerHTML = s.reading ? `${mm(s.reading.mgdl)}<span class="u">${unit}</span>` : "--";
    $("r-value").className = `v big ${fresh ? rangeClass(s.reading.mgdl) : "stale"}`;
    $("r-trend").textContent = fresh ? `${s.arrow} ${TREND[s.arrow] || ""}` : s.reading ? "old reading (no current trend)" : "no data";
    $("r-trend").className = `trend ${!fresh ? "" : s.trend_mgdl_min <= -1 ? "down" : s.trend_mgdl_min >= 1 ? "up" : "flat"}`;
    $("r-fc").innerHTML = s.forecast ? `${mm(s.forecast.mean[2])}<span class="u">${unit}</span>` : "--";
    $("r-fc").className = `v ${s.forecast ? rangeClass(s.forecast.mean[2]) : "stale"}`;
    drawChart(s, mm);
    $("r-fcs").textContent = s.forecast ? `range ${mm(s.forecast.lo[2])}–${mm(s.forecast.hi[2])}` : " ";

    const d = s.driving;
    $("r-sit").textContent = d.driving ? "Driving" : d.in_vehicle ? "In the car" : "Not in a car";
    const who = { driver: "Driver", passenger: "Passenger", unknown: "Seat not confirmed" }[d.role];
    const how = { camera: " (camera seat check)", wearer: " (they said so)", forced: " (override)" }[d.role_source] || "";
    $("r-seat").textContent = `${who}${how}${d.seat_checking ? " · checking seat…" : ""}`;
    $("r-time").textContent = new Date(s.now).toISOString().slice(11, 16);
    $("r-speed").textContent = s.paused ? "paused" : `${s.speed}× real time`;
    $("seat-driver").classList.toggle("on", d.role === "driver");
    $("seat-passenger").classList.toggle("on", d.role === "passenger");

    const a = s.alert;
    const box = $("alert");
    box.className = `alert ${a.level}${a.level === "PULL_OVER" && !a.acked ? " urgent" : ""}`;
    $("alert-icon").textContent = { NONE: "✓", LOW_SOON: "!", PRE_DRIVE: "!", PULL_OVER: "⚠", RECOVERING: "↻" }[a.level] || "!";
    const [title, meaning] = MEANING[a.level] || ["", ""];
    box.querySelector(".t").textContent = a.level === "NONE" ? title : `${a.title}${a.acked ? " ✓" : ""}`;
    box.querySelector(".l").textContent = a.level === "NONE" ? " " : a.line;
    box.querySelector(".m").textContent = a.level === "NONE" ? meaning
      : `${meaning}${a.acked ? " Acknowledged." : ""}${a.speak ? "" : " (Shown silently: it was already said.)"}`;
    $("ack").disabled = a.level === "NONE" || a.acked;
    $("ack").style.opacity = $("ack").disabled ? 0.5 : 1;

    mark("speed", s.speed); mark("units", s.units); mark("force", s.force_driving); mark("role", s.force_role);
    $("r-tech").textContent = `scenario ${s.scenario} · trend ${s.trend_mgdl_min} mg/dL/min · seat score ${d.p_driver.toFixed(2)} · ` +
      `phone ${d.phone_stale ? "offline" : `${d.speed_kmh == null ? "--" : Math.round(d.speed_kmh)} km/h`} · alert ${a.level}${a.spoken ? " (spoken)" : ""}`;

    if (a.level !== lastLevel) { log(`alert → ${a.level}${a.level !== "NONE" && !a.speak ? " (silent)" : ""}`); lastLevel = a.level; }
    if (a.level !== "NONE" && a.id && a.id !== lastId) {
      lastId = a.id;
      if (sound && primed && a.speak && "speechSynthesis" in window) {
        if (a.level !== speaking) speechSynthesis.cancel(); // a repeat queues, a new level replaces
        speaking = a.level;
        const u = new SpeechSynthesisUtterance(a.speak);
        u.onstart = () => sendWs({ type: "spoken", id: a.id });
        speechSynthesis.speak(u);
      }
    }
  }

  function connect() {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/state`);
    ws.onmessage = (e) => render(JSON.parse(e.data));
    ws.onclose = () => setTimeout(connect, 1000);
  }
  connect();

  // ---- Glasses preview: scale the 600×600 HUD to the frame ----
  const fit = () => { $("hud").style.transform = `scale(${$("frame").clientWidth / 600})`; };
  new ResizeObserver(fit).observe($("frame"));
  fit();
})();
