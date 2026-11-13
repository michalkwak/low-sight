# LowSight

Eyes-up hypoglycaemia alerts for drivers with type 1 diabetes, built as a Meta Ray-Ban Display web app
(Junction hackathon, Meta glasses challenge). The first-person camera tells LowSight that the wearer is in
the driver's seat. LowSight then watches the CGM trend and a short-horizon forecast and gives escalating,
audio-first alerts: **Low soon**, **Pull over**, and a **pre-drive check**.

> **Not medical advice.** LowSight is decision support. It never suggests insulin doses.

Full spec: [LOWSIGHT_BUILD_PLAN.md](LOWSIGHT_BUILD_PLAN.md).

## Status

| Milestone | State |
|---|---|
| M0: skeleton, config, models, DemoClock, health, static mounts | ✅ |
| M1: synthetic scenarios, ReplaySource, baseline forecaster, `/ws/state`, ambient HUD | ✅ (not yet checked in DisplayGlasses.dev) |
| M2: alert engine + tests + control panel | control panel works; engine is a stub that always returns `NONE` |
| M3: CLIP detector + camera page | `/ws/frames` and the driving-state tracker exist; the CLIP detector and camera page are still to build |
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

1. Open `https://<tunnel>/control/` and `https://<tunnel>/camera/` (the camera page goes on the phone you
   use as the "glasses camera").
2. On https://displayglasses.dev, paste `https://<tunnel>/hud/` into **Web App Link** → Load. Set the position
   to **Top Right** or **Mid Right** and the size to Medium. Use **Point of View** mode with a street or
   driving background for screenshots, and **Record** for the demo video.
3. Click into the simulator iframe so the arrow keys and Enter reach the HUD.

Locally, without a tunnel: http://localhost:8000/hud/ and http://localhost:8000/control/.

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
web/       hud/ (glasses app), control/ (demo operator), camera/ (frame source)
data/      scenarios/*.csv (committed); city/ and demo_video/ are gitignored
scripts/   make_scenarios.py
tests/
```

## Data
CITY trial data stays local in `data/city/` (gitignored). Use it only to train and evaluate the forecaster.
The public demo runs on synthetic scenarios.
