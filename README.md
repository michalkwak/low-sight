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

Full spec: [LOWSIGHT_BUILD_PLAN.md](LOWSIGHT_BUILD_PLAN.md).

## Status

| Milestone | State |
|---|---|
| M0: skeleton, config, models, DemoClock, health, static mounts | ✅ |
| M1: synthetic scenarios, ReplaySource, baseline forecaster, `/ws/state`, ambient HUD | ✅ (not yet checked in DisplayGlasses.dev) |
| Phone companion: trip detection, driver/passenger context, speaks + notifies alerts | ✅ (`/phone`, `/api/phone`) |
| M2: alert engine + tests + control panel | control panel works (in-car and seat overrides); engine is a stub that always returns `NONE` |
| M3: CLIP seat check + camera page | `/ws/frames` and seat smoothing exist (accepts `{"p_driver":…}` for testing); the CLIP detector and camera page are still to build |
| M4–M7 | not started |

## Running it

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt          # vision deps (torch, open_clip_torch, pillow) are commented out until M3
python scripts/make_scenarios.py         # writes data/scenarios/*.csv
uvicorn backend.app:app --port 8000
cloudflared tunnel --url http://localhost:8000   # → https://<random>.trycloudflare.com
```

1. Open `https://<tunnel>/control/` on the laptop. On the phone paired with the glasses, open
   `https://<tunnel>/phone/` and tap **Start** (keep it in front; it holds a wake lock). Open
   `https://<tunnel>/camera/` on the device you use as the "glasses camera" for the seat check.
2. On https://displayglasses.dev, paste `https://<tunnel>/hud/` into **Web App Link** → Load. Set the position
   to **Top Right** or **Mid Right** and the size to Medium. Use **Point of View** mode with a street or
   driving background for screenshots, and **Record** for the demo video.
3. Click into the simulator iframe so the arrow keys and Enter reach the HUD.

Locally, without a tunnel: http://localhost:8000/hud/, /control/ and /phone/. (GPS and notifications on a
real phone need HTTPS, so use the tunnel for that.)

### HUD controls
- `←` / `→`: cycle views (Glucose / Forecast detail / About)
- `Enter`: acknowledge the current alert

### Tests
```bash
pytest -q
```

## Layout
```
backend/   FastAPI app, config, models, DemoClock, cgm/, forecast/, vision/, alerts/, hub
backend/driving/  phone trip detection + DrivingContext (in car × seat role)
web/       hud/ (glasses app), phone/ (phone companion), control/ (demo operator), camera/ (seat-check frames)
data/      scenarios/*.csv (committed); city/ and demo_video/ are gitignored
scripts/   make_scenarios.py
tests/
```

## Data
CITY trial data stays local in `data/city/` (gitignored). Use it only to train and evaluate the forecaster.
The public demo runs on synthetic scenarios.
