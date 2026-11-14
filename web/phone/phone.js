// LowSight phone companion: trip detection signals → /api/phone, alerts → speech + notification.
(() => {
  const $ = (id) => document.getElementById(id);
  const log = (m) => { $("log").textContent = `${new Date().toLocaleTimeString()}  ${m}\n` + $("log").textContent; };

  let carConnected = false;
  let gpsKmh = null;
  let simKmh = null; // null → use GPS
  let started = false;
  let lastAlertId = null;
  let swReg = null;
  let ws = null;
  let speakingLevel = null;

  // ---- which demo: ?s=CODE from the simulator's link, or a code typed here ----
  const CODE_RE = /^[A-HJ-NP-Z2-9]{4}$/; // the simulator's codes: no O/0, I/1
  const clean = (c) => { c = String(c || "").trim().toUpperCase(); return CODE_RE.test(c) ? c : ""; };
  // Only the link (?s=) or a code typed here: never a remembered one, so a phone that once joined
  // a visitor's demo can't silently stay off the shared demo the real glasses use.
  let demo = clean(new URLSearchParams(location.search).get("s"));
  const q = () => (demo ? `?s=${demo}` : "");
  function showDemo() {
    $("code").value = demo;
    $("code-note").textContent = demo
      ? `Joined demo ${demo}: you'll hear its alerts. Clear the box and tap Join for the shared demo.`
      : "Type the 4-character code shown in the simulator to hear your own demo.";
    $("code-note").classList.toggle("ok", !!demo);
  }
  $("join-form").onsubmit = (e) => {
    e.preventDefault();
    const typed = $("code").value;
    const next = clean(typed);
    if (typed.trim() && !next) { $("code-note").textContent = "That isn't a demo code: 4 letters or numbers, as shown in the simulator."; return; }
    demo = next;
    history.replaceState(null, "", demo ? `?s=${demo}` : location.pathname);
    lastAlertId = null;
    showDemo();
    log(demo ? `joined demo ${demo}` : "joined the shared demo");
    if (ws) ws.close(); // reconnects to the new demo
  };

  // ---- signals ----
  $("car").onclick = () => {
    carConnected = !carConnected;
    $("car").classList.toggle("on", carConnected);
    $("car").setAttribute("aria-pressed", String(carConnected));
    send();
  };
  $("sim").oninput = (e) => {
    const v = Number(e.target.value);
    simKmh = v < 0 ? null : v;
    $("simv").textContent = simKmh === null ? "GPS" : `${simKmh} km/h`;
  };

  // The wearer says which seat they're in: same effect as a camera seat check, for this trip.
  function confirmSeat(role) {
    if (ws && ws.readyState === 1) { ws.send(JSON.stringify({ type: "seat", role })); log(`seat → ${role}`); }
    else log("not connected: seat not sent");
  }
  $("seat-driver").onclick = () => confirmSeat("driver");
  $("seat-passenger").onclick = () => confirmSeat("passenger");

  function send() {
    const speed = simKmh !== null ? simKmh : gpsKmh;
    fetch(`/api/phone${q()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ speed_kmh: speed, car_connected: carConnected }),
    }).catch(() => {});
  }

  // ---- start (needs a user gesture for speech, notifications, wake lock) ----
  $("start").onclick = async () => {
    if (started) return;
    started = true;
    $("start").textContent = "Running: keep this page open";
    $("start").classList.add("running");
    // Prime speech so later alerts can play without a tap.
    if ("speechSynthesis" in window) speechSynthesis.speak(new SpeechSynthesisUtterance("LowSight is on."));
    try {
      if ("serviceWorker" in navigator) swReg = await navigator.serviceWorker.register("sw.js");
      if ("Notification" in window && Notification.permission === "default") await Notification.requestPermission();
    } catch (e) { log(`notifications unavailable: ${e.message}`); }
    try { if ("wakeLock" in navigator) await navigator.wakeLock.request("screen"); } catch (e) { log("wake lock unavailable"); }
    if ("geolocation" in navigator) {
      navigator.geolocation.watchPosition(
        (pos) => { gpsKmh = pos.coords.speed == null ? null : pos.coords.speed * 3.6; },
        (err) => log(`GPS: ${err.message}`),
        { enableHighAccuracy: true, maximumAge: 1000 },
      );
    }
    setInterval(send, 1000);
    send();
    log("started");
  };

  // ---- alerts ----
  // Speech plays through the glasses speakers. A different level replaces what is being
  // said; a repeat of the same level queues behind it instead of cutting it off.
  function speak(a) {
    if (!a.speak || !("speechSynthesis" in window)) return;
    if (speakingLevel !== a.level) speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(a.speak);
    u.onstart = () => {
      speakingLevel = a.level;
      // Tell the backend, so the HUD (if open) doesn't say it a second time.
      if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "spoken", id: a.id }));
    };
    u.onend = () => { if (!speechSynthesis.speaking) speakingLevel = null; };
    speechSynthesis.speak(u);
  }
  function notify(a, valueText) {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const opts = { body: `${a.line} · ${valueText}`, tag: "lowsight", renotify: true, requireInteraction: a.level === "PULL_OVER" };
    if (swReg) swReg.showNotification(`LowSight: ${a.title}`, opts);
    else new Notification(`LowSight: ${a.title}`, opts);
  }

  const TREND = { "⇈": "rising fast", "↑": "rising", "↗": "rising slowly", "→": "steady", "↘": "falling slowly", "↓": "falling", "⇊": "falling fast" };
  function setConn(live) {
    $("conn").classList.toggle("live", live);
    $("conn").lastElementChild.textContent = live ? "live" : "reconnecting…";
  }

  function connect() {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/state${q()}`);
    ws.onmessage = (e) => {
      const s = JSON.parse(e.data);
      const f = (v) => (s.units === "mmol" ? (v / 18).toFixed(1) : Math.round(v));
      const valueText = s.reading ? `${f(s.reading.mgdl)} ${s.arrow}` : "--";
      const unit = s.units === "mmol" ? "mmol/L" : "mg/dL";
      const fresh = s.reading && s.forecast;
      $("r-value").innerHTML = s.reading ? `${f(s.reading.mgdl)}<span class="u">${unit}</span>` : "--";
      const mg = s.reading ? s.reading.mgdl : 0;
      $("r-value").className = !fresh ? "stale" : mg < 70 ? "bad" : mg < 90 || mg > 180 ? "warn" : "ok";
      $("r-trend").textContent = fresh ? `${s.arrow} ${TREND[s.arrow] || ""}` : s.reading ? "old reading" : "no data";
      $("r-trend").className = `trend ${!fresh ? "" : s.trend_mgdl_min <= -1 ? "down" : s.trend_mgdl_min >= 1 ? "up" : "flat"}`;
      $("r-speed").textContent = s.driving.speed_kmh == null ? "--" : `${Math.round(s.driving.speed_kmh)} km/h`;
      $("r-car").textContent = s.driving.in_vehicle ? (s.driving.driving ? "driving" : "yes") : "no";
      const src = { camera: "camera", wearer: "you", forced: "override" }[s.driving.role_source];
      const role = { driver: "Driver", passenger: "Passenger", unknown: "Not set" }[s.driving.role] || s.driving.role;
      $("r-role").textContent = src ? `${role} (${src})` : role;
      $("seat-driver").classList.toggle("on", s.driving.role === "driver");
      $("seat-passenger").classList.toggle("on", s.driving.role === "passenger");

      const a = s.alert;
      const box = $("alert");
      if (a.level === "NONE") { box.classList.add("hidden"); }
      else {
        box.className = `${a.level}${a.acked ? " acked" : ""}`;
        $("alert-title").textContent = a.acked ? `${a.title} ✓` : a.title;
        $("alert-line").textContent = a.line;
        $("alert-icon").textContent = { PULL_OVER: "⚠", RECOVERING: "↻" }[a.level] || "!";
      }
      if (a.level !== "NONE" && a.id && a.id !== lastAlertId) {
        lastAlertId = a.id;
        // speak === null: already said this episode (dedupe) → update the page silently.
        log(`alert ${a.level}${a.speak ? "" : " (silent)"}`);
        if (started && a.speak) { speak(a); notify(a, valueText); }
      }
    };
    ws.onopen = () => setConn(true);
    ws.onclose = (e) => {
      setConn(false);
      if (e.code === 1013 && demo) {
        $("code-note").textContent = `Demo ${demo} isn't available right now (the server is busy, or the demo expired). Open the simulator again for a new code, or clear the box for the shared demo.`;
        $("code-note").classList.remove("ok");
        setTimeout(connect, 5000);
        return;
      }
      setTimeout(connect, 1000);
    };
  }
  showDemo();
  connect();
})();
