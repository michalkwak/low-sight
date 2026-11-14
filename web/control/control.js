(() => {
  const $ = (id) => document.getElementById(id);
  const post = (body) =>
    fetch("/api/control", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const log = (msg) => {
    const el = $("log");
    el.textContent = `${new Date().toLocaleTimeString()}  ${msg}\n` + el.textContent;
  };

  fetch("/api/scenarios").then((r) => r.json()).then(({ scenarios, current }) => {
    $("scenario").innerHTML = scenarios.map((s) => `<option ${s === current ? "selected" : ""}>${s}</option>`).join("");
  });
  $("scenario").onchange = (e) => { post({ scenario: e.target.value }); log(`scenario → ${e.target.value}`); };
  $("reset").onclick = () => { post({ reset: true }); log("reset"); };
  $("pause").onclick = () => post({ pause: true });
  $("play").onclick = () => post({ pause: false });
  $("jump").onclick = () => { post({ seek_to_crossing_min: 5 }); log("jump to −5 min before crossing"); };
  $("jump20").onclick = () => { post({ seek_to_crossing_min: 20 }); log("jump to −20 min before crossing"); };
  $("ack").onclick = () => { post({ ack: true }); log("ack"); };

  // Stage audio: speak alerts through this laptop's speakers so the audience hears them.
  let stage = false;
  $("stage").onclick = () => {
    stage = !stage;
    $("stage").textContent = `Stage audio: ${stage ? "on" : "off"}`;
    $("stage").classList.toggle("on", stage);
    if (stage && "speechSynthesis" in window) speechSynthesis.speak(new SpeechSynthesisUtterance("Stage audio on."));
    log(`stage audio ${stage ? "on" : "off"}`);
  };

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

  let ws = null;
  let lastLevel = null;
  let lastId = null;
  let stageLevel = null;
  function connect() {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/state`);
    ws.onmessage = (e) => {
      const s = JSON.parse(e.data);
      const f = (v) => (s.units === "mmol" ? (v / 18).toFixed(1) : Math.round(v));
      $("r-value").textContent = s.reading ? f(s.reading.mgdl) : "--";
      $("r-trend").textContent = `${s.arrow} ${s.trend_mgdl_min}`;
      $("r-fc").textContent = s.forecast ? f(s.forecast.mean[2]) : "--";
      const d = s.driving;
      $("r-phone").textContent = d.phone_stale ? "offline" : `${d.speed_kmh == null ? "--" : Math.round(d.speed_kmh)} km/h${d.car_connected ? " · car" : ""}`;
      $("r-car").textContent = d.in_vehicle ? "yes" : "no";
      $("r-p").textContent = `${d.role} · ${d.p_driver.toFixed(2)}${d.seat_checking ? " · checking" : ""}`;
      $("r-drv").textContent = `${d.driving ? "YES" : "no"} (${d.source})`;
      $("r-alert").textContent = s.alert.level;
      $("r-time").textContent = new Date(s.now).toISOString().slice(11, 16);
      mark("speed", s.speed); mark("units", s.units); mark("force", s.force_driving); mark("role", s.force_role);

      const a = s.alert;
      const b = $("banner");
      b.className = `banner ${a.level}`;
      b.innerHTML = a.level === "NONE" ? "No alert"
        : `${a.title} — ${a.line}<small>${a.acked ? "acknowledged" : "not acknowledged"} · ${a.spoken ? "spoken" : "not spoken yet"}${a.speak ? "" : " · silent (already said this episode)"}</small>`;
      if (a.level !== lastLevel) { log(`alert → ${a.level}${a.level !== "NONE" && !a.speak ? " (silent)" : ""}`); lastLevel = a.level; }
      if (a.level !== "NONE" && a.id && a.id !== lastId) {
        lastId = a.id;
        if (stage && a.speak && "speechSynthesis" in window) {
          if (a.level !== stageLevel) speechSynthesis.cancel(); // a repeat queues, a new level replaces
          stageLevel = a.level;
          const u = new SpeechSynthesisUtterance(a.speak);
          u.onstart = () => ws && ws.readyState === 1 && ws.send(JSON.stringify({ type: "spoken", id: a.id }));
          speechSynthesis.speak(u);
        }
      }
    };
    ws.onclose = () => setTimeout(connect, 1000);
  }
  connect();
})();
