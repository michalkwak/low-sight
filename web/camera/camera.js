// LowSight camera page: streams JPEG frames to /ws/frames for one seat check, like a
// glasses camera session. Stops when the backend decides the seat, or after 3 minutes.
(() => {
  const $ = (id) => document.getElementById(id);
  const FRAME_MS = 500; // 2 fps
  const WIDTH = 384;
  const QUALITY = 0.7;
  const SESSION_MS = 180000; // the platform's glasses-session limit
  const video = $("video");
  const canvas = document.createElement("canvas");
  let stream = null;
  let ws = null;
  let timer = null;
  let startedAt = 0;
  let waiting = false; // a frame is out for scoring: skip ticks instead of piling up frames
  let simulate = null; // a fixed p_driver for the "simulate" buttons, else null

  const setStatus = (t) => { $("status").textContent = t; };
  const url = (path) => `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}${path}`;

  // ---- sources ----
  function stopCamera() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  $("cam").onclick = async () => {
    stopCamera();
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 640 } },
        audio: false,
      });
      video.removeAttribute("src");
      video.srcObject = stream;
      await video.play();
      setStatus("Camera on. Point it where your eyes look, then start the seat check.");
    } catch (e) {
      setStatus(`Camera unavailable: ${e.message}. It needs HTTPS (the tunnel) or localhost.`);
    }
  };
  $("file").onchange = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    stopCamera();
    video.srcObject = null;
    video.src = URL.createObjectURL(f);
    video.loop = true;
    video.play();
    setStatus(`Playing ${f.name}.`);
  };

  // ---- session ----
  $("start").onclick = () => start(null);
  $("sim-driver").onclick = () => start(0.95);
  $("sim-passenger").onclick = () => start(0.05);
  $("stop").onclick = () => finish("Stopped.");

  function start(simP) {
    finish(null);
    if (simP === null && !video.videoWidth) { setStatus("Start the camera or pick a video first."); return; }
    simulate = simP;
    $("result").textContent = "Checking…";
    $("result").className = "";
    const sock = new WebSocket(url("/ws/frames"));
    ws = sock;
    sock.onopen = () => {
      startedAt = performance.now();
      waiting = false;
      timer = setInterval(tick, FRAME_MS);
      tick();
    };
    sock.onmessage = (e) => onReply(JSON.parse(e.data));
    sock.onclose = () => { if (ws === sock) finish("Connection closed."); };
  }

  function tick() {
    if (!ws || ws.readyState !== 1) return;
    const elapsed = performance.now() - startedAt;
    const left = Math.max(0, Math.ceil((SESSION_MS - elapsed) / 1000));
    $("timer").textContent = `· ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} left`;
    if (elapsed >= SESSION_MS) { finish("Session over (3 min) without a decision: the role stays unknown."); return; }
    if (simulate !== null) { ws.send(JSON.stringify({ p_driver: simulate })); return; }
    if (waiting || !video.videoWidth) return;
    canvas.width = WIDTH;
    canvas.height = Math.round((video.videoHeight * WIDTH) / video.videoWidth);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    waiting = true;
    const sock = ws;
    canvas.toBlob((blob) => {
      if (!blob || sock !== ws || sock.readyState !== 1) { waiting = false; return; }
      blob.arrayBuffer().then((buf) => sock.send(buf));
    }, "image/jpeg", QUALITY);
  }

  function onReply(r) {
    waiting = false;
    $("pema").textContent = r.p_driver == null ? "--" : r.p_driver.toFixed(2);
    $("pframe").textContent = r.p_frame == null ? "--" : r.p_frame.toFixed(2);
    $("pbar").style.width = `${Math.round((r.p_driver ?? 0.5) * 100)}%`;
    $("dropped").textContent = r.dropped ?? 0;
    if (r.error) {
      setStatus(r.error);
      if (/not installed|failed to load/.test(r.error)) {
        finish(`${r.error}. Use "Test without the vision model" below, or the control panel's seat override.`);
      }
    }
    if (r.seat) {
      $("result").textContent = r.seat === "driver" ? "Driver seat ✓" : "Passenger seat";
      $("result").className = r.seat;
      finish(`Decided in ${r.elapsed_s} s. The HUD shows the result.`);
    } else if (r.done) {
      finish(r.reason || "Session over.");
    }
  }

  function finish(msg) {
    clearInterval(timer);
    timer = null;
    waiting = false;
    if (ws) {
      const sock = ws;
      ws = null;
      try { sock.close(); } catch (_) { /* already closed */ }
    }
    $("timer").textContent = "";
    if ($("result").textContent === "Checking…") $("result").textContent = "Not decided";
    if (msg) setStatus(msg);
  }
})();
