// LowSight guided demo: plays one story by itself on the visitor's own private demo, using the
// same backend calls as the simulator. Each step: a caption for the viewer, a "behind the scenes"
// line with live numbers, and the real backend action that makes it happen.
(() => {
  const $ = (id) => document.getElementById(id);
  const TREND = { "⇈": "rising fast", "↑": "rising", "↗": "rising slowly", "→": "steady", "↘": "falling slowly", "↓": "falling", "⇊": "falling fast" };
  let demo = "";          // this viewer's private demo code
  let ws = null;
  let state = null;       // latest state pushed by the backend
  let run = 0;            // bumps on replay/skip: cancels the running script
  let paused = false;
  let lastSpokenId = null;
  let clockRunning = false; // the server's demo clock runs in steps 1-2, is frozen from step 3

  const q = () => (demo ? `?s=${demo}` : "");
  const post = (body) => fetch(`/api/control${q()}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const mm = (mgdl) => (mgdl / 18).toFixed(1);

  // ---- timing that respects Pause and stops on Replay/Skip ----
  class Stopped extends Error {}
  async function hold(ms, my) {
    let left = ms;
    while (left > 0) {
      if (my !== run) throw new Stopped();
      await new Promise((r) => setTimeout(r, 100));
      if (!paused) left -= 100;
    }
    if (my !== run) throw new Stopped();
  }
  async function until(test, my, maxMs = 40000) {
    let waited = 0;
    while (!(state && test(state))) {
      if (my !== run) throw new Stopped();
      if (waited > maxMs) return false;
      await new Promise((r) => setTimeout(r, 100));
      if (!paused) waited += 100;
    }
    return true;
  }

  // ---- the story panel ----
  function step(i, title, text, ms) {
    $("num").textContent = `Step ${i} of 5`;
    $("title").textContent = title;
    $("text").textContent = text;
    document.querySelectorAll("#steps i").forEach((el, j) => {
      el.className = j < i - 1 ? "done" : j === i - 1 ? "now" : "";
    });
    const now = document.querySelector("#steps i.now");
    if (now) { now.style.setProperty("--dur", `${ms / 1000}s`); now.replaceWith(now.cloneNode()); } // restart the bar
  }
  const behind = (html) => { $("behind").classList.remove("hidden"); $("behind").innerHTML = `<b>Behind the scenes:</b> ${html}`; };

  // ---- the script ----
  async function play() {
    const my = ++run;
    paused = false;
    $("end").classList.remove("on");
    $("story").classList.remove("hidden");
    ["pause", "skip", "replay"].forEach((id) => { $(id).disabled = false; });
    $("pause").textContent = "❚❚ Pause";
    $("steps").classList.remove("paused");
    try {
      // 1. Driving, glucose drifting down. Backend: fresh "falling while driving" story, phone says
      //    "in a moving car", clock at 30×, jumped to 20 min before the low.
      await post({ reset: true, scenario: "falling_while_driving", force_driving: "on", force_role: "auto", speed: 30, pause: false, units: "mmol" });
      await post({ seek_to_crossing_min: 20 });
      clockRunning = true;
      step(1, "Alex is driving home", "Alex has type 1 diabetes. LowSight reads their glucose sensor and knows from the phone that they're in a moving car.", 9000);
      await until((s) => s.reading, my);
      behind(`glucose ${mm(state.reading.mgdl)} mmol/L, ${TREND[state.arrow] || "steady"} · phone: in a moving car · clock running 30× fast`);
      await hold(3000, my);
      await until((s) => s.alert.level === "LOW_SOON", my);

      // 2. The forecast crosses the low line within 30 min → LOW SOON, spoken.
      step(2, "A low is coming, and it warns early", "LowSight forecasts the next 30 minutes. It sees a low ahead and says so through the glasses' speakers: plan a stop.", 9000);
      const fc = state.forecast ? mm(state.forecast.mean[2]) : "?";
      behind(`glucose ${mm(state.reading.mgdl)} mmol/L, but the forecast for +30 min is <b>${fc}</b>, below the 3.9 low line → amber “LOW SOON”`);
      await hold(8000, my);

      // 3. Speed the clock up to the urgent moment → PULL OVER, spoken.
      await post({ speed: 60 });
      await until((s) => s.alert.level === "PULL_OVER", my);
      await post({ pause: true }); // freeze the moment while it's explained
      clockRunning = false;
      step(3, "Now it's urgent", "Blood sugar is low and dropping fast. LowSight tells Alex to pull over, out loud, without them looking at a phone.", 8000);
      behind(`glucose ${mm(state.reading.mgdl)} mmol/L and falling faster than 0.1 mmol/L a minute, under the 5.0 “safe to drive” line → red “PULL OVER”`);
      await hold(7500, my);

      // 4. Acknowledge, as a pinch on the Neural Band or "OK" to Meta AI would.
      await post({ ack: true });
      await until((s) => s.alert.acked, my, 5000);
      step(4, "One pinch: “got it”", "Alex pinches (or says “OK, I'm pulling over”). The warning stays on screen, but it won't repeat.", 7000);
      behind("the backend marks the alert acknowledged · the repeat is cancelled · nothing else needed from the driver");
      await hold(6500, my);

      // 5. Same moment as a passenger → no driving instructions.
      await post({ force_role: "passenger" });
      await until((s) => s.driving.role === "passenger", my, 5000);
      step(5, "Why glasses? They know who's driving", "If the glasses' first-person seat check sees Alex is a passenger, LowSight drops “pull over” and gives a gentle reminder instead.", 9000);
      behind(`same glucose (${mm(state.reading.mgdl)} mmol/L), but seat = passenger → “${state.alert.title} · ${state.alert.line}”`);
      await hold(8500, my);

      finish(my);
    } catch (e) {
      if (!(e instanceof Stopped)) throw e;
    }
  }

  function finish(my) {
    if (my !== undefined && my !== run) return;
    run++;
    clockRunning = false;
    post({ pause: true });
    document.querySelectorAll("#steps i").forEach((el) => { el.className = "done"; });
    $("story").classList.add("hidden");
    $("end").classList.add("on");
    if ("speechSynthesis" in window) speechSynthesis.cancel();
  }

  // ---- speak alerts here (the glasses preview is muted), as they'd sound through the glasses ----
  function speakNew(s) {
    const a = s.alert;
    if (a.level === "NONE" || !a.id || a.id === lastSpokenId) return;
    lastSpokenId = a.id;
    if (!a.speak || !("speechSynthesis" in window)) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(a.speak);
    u.onstart = () => ws && ws.readyState === 1 && ws.send(JSON.stringify({ type: "spoken", id: a.id }));
    speechSynthesis.speak(u);
  }

  function connect() {
    const sock = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/state${q()}`);
    ws = sock;
    sock.onmessage = (e) => {
      const s = JSON.parse(e.data);
      if (s.demo !== (demo || "main")) return;
      state = s;
      if (run && !$("end").classList.contains("on")) speakNew(s);
    };
    sock.onclose = () => { if (ws === sock) setTimeout(connect, 1000); };
  }

  // ---- controls ----
  $("start").onclick = async () => {
    // The click also unlocks speech in the browser.
    if ("speechSynthesis" in window) speechSynthesis.speak(new SpeechSynthesisUtterance(""));
    $("play").classList.add("hidden");
    await ready;
    if (!demo) { busy(); return; }
    play();
  };
  $("pause").onclick = () => {
    paused = !paused;
    $("pause").textContent = paused ? "▶ Resume" : "❚❚ Pause";
    $("steps").classList.toggle("paused", paused);
    if ("speechSynthesis" in window) paused ? speechSynthesis.pause() : speechSynthesis.resume();
    if (clockRunning) post({ pause: paused }); // the story mustn't carry on underneath a pause
  };
  $("skip").onclick = () => finish();
  $("replay").onclick = () => { lastSpokenId = null; play(); };
  $("replay2").onclick = () => { lastSpokenId = null; play(); };

  function busy() {
    $("num").textContent = "Busy right now";
    $("title").textContent = "Lots of people are watching";
    $("text").textContent = "There's no free demo slot at the moment. Try again in a minute, or explore the shared simulator.";
  }

  // ---- start: a private demo for this viewer, so many people can watch at once ----
  const ready = (async () => {
    const r = await fetch("/api/demos", { method: "POST" }).then((x) => x.json()).catch(() => null);
    if (r && r.private) {
      demo = r.code;
      $("try").href = `/control/?s=${demo}`; // "Try it yourself" continues in the same demo
      $("hud").src = `/hud/?mute&s=${demo}`;
      connect();
      await until((s) => s.demo === demo, run, 20000).catch(() => {});
    }
  })();

  const fit = () => { $("hud").style.transform = `scale(${$("frame").clientWidth / 600})`; };
  new ResizeObserver(fit).observe($("frame"));
  fit();
})();
