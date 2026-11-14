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

  // ---- signals ----
  $("car").onclick = () => {
    carConnected = !carConnected;
    $("car").textContent = `Connected to car: ${carConnected ? "on" : "off"}`;
    $("car").classList.toggle("on", carConnected);
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
    fetch("/api/phone", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ speed_kmh: speed, car_connected: carConnected }),
    }).catch(() => {});
  }

  // ---- start (needs a user gesture for speech, notifications, wake lock) ----
  $("start").onclick = async () => {
    if (started) return;
    started = true;
    $("start").textContent = "Running";
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

  function connect() {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/state`);
    ws.onmessage = (e) => {
      const s = JSON.parse(e.data);
      const f = (v) => (s.units === "mmol" ? (v / 18).toFixed(1) : Math.round(v));
      const valueText = s.reading ? `${f(s.reading.mgdl)} ${s.arrow}` : "--";
      $("r-value").textContent = valueText;
      $("r-speed").textContent = s.driving.speed_kmh == null ? "--" : `${Math.round(s.driving.speed_kmh)} km/h`;
      $("r-car").textContent = s.driving.in_vehicle ? "yes" : "no";
      const src = { camera: "camera", wearer: "you", forced: "override" }[s.driving.role_source];
      $("r-role").textContent = src ? `${s.driving.role} (${src})` : s.driving.role;
      $("seat-driver").classList.toggle("on", s.driving.role === "driver");
      $("seat-passenger").classList.toggle("on", s.driving.role === "passenger");

      const a = s.alert;
      const box = $("alert");
      if (a.level === "NONE") { box.classList.add("hidden"); }
      else {
        box.className = a.level;
        box.textContent = `${a.title} — ${a.line}`;
      }
      if (a.level !== "NONE" && a.id && a.id !== lastAlertId) {
        lastAlertId = a.id;
        // speak === null: already said this episode (dedupe) → update the page silently.
        log(`alert ${a.level}${a.speak ? "" : " (silent)"}`);
        if (started && a.speak) { speak(a); notify(a, valueText); }
      }
    };
    ws.onclose = () => setTimeout(connect, 1000);
  }
  connect();
})();
