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

  let lastLevel = null;
  function connect() {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/state`);
    ws.onmessage = (e) => {
      const s = JSON.parse(e.data);
      const f = (v) => (s.units === "mmol" ? (v / 18).toFixed(1) : Math.round(v));
      $("r-value").textContent = s.reading ? f(s.reading.mgdl) : "--";
      $("r-trend").textContent = `${s.arrow} ${s.trend_mgdl_min}`;
      $("r-fc").textContent = s.forecast ? f(s.forecast.mean[2]) : "--";
      const d = s.driving;
      $("r-phone").textContent = d.phone_stale ? "offline" : `${d.speed_kmh == null ? "--" : Math.round(d.speed_kmh)} km/h${d.car_connected ? " · car" : ""}`;
      $("r-car").textContent = d.in_vehicle ? "yes" : "no";
      $("r-p").textContent = `${d.role} · ${d.p_driver.toFixed(2)}`;
      $("r-drv").textContent = `${d.driving ? "YES" : "no"} (${d.source})`;
      $("r-alert").textContent = s.alert.level;
      $("r-time").textContent = new Date(s.now).toISOString().slice(11, 16);
      mark("speed", s.speed); mark("units", s.units);
      if (s.alert.level !== lastLevel) { log(`alert → ${s.alert.level}`); lastLevel = s.alert.level; }
    };
    ws.onclose = () => setTimeout(connect, 1000);
  }
  connect();
})();
