# LowSight

Eyes-up hypoglycaemia alerts for drivers with type 1 diabetes, built for Meta Ray-Ban Display
(Junction hackathon, Meta glasses challenge). **The phone senses the trip, the glasses confirm you're the
driver, and audio warns you with your eyes up.** LowSight watches the CGM trend and a short-horizon
forecast and gives escalating, audio-first alerts: **Low soon**, **Pull over**, and a **pre-drive check**.

Glasses sessions last at most 3 minutes and only the wearer can start them, so the phone does the
always-on work: it detects the trip, speaks alerts (heard through the glasses speakers) and sends
notifications (shown on the glasses display). The glasses camera does a one-off seat check when the
wearer opens LowSight.

> **Not medical advice.** LowSight is decision support. It never suggests insulin doses.

Full spec: [LOWSIGHT_BUILD_PLAN.md](LOWSIGHT_BUILD_PLAN.md). Task list: [TODO.md](TODO.md).

## Status

| Milestone | State |
|---|---|
| M0: skeleton, config, models, DemoClock, health, static mounts | ✅ |
| M1: synthetic scenarios, ReplaySource, baseline forecaster, `/ws/state`, ambient HUD | ✅ (runs in Meta's simulator) |
| Phone companion: trip detection, driver/passenger context, speaks + notifies alerts | ✅ (`/phone`, `/api/phone`) |
| M2: alert engine (all 5 levels, dedupe, hysteresis, ack) + tests + control panel | ✅ |
| M3: seat check: camera page, `/ws/frames`, CLIP detector, `eval_vision.py` | Implemented; a reported run found 4/4 driver matches on a small public-photo prompt check. This is not a representative accuracy metric; labelled project footage is still needed. |
| M4: PRE_DRIVE (seat check and trip start), RECOVERING countdown, stage audio, PULL_OVER repeat | ✅ (audio uses `speechSynthesis`; no mp3s, see TODO) |
| M5: polish and numbers | partly: forecast floor, stale states, Meta metadata and fluid layout done; legibility, device checks and numbers need people and hardware |
| M6–M7 | not started |

The glasses HUD is the plain HTML/CSS/JS app in `web/hud/` (~36 KB, no build step). An experimental React
version built on Meta's UI Toolkit is archived in [archive/hud-app/](archive/hud-app/): its ~500 KB bundle is
over Meta's first-load budget (under 300 KB, fewer than 15 requests), so it is not served at `/hud/`. Its 13
Vitest tests, TypeScript check, and production build pass under Node 24.15 (see `archive/hud-app/.nvmrc`).

## Running it

```bash
uv sync --group dev                       # backend and test dependencies
uv sync --extra vision --group dev        # also install CLIP vision dependencies
uv run python scripts/make_scenarios.py  # writes data/scenarios/*.csv (already committed)
uv run uvicorn backend.app:app --port 8000
cloudflared tunnel --url http://localhost:8000   # → https://<random>.trycloudflare.com
```

`requirements.txt` remains available as a pip-compatible dependency list; `pyproject.toml` and
`uv.lock` are the supported uv setup. The vision extra installs large packages and downloads
model weights on first use. On Windows, install the tunnel with `winget install --id Cloudflare.cloudflared`.

1. Open `https://<tunnel>/control/` on the laptop. On the phone paired with the glasses, open
   `https://<tunnel>/phone/` and tap **Start** (keep it in front; it holds a wake lock). Open
   `https://<tunnel>/camera/` on the device you use as the "glasses camera" for the seat check.
2. Load the HUD in the **Meta Ray-Ban Display Simulator**, Meta's official Chrome extension
   ([Chrome Web Store](https://chromewebstore.google.com/detail/jpjlmmodokemlepklkdbimceggpbjcll)). Open
   `http://localhost:8000/hud/` (or the tunnel URL) in Chrome and click the extension icon to turn the simulator
   on. Its D-pad and **Select** send arrow and Enter key events to the page. Pick a bright and a driving
   background to check legibility. It can also record a WebM for the demo video and generate a
   "View on Glasses QR" (that one needs the tunnel URL).
3. On real glasses (from Meta's [Test](https://wearables.developer.meta.com/docs/develop/webapps/test/) page):
   enable Developer Mode in the Meta AI app (Settings → App Info → tap the app version 5 times), then
   **App Settings → Apps → Web Apps → Connect Web App**, enter the HTTPS HUD URL and **Save**. Needs glasses
   software v125+ and Meta AI app v272+.

Locally, without a tunnel: http://localhost:8000/hud/, /control/, /phone/ and /camera/. (GPS, the camera and
notifications on a real phone need HTTPS, so use the tunnel for those.)

### Demo flow (plan §11)
- **Pre-drive:** scenario `low_before_drive`, then a seat check on `/camera/` (or **Seat: Driver** on the
  control panel). The HUD shows "Driver seat ✓" and **CHECK BEFORE DRIVING**.
- **Low soon → pull over:** scenario `falling_while_driving`, **In car: On** (or the phone's "Connected to
  car"), then **Jump to −20 min before crossing**: LOW_SOON at the 50-min reading, PULL_OVER at 60. (The
  −5 min jump lands on PULL_OVER directly.) Enter on the HUD acknowledges; `treated_recovery` shows
  **WAIT · RECHECK** with a countdown once glucose rises.
- **Stage audio** on the control panel speaks alerts through the laptop, so the room hears them.

### HUD
The glucose view shows the value inside a ring. A **trend spike** orbits the ring like a CGM arrow:
pointing right is steady, up is rising, down is falling (fully up or down at ±3 mg/dL/min). It glides between
readings and blends green → orange when rising, green → red when falling. The ring takes the alert colour
(amber LOW_SOON / PRE_DRIVE, pulsing red PULL_OVER, cyan RECOVERING) and turns grey with the spike hidden when
the data is stale. The sparkline and forecast are on the Forecast view.

- `←` / `→`: cycle views (Glucose / Forecast detail / About)
- `Enter` (Neural Band select): acknowledge the current alert. It stops the PULL_OVER repeat and keeps the banner.

**Dev page:** <http://localhost:8000/hud/dev.html> embeds the HUD (`/hud/?dev`) and drives it from sliders
(value, trend, alert, acknowledged, trend sweep, fake readings every 2 s) without the backend. Use it in a
normal tab; use `/hud/` itself in the simulator.

### Voice (Meta AI, WebMCP)
The HUD registers three tools on `document.modelContext` ([web/hud/webmcp.js](web/hud/webmcp.js)), so the
wearer can talk to Meta AI instead of using the Neural Band:

| The wearer says | Tool | What happens |
|---|---|---|
| "What's my glucose?", "Am I going low?", "When do I recheck?" | `lowsight_get_status` | Read-only: value, trend, forecast, active alert, recheck time, driving context |
| "OK, I'm pulling over." | `lowsight_acknowledge_alert` | Same as Select; it reports success only after the backend confirms |
| "Show me the forecast." | `lowsight_show_view` | Switches the display to glucose, forecast or about |
| "I'm driving." / "I'm a passenger." | `lowsight_confirm_seat` | Sets the seat like a camera seat check (see below); Meta AI must pass exactly `driver` or `passenger` |

Every result tells Meta AI to answer in one or two short sentences, never to give insulin or carb doses and
never to say it is safe to drive. The same guardrails are in the page's `<meta name="description">`.
The tools are optional: if `document.modelContext` is missing or a registration fails, the HUD works as before.
WebMCP is off by default on the glasses (Developer Mode or rollout) and is decided at launch, so relaunch the
app after turning it on. The dev page's **Voice** panel calls the same tools and shows exactly what Meta AI
gets back, so you can test and demo them without glasses.

### Audio
The phone speaks each alert once (alert `id`s are unique) and reports it back. The HUD, if open, only speaks
an alert that no phone reported within 2.5 s, using `speechSynthesis` (supported on Meta Ray-Ban Display web
apps: one en-US voice). An alert that was already spoken this episode updates silently.

### Seat check
`/camera/` sends a 384 px JPEG every 500 ms over `/ws/frames` for at most 3 minutes, and stops once the seat
is decided (EMA > 0.70 or < 0.30 held for 3 s). Without the vision dependencies the page says so; use
**Test without the vision model** (simulated scores through the same smoothing) or the control-panel seat
override. To get the accuracy number for the pitch, put labelled frames in `data/vision/{driver,passenger,other}/`
and run `python scripts/eval_vision.py`.

**Without a camera** (glasses web apps can't use the glasses camera): the wearer can say "I'm driving" / "I'm a
passenger" to Meta AI, or tap **I'm driving** / **I'm a passenger** on `/phone/`. Both send
`{"type": "seat", "role": …}` on `/ws/state` and work exactly like a decided seat check: the seat holds for the
trip, carries into a trip that starts within 5 minutes, and resets when the trip ends. Saying "driver" while
low and parked raises CHECK BEFORE DRIVING. Safety rules: a "passenger" is **ignored while PULL OVER or CHECK
BEFORE DRIVING is up**, a control-panel override wins, and a camera seat check that is running overrides the
wearer. The state shows who decided the seat in `driving.role_source` (`camera`, `wearer` or `forced`). Like the
other demo endpoints, this socket has no authentication (hackathon).

### Tests
```bash
uv run --group dev pytest -q          # also runs the JS voice-tool tests if Node is installed
node --test tests/js/*.test.js        # the JS tests on their own
```

## Layout
```
backend/   FastAPI app, config, models, DemoClock, cgm/, forecast/, vision/, alerts/, hub
backend/alerts/   engine.py: pure alert state machine (evaluate / acknowledge)
backend/driving/  phone trip detection + DrivingContext (in car × seat role)
backend/vision/   SeatTracker (smoothing) + clip_detector.py (optional CLIP zero-shot)
web/       hud/ (glasses app, webmcp.js voice tools, dev.html), phone/ (phone companion), control/ (demo operator), camera/ (seat-check frames)
archive/   hud-app/: the shelved React + UI Toolkit HUD (not served)
data/      scenarios/*.csv (committed); city/, demo_video/ and vision/ are gitignored
scripts/   make_scenarios.py, eval_vision.py
tests/     pytest suites; js/ holds the Node tests for the voice tools
```

## Data
CITY trial data stays local in `data/city/` (gitignored). Use it only to train and evaluate the forecaster.
The public demo runs on synthetic scenarios.
