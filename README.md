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
| M1: synthetic scenarios, ReplaySource, baseline forecaster, `/ws/state`, ambient HUD | ✅ (not yet checked in a simulator) |
| Phone companion: trip detection, driver/passenger context, speaks + notifies alerts | ✅ (`/phone`, `/api/phone`) |
| M2: alert engine (all 5 levels, dedupe, hysteresis, ack) + tests + control panel | ✅ |
| M3: seat check: camera page, `/ws/frames`, CLIP detector, `eval_vision.py` | Implemented; a reported run found 4/4 driver matches on a small public-photo prompt check. This is not a representative accuracy metric; labelled project footage is still needed. |
| M4: PRE_DRIVE (seat check and trip start), RECOVERING countdown, stage audio, PULL_OVER repeat | ✅ (audio uses `speechSynthesis`; no mp3s, see TODO) |
| M5: polish and numbers | partly: forecast floor, stale states, Meta metadata and fluid layout done; legibility, device checks and numbers need people and hardware |
| M6–M7 | not started |

The experimental React HUD in `web/hud-app/` has source and tests, but it is not the app served at `/hud/`; the plain HUD remains the active implementation. Its locked JavaScript toolchain requires Node 24.15 or newer (see `web/hud-app/.nvmrc`). Under Node 24.15, all 13 Vitest tests, the TypeScript check, and the production build pass.

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
model weights on first use. The React HUD has a separate Node setup: run `nvm install` and
`nvm use` in `web/hud-app/` (which reads `.nvmrc`), then run `npm ci`, `npm test`, and
`npm run build` there.
The lockfile's dependencies require Node 24.15 or newer; the React HUD remains experimental and
is not served at `/hud/`.

1. Open `https://<tunnel>/control/` on the laptop. On the phone paired with the glasses, open
   `https://<tunnel>/phone/` and tap **Start** (keep it in front; it holds a wake lock). Open
   `https://<tunnel>/camera/` on the device you use as the "glasses camera" for the seat check.
2. Load the HUD (`https://<tunnel>/hud/`) in a simulator:
   - **Meta Ray-Ban Display Simulator** (Meta's official Chrome extension,
     [Chrome Web Store](https://chromewebstore.google.com/detail/jpjlmmodokemlepklkdbimceggpbjcll)): open the HUD
     URL in Chrome and click the extension icon to turn the simulator on. Its D-pad and **Select** send arrow
     and Enter key events to the page. It can record a WebM for the demo video and generate a "View on
     Glasses QR". (Whether it works on `http://localhost` is unverified; the tunnel URL works.)
   - **DisplayGlasses.dev**: paste the HUD URL into **Web App Link** → Load. Set the position to **Top Right**
     or **Mid Right** and the size to Medium. Use **Point of View** mode with a street or driving background
     for screenshots, and **Record** for the demo video. Click into the simulator iframe so the arrow keys
     and Enter reach the HUD.
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

### HUD controls
- `←` / `→`: cycle views (Glucose / Forecast detail / About)
- `Enter` (Neural Band select): acknowledge the current alert. It stops the PULL_OVER repeat and keeps the banner.

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

### Tests
```bash
uv run --group dev pytest -q
```

## Layout
```
backend/   FastAPI app, config, models, DemoClock, cgm/, forecast/, vision/, alerts/, hub
backend/alerts/   engine.py: pure alert state machine (evaluate / acknowledge)
backend/driving/  phone trip detection + DrivingContext (in car × seat role)
backend/vision/   SeatTracker (smoothing) + clip_detector.py (optional CLIP zero-shot)
web/       hud/ (glasses app), phone/ (phone companion), control/ (demo operator), camera/ (seat-check frames)
data/      scenarios/*.csv (committed); city/, demo_video/ and vision/ are gitignored
scripts/   make_scenarios.py, eval_vision.py
tests/
```

## Data
CITY trial data stays local in `data/city/` (gitignored). Use it only to train and evaluate the forecaster.
The public demo runs on synthetic scenarios.
