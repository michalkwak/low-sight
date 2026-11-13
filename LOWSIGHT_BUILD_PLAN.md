# LowSight — Build Plan & Architecture

> **For Claude Code:** This is the full spec for a 48-hour hackathon project. Build it in the milestone order in §9 and get a thin end-to-end slice working first (fake data → HUD on screen). Then deepen each part. Keep every component runnable on its own. Ask before adding heavy dependencies beyond what's listed.

---

## 1. Context

- **Event:** Junction hackathon, Meta glasses challenge (48 h).
- **Theme:** "How a first-person POV enables new or better interactions in everyday life."
- **Challenge page:** https://hackjunction.app/participate/45/challenges/342. *The full requirements and judging criteria are not in this file. Paste them into §1.1 before building and check §10 against them.*
- **Hardware:** We have **no physical glasses**. The HUD runs in the **DisplayGlasses.dev** simulator (https://displayglasses.dev), which previews web apps for Meta Ray-Ban Display in the browser.

### 1.1 Challenge judgement

```
Creativity and use case
(25%)
Technical execution
(25%)
Real-world value and feasibility
(25%)
User experience: input, accessibility and trust
(25%)
```

### 1.2 Platform facts confirmed with the Meta supervisor (2026-11-13)

1. Glasses sessions last **at most 3 minutes** and can **only be started by the wearer**. This applies to Display Web Apps **and** to camera access through the Device Access Toolkit (DAT).
2. A phone app **can push a notification** that shows on the glasses display.
3. Audio the phone plays (e.g. text-to-speech) **comes out of the glasses speakers** with no glasses app open.

**Consequence:** the glasses can't watch for the steering wheel continuously. The **phone** detects the trip and delivers the alerts (voice through the glasses speakers, plus a notification on the display). The glasses camera is used for a **one-off seat check** in a session the wearer opens, which tells us whether they're the driver or a passenger.

---

## 2. The product in one paragraph

**LowSight** keeps people with type 1 diabetes safe from hypoglycaemia while driving. **The phone senses the trip, the glasses confirm you're the driver, and audio warns you with your eyes up.** The phone companion knows when the wearer is in a moving car (speed, car Bluetooth/CarPlay). When the wearer opens LowSight on the glasses before setting off, the first-person camera checks that **they are in the driver's seat (steering wheel in view)**. While driving, LowSight watches the CGM trend and a short-horizon **glucose forecast**, and the phone gives escalating, audio-first alerts that play through the glasses speakers and appear as a notification on the display:

- **"Low soon"**: the forecast shows a low within ~30 min while the wearer is still in range. Plan a stop.
- **"Pull over"**: the wearer is low now, or a low is imminent. Stop safely and treat.
- **Pre-drive check**: the wearer opens LowSight in the driver's seat (or a trip starts) and is already low or trending low. "Treat before you set off."

A phone on the dashboard can show a number. It can't tell whether you're the driver, and it can't put the warning in your ears and line of sight without you looking down. Opening the glasses app mid-drive is a quick glance: value, arrow, forecast, alert.

**Not medical advice.** LowSight is decision support. It never suggests insulin doses. Put this on the HUD's about screen and in the pitch.

---

## 3. Platform constraints (verified, plan around these)

| Constraint | Implication |
|---|---|
| Display Web Apps are HTML/CSS/JS on a **600×600** canvas, monocular (right lens), **additive** display: black = transparent | Black background. Bright, high-contrast elements only. No large bright fills. |
| Input is a **D-pad**: arrow keys plus **Enter** (Neural Band gestures arrive as these events) | Every interaction works with ↑↓←→ and Enter. No mouse or touch. |
| Web Apps **cannot access the camera or microphone**. Only the native **Device Access Toolkit (DAT)** mobile SDK can | The seat check runs **off the HUD**: a camera source sends frames to the backend. For the hackathon the camera source is a laptop or phone webcam, or a recorded POV video. On real hardware it would be a DAT Android/iOS app. |
| Glasses sessions (Web App **and** DAT camera) last **≤ 3 min** and are **started only by the wearer** | No continuous on-glasses detection or alerting. **Trip detection and alert delivery live on the phone.** Vision is a one-off seat check (decides in ~3 s, well inside a session). The HUD is designed for short glances. |
| The phone can push notifications to the display, and phone audio plays through the glasses speakers | Alerts = phone TTS (heard through the glasses) + phone notification (seen on the display). Tapping the notification opens the HUD for detail. |
| Hosted at a **public HTTPS URL** (simulator loads it via URL, glasses via QR) | Serve the HUD over HTTPS (tunnel or static deploy). Backend sockets must be **wss://**. |
| Some sites block iframe embedding in the simulator | Don't send `X-Frame-Options: DENY` or a restrictive `frame-ancestors` CSP from the HUD host. |

---

## 4. Architecture

```
 ┌──────────────────────┐  speed + car-connected (1 Hz) ┌────────────────────────────────────┐
 │  Phone companion      │ ───────────────────────────▶ │            Backend (FastAPI)        │
 │  /phone page          │ ◀────── state (wss) ──────── │                                    │
 │  GPS speed, car BT    │                              │  DrivingContext                    │
 │  toggle; SPEAKS alerts│                              │   phone → in_vehicle (trip)        │
 │  (→ glasses speakers) │                              │   seat check → role driver/pass.   │
 │  + notification       │                              │   driving = in_vehicle ∧ ¬passenger│
 │  (→ glasses display)  │                              │                                    │
 └──────────────────────┘                              │  VisionService (seat check)         │
                                                       │   CLIP zero-shot "driver's seat?"  │
 ┌──────────────────────┐  JPEG frames (2 fps, WS),    │   → EMA → driver / passenger       │
 │  Glasses camera       │  only during a ≤3 min        │                                    │
 │  (seat check)         │  user-started session        │  CGMSource                          │
 │  • /camera page       │ ───────────────────────────▶ │   replay CSV (CITY / synthetic)    │
 │    stands in for it   │                              │   on accelerated demo clock        │
 │  • [future] DAT app   │                              │                                    │
 └──────────────────────┘                              │  Forecaster                         │
                                                       │   +10/+20/+30 min with band        │
 ┌──────────────────────┐   control cmds (REST)        │                                    │
 │  Demo Control Panel   │ ───────────────────────────▶ │  AlertEngine (state machine)        │
 │  /control             │ ◀─────────── state ───────── │   NONE / LOW_SOON / PULL_OVER /    │
 │  scenario, speed, in- │                              │   PRE_DRIVE / RECOVERING           │
 │  car + seat overrides │                              │                                    │
 └──────────────────────┘                              │  Hub: broadcasts AppState JSON      │
                                                       │                                    │
 ┌──────────────────────┐   state push (wss, ~1 Hz)    │                                    │
 │  HUD Web App          │ ◀─────────────────────────── │                                    │
 │  600×600, opened by   │ ── ack (Enter) ────────────▶ │                                    │
 │  wearer, ≤3 min glance│                              └────────────────────────────────────┘
 └──────────────────────┘
```

The phone is the always-on part. The glasses are opened briefly, by the wearer: once before setting off (seat check + pre-drive check), and for glances while driving or when a notification arrives.

### 4.1 Tech stack
- **Backend:** Python 3.11, FastAPI, uvicorn, websockets, numpy, pandas, pydantic.
- **Vision:** `open_clip_torch` (ViT-B-32, `laion2b_s34b_b79k`) on CPU, about 1–2 fps. Pillow for decoding.
- **Forecasting:** numpy baseline. Optional scikit-learn ridge regression trained on CITY.
- **HUD, control and camera pages:** plain HTML/CSS/vanilla JS, served as static files by FastAPI. No build step, so it's quick to iterate in the simulator.
- **HTTPS:** `cloudflared tunnel --url http://localhost:8000` (or ngrok) gives one public HTTPS origin for everything, so the HUD can use `wss://` on the same host.

### 4.2 Repo layout
```
lowsight/
  README.md
  backend/
    app.py                 # FastAPI app, routes, static mounts, websocket hub
    config.py              # thresholds, units, speeds (pydantic Settings, env overridable)
    models.py              # pydantic: CGMReading, Forecast, DrivingState, Alert, AppState
    clock.py               # DemoClock: real or accelerated time, pause/seek
    cgm/
      source.py            # CGMSource interface + ReplaySource
      loaders.py           # load_city(path, mapping), load_csv(path)
      synthetic.py         # scenario generator (falling-while-driving, stable, rebound)
    forecast/
      baseline.py          # damped linear extrapolation + residual band
      ridge.py             # optional: lag-feature ridge trained on CITY
      evaluate.py          # CLI: RMSE/MAE at +15/+30 vs baseline
    vision/
      clip_detector.py     # zero-shot classifier, returns p(driver_seat)
      driving_state.py     # SeatTracker: EMA + hold → driver / passenger
    driving/
      phone.py             # VehicleTracker: phone speed / car connection → in_vehicle
      context.py           # DrivingContext: in_vehicle + seat role + overrides → DrivingState
    alerts/
      engine.py            # state machine + dedupe + ack + escalation
    hub.py                 # connection manager, broadcast AppState
  web/
    hud/index.html, hud.css, hud.js         # the glasses app
    hud/audio/*.mp3                          # pre-generated spoken alerts
    control/index.html, control.js           # demo control panel
    camera/index.html, camera.js             # webcam/video → frames (stands in for the glasses camera session)
    phone/index.html, phone.js, sw.js        # phone companion: trip signals, speaks alerts, notifications
  data/
    scenarios/*.csv        # synthetic demo traces (committed)
    city/                  # CITY data (gitignored, never committed)
    demo_video/pov_drive.mp4 (gitignored)
  scripts/
    make_scenarios.py
    make_audio.py          # generate TTS mp3s (e.g. pyttsx3 / gTTS / edge-tts)
    eval_vision.py         # run detector over labelled frames, print accuracy
  tests/
    test_alert_engine.py
    test_forecast.py
    test_driving_state.py
```

---

## 5. Components in detail

### 5.1 Data model (`models.py`)
```python
class CGMReading(BaseModel):  t: datetime; mgdl: float
class Forecast(BaseModel):    t0: datetime; horizons_min: list[int]          # [10,20,30]
                              mean: list[float]; lo: list[float]; hi: list[float]   # mg/dL
class DrivingState(BaseModel): driving: bool            # in_vehicle and role != "passenger"
                              in_vehicle: bool          # phone
                              role: Literal["driver","passenger","unknown"]   # glasses seat check
                              p_driver: float; speed_kmh: float | None; car_connected: bool
                              phone_stale: bool; source: Literal["phone","forced"]; since: datetime
class Alert(BaseModel):       level: Literal["NONE","LOW_SOON","PRE_DRIVE","PULL_OVER","RECOVERING"]
                              title: str; line: str; speak: str | None; acked: bool; id: str
class AppState(BaseModel):    now: datetime; reading: CGMReading | None; trend_mgdl_min: float
                              arrow: str; forecast: Forecast | None; driving: DrivingState
                              alert: Alert; history: list[CGMReading]   # last 3 h for sparkline
                              units: Literal["mmol","mgdl"]
```
Store everything internally in **mg/dL**. Convert for display (`mmol = mgdl / 18.0`). **Default display unit: mmol/L** (Finland/EU). Make it switchable in config.

### 5.2 Demo clock (`clock.py`)
- `speed` multiplier (default **30×**, so one 5-min CGM sample every 10 s of real time). Configurable from the control panel: 1×, 10×, 30×, 60×.
- `pause()`, `resume()`, `seek(minutes)`, `reset()`.
- Every time-dependent component uses `clock.now()`, never `datetime.now()`.

### 5.3 CGM source (`cgm/`)
- `ReplaySource(df)` emits readings whose timestamp ≤ `clock.now()`. Interpolation isn't needed, since we use the 5-min samples as they are.
- **`load_city(path, mapping)`**: the CITY trial CGM export. Column names vary between Jaeb releases, so take a mapping `{patient_col, time_col, value_col}` and print the detected columns if the mapping fails. Pick one patient and a window that contains a real falling episode (helper: `find_lows(df, below=70, min_drop=40, within_min=60)`).
  - ⚠️ **Data-use terms:** CITY data stays local (gitignored). Use it to *train/evaluate* the forecaster. For the **public demo, use synthetic scenarios** unless the team has confirmed the terms allow displaying real traces.
- **`synthetic.py`** generates scenarios at 5-min resolution with mild sensor noise (±3 mg/dL):
  1. `falling_while_driving`: stable ~130 for 40 min, then a decline accelerating to −2.5 mg/dL/min, crossing 70 about 60 min in. **Main demo.**
  2. `low_before_drive`: already 72 and falling at t=0, for the pre-drive check.
  3. `stable_drive`: 110–140 the whole time, so no alerts fire (false-alarm control).
  4. `treated_recovery`: a low followed by a rise after "treatment".

### 5.4 Forecaster (`forecast/`)
- **Baseline (build first):** fit a weighted linear regression over the last 20 min (5 points, recent points weighted higher). Extrapolate to +10/+20/+30 min with **damping** (slope × 0.85 per 10 min) so the forecast doesn't run away. Band = ± residual quantile (80% interval) taken from `evaluate.py` on CITY, or a fixed ±(6, 12, 20) mg/dL if CITY isn't available.
- **Ridge (stretch):** features = last 6 values, deltas, time of day. Targets = +15 and +30 min. Train on CITY with a train/test split **by patient** and report RMSE vs. baseline in `evaluate.py`. Only switch to it if it beats the baseline. Put the RMSE comparison on a pitch slide.
- **Trend arrow** from the 15-min slope (mg/dL/min): `≤-3 ⇊`, `≤-2 ↓`, `≤-1 ↘`, `<1 →`, `<2 ↗`, `<3 ↑`, else `⇈`.
- Output nothing if there are fewer than 3 readings in the last 20 min (sensor gap). The HUD then shows "No CGM data".

### 5.5 Driving detection (`driving/` + `vision/`)
Two signals, because the glasses can't run continuously (§1.2):

| Signal | Source | Answers | When |
|---|---|---|---|
| `in_vehicle` | Phone (`driving/phone.py`) | "Is the wearer in a moving car?" | Always on, ~1 Hz |
| `role` | Glasses camera seat check (`vision/`) | "Are they the driver or a passenger?" | Once per trip, in a session the wearer opens |

**Phone trip detection (`VehicleTracker`):**
- Hackathon: the `/phone` page sends GPS speed (`watchPosition`) and a "Connected to car" toggle (stand-in for car Bluetooth / CarPlay / Android Auto) to `POST /api/phone` every second. A simulated-speed slider covers indoor demos.
- Native (future): Android Activity Recognition `IN_VEHICLE` / iOS Core Motion `automotive`, plus the car's Bluetooth or CarPlay/Android Auto connection. Same `PhoneSignal` contract.
- Trip **starts** when the car is connected, or speed ≥ 15 km/h for ≥ 10 s (so running for a bus doesn't count).
- Trip **ends** when speed < 5 km/h and the car is disconnected for ≥ 5 min (traffic lights and short stops don't end it), or when the phone has been silent for 5 min.

**Combining (`DrivingContext`):**
- `role` starts as `unknown` on each trip. A seat check sets it to `driver` or `passenger` for the rest of the trip. A check done while parked carries into a trip that starts within 5 min. The role resets when the trip ends.
- **`driving = in_vehicle and role != "passenger"`.** An unconfirmed wearer in a moving car is treated as possibly driving, because missing a real driver is worse than warning a passenger. A confirmed passenger gets no driving alerts (their normal CGM app alarms still apply).
- **Control-panel overrides:** `force_driving` (in car: on/off/auto) and `force_role` (driver/passenger/auto). Essential demo fallbacks.

**Seat check (vision):** detect that the wearer's POV is *from the driver's seat*. COCO detectors have no steering-wheel class, so use **CLIP zero-shot classification** on each frame. It runs only while a glasses session is open (≤ 3 min), so it must decide within seconds.

- Prompt groups (average the text embeddings within each group):
  - **driver** (positive): "a first-person view from the driver's seat of a car, steering wheel in front", "POV of a person driving a car, hands on the steering wheel", "car dashboard and steering wheel seen by the driver"
  - **passenger**: "first-person view from the passenger seat of a car", "view of a car dashboard from the passenger side with no steering wheel in front"
  - **other**: "a person walking on a street, first-person view", "indoors in a room", "an office desk with a laptop", "a kitchen", "a supermarket aisle"
- `p_driver = softmax(group_logits * 100)[driver]`.
- **Temporal smoothing (`SeatTracker`)**: EMA with α = 0.3 at 2 fps. Decide `driver` when EMA > 0.70 for ≥ 3 s, `passenger` when EMA < 0.30 for ≥ 3 s. One odd frame never decides. Typical time to decide: 3–5 s.
- On the HUD, show the result ("Driver seat ✓" / "Passenger") so the wearer knows the check happened. If no decision is reached before the session closes, the role stays `unknown`.
- Downscale frames to 224 px. Skip a frame if the previous one is still processing (never queue).
- Until the CLIP detector is wired in (M3), `/ws/frames` also accepts a text message `{"p_driver": 0.9}` for testing.
- **`scripts/eval_vision.py`**: run on ~50 labelled frames (record a phone video in a parked car from the driver's and passenger's seats, plus indoor footage) and print accuracy and a confusion matrix. That gives an honest number for the pitch.
- *Future (document, don't build):* on real hardware, a DAT Android/iOS app streams glasses-camera frames to the same `/ws/frames` endpoint during the session the wearer opens. The contract stays the same.

### 5.6 Alert engine (`alerts/engine.py`)
Inputs every tick: `reading`, `trend`, `forecast`, `driving` (the full `DrivingState`, so `in_vehicle` and `role` are available). "When `driving`" below means `in_vehicle and role != "passenger"` (§5.5). Thresholds are in `config.py` (mg/dL):

| Constant | Default | Note |
|---|---|---|
| `LOW` | 70 (3.9 mmol) | hypo level 1 |
| `DRIVE_MIN` | 90 (5.0 mmol) | "five to drive" style threshold for the pre-drive check |
| `LOW_SOON_HORIZON` | 30 min | |
| `IMMINENT_HORIZON` | 10 min | |
| `FAST_FALL` | −2.0 mg/dL/min | |

**Rules, highest priority first:**
1. **PULL_OVER**, only when `driving`: `reading < LOW`, **or** `forecast(+10).mean < LOW`, **or** (`reading < DRIVE_MIN` and `trend ≤ FAST_FALL`).
   HUD: red-amber "PULL OVER" + glucose + "Stop safely · take fast carbs". Audio: *"Your glucose is low. Pull over when it's safe and take fast-acting sugar."*
2. **PRE_DRIVE**: fires when `reading < DRIVE_MIN` or `forecast(+30).mean < LOW` **and** either (a) the seat check confirms `driver` (the wearer opened the glasses in the driver's seat, typically still parked), or (b) a trip starts (`in_vehicle` false → true) and the wearer isn't a confirmed passenger. Case (a) is the main path and is shown on the open HUD; case (b) reaches the wearer through the phone. HUD: "Check before driving" + value + "Treat before you set off". Audio: *"Before you drive: your glucose is low or dropping. Treat it first."* If this condition persists past 60 s of driving, escalate to PULL_OVER.
3. **LOW_SOON**, only when `driving`: `forecast(+30).mean < LOW` (or `lo < LOW` and `mean < LOW + 10`) while `reading ≥ LOW`. HUD: amber "Low in ~N min" + "Plan a stop". Audio: *"Heads up: you may go low in about N minutes. Plan a stop."* Compute N by linear interpolation of the forecast to the LOW crossing, rounded to 5 min.
4. **RECOVERING**: after a PULL_OVER is acknowledged and the reading is rising, show "Wait 15 min · recheck" with a countdown on the demo clock. Clear when `reading ≥ DRIVE_MIN` and trend ≥ 0. (Encodes "treat, wait, recheck before driving on".)
5. Otherwise **NONE**.

**Behaviour rules:**
- **Dedupe:** speak each level at most once per episode. An episode ends when the condition has been false for 10 demo-minutes.
- **Escalation:** LOW_SOON → PULL_OVER may happen at any time. De-escalation needs the condition to be false for 2 consecutive readings (hysteresis).
- **Ack:** Enter on the HUD (or the control-panel button) sets `acked = True`, which silences repeats but keeps the banner. If PULL_OVER is unacked for 2 demo-minutes, repeat the audio once (stretch: notify a caregiver, see §8).
- **While driving, never require interaction.** Ack is optional.
- **Delivery:** the glasses HUD is usually closed while driving, so every alert is delivered by the **phone**: spoken (`speak` text, heard through the glasses speakers) and as a notification (title + line + value, shown on the glasses display). The HUD shows the same banner when the wearer opens it. Each new alert `id` is spoken and notified once.
- Pure function core: `evaluate(prev_state, inputs, now) -> (alert, effects)`, so it can be unit-tested without I/O.

### 5.7 Hub & API (`app.py`, `hub.py`)
- `GET /` → redirects to `/hud/`
- Static mounts: `/hud`, `/control`, `/camera`, `/phone`
- `WS /ws/state`: server pushes `AppState` JSON at 1 Hz, plus immediately whenever the alert changes. Client → server: `{"type":"ack","id":...}`
- `WS /ws/frames`: client sends binary JPEG (or, for testing, text `{"p_driver":0.9}`). Server replies `{"p_driver":..,"seat":..,"role":..}` (shown on the camera page for debugging)
- `POST /api/phone`: `{speed_kmh, car_connected}` from the phone companion, ~1 Hz. Returns the current `DrivingState`.
- `POST /api/control`: `{scenario, speed, pause, seek_min, seek_to_crossing_min, force_driving, force_role, units, reset}`
- `GET /api/health`
- Tick loop: an asyncio background task every 0.5 s real time: pull new CGM readings → forecast → driving state → alert engine → broadcast.
- CORS is open (hackathon). No `X-Frame-Options` header, so the simulator can iframe the HUD.

### 5.8 HUD web app (`web/hud/`), the glasses UI
**Hard rules:** 600×600 container, `background:#000`, no element larger than ~40% of the area lit at full brightness, everything keyboard-navigable, legible over a moving street scene.

**Sessions:** the wearer opens the HUD; it closes after ≤ 3 min. Design for a glance: the important information must be on screen in the first second after it opens (connect fast, show the last known state immediately, no intro). Typical opens: (1) before setting off, for the seat check and pre-drive check; (2) a quick glance while driving; (3) tapping a LowSight notification.

**Layouts:**
- **Ambient (NONE, not driving):** top right: large glucose value (e.g. `6.4`) + trend arrow + unit. Under it a 3 h sparkline (thin 2 px line, dimmed) with a dotted forecast segment and a faint band. Small badge when driving: "● Driver" once the seat check confirmed it, otherwise "● In car".
- **Seat check result:** brief "Driver seat ✓" or "Passenger" line when the check decides during the session.
- **Driving + NONE:** value and arrow only. **No sparkline while driving**, to keep visual load minimal.
- **LOW_SOON:** amber (#FFB020) outline banner: "LOW IN ~20 MIN" / "Plan a stop". Value + arrow.
- **PULL_OVER:** strong red-orange (#FF5A36) banner, large text "PULL OVER", line "Stop safely · fast carbs", value + arrow. Gentle pulse on the border only (≤1 Hz, no full-screen flashing).
- **PRE_DRIVE:** amber "CHECK BEFORE DRIVING" / "Treat before you set off".
- **RECOVERING:** green-cyan (#3EE6C1) "WAIT · RECHECK" + countdown mm:ss.
- **No data / disconnected:** grey "No CGM data" or "Reconnecting…". Never show a stale value without marking it (dim it and add "x min ago").

**Typography:** system sans, bold. Glucose value ~120 px, banner title ~56 px, secondary ~32 px. Never below 28 px.

**Input:** `Enter` = acknowledge the current alert. `←/→` = cycle views (Glucose / Forecast detail / About & disclaimer). `↑/↓` = unused (reserved). Show focus states clearly.

**Audio:** the **phone** is the primary audio path (§5.11); its speech plays through the glasses speakers (confirmed by Meta). While the HUD is open it may also play the matching mp3 from `hud/audio/`, but must not double up with the phone (skip if the phone already spoke this alert `id`). For the demo, the **control panel can also speak** the alert through the laptop speakers ("Stage audio"), so audio always works on stage.

**Connection:** derive the ws URL from `location` (`wss:` when `https:`). Auto-reconnect with backoff.

### 5.9 Control panel (`web/control/`)
Big buttons for the demo operator: scenario picker, Play/Pause, speed, "Jump to −5 min before crossing", In car (phone) On/Off/Auto, Seat (glasses) Driver/Passenger/Auto, Ack, Units, Reset. Live readouts: current value, forecast, phone speed and car connection, in-car, seat role and p_driver, driving, alert level, an event log. Speaks alerts (speechSynthesis) when "Stage audio" is on.

### 5.10 Camera page (`web/camera/`): stand-in for the glasses camera session
- Mode A: `getUserMedia` (works on a phone browser over HTTPS). A phone on a **head strap or taped to a cap** gives a convincing POV for a live demo in a parked car.
- Mode B: play `pov_drive.mp4` (file picker) and grab frames from the `<video>`, for a reproducible stage demo.
- A **"Start seat check"** button sends frames for at most 3 min (matching the glasses session limit), then stops. It stops early once the seat is decided.
- Send a JPEG (quality 0.7, 384 px wide) every 500 ms over `/ws/frames`. Show the returned p_driver and seat result as an overlay.

### 5.11 Phone companion (`web/phone/`)
The always-on part of LowSight. Hackathon version is a web page; production is a native app (§8).
- **Start** button (needs a user gesture): primes `speechSynthesis`, registers `sw.js`, asks for notification permission, takes a screen wake lock, starts `geolocation.watchPosition`.
- Sends `{speed_kmh, car_connected}` to `POST /api/phone` every second. "Connected to car" toggle stands in for car Bluetooth/CarPlay; a simulated-speed slider overrides GPS for indoor demos.
- Listens on `/ws/state`. On each new alert `id`: **speak** the `speak` text (plays through the glasses speakers) and **show a notification** (`LowSight: <title>`, body `<line> · <value> <arrow>`, `requireInteraction` for PULL_OVER). The notification reaches the glasses display.
- Shows value, speed, in-car and role for debugging.
- *Unverified:* that a **web** notification from mobile Chrome/Safari is mirrored to the glasses (Meta confirmed it for phone app notifications in general; mirroring may be per app). Fallback for the demo: the spoken alert plus the HUD.

---

## 6. Config defaults (`config.py`, env-overridable)
```
UNITS=mmol  SPEED=30  TICK_S=0.5
LOW=70 DRIVE_MIN=90 FAST_FALL=-2.0 LOW_SOON_HORIZON=30 IMMINENT_HORIZON=10
EMA_ALPHA=0.3 ENTER_P=0.70 EXIT_P=0.30 ENTER_S=3 SESSION_MAX_S=180
PHONE_SPEED_ON_KMH=15 PHONE_ON_S=10 PHONE_SPEED_OFF_KMH=5 TRIP_END_S=300 PHONE_STALE_S=30
SCENARIO=falling_while_driving  CITY_PATH=data/city/  CLIP_MODEL=ViT-B-32  CLIP_PRETRAINED=laion2b_s34b_b79k
```

---

## 7. Running it
```bash
python -m venv .venv && source .venv/bin/activate
pip install fastapi "uvicorn[standard]" numpy pandas pydantic pydantic-settings pillow open_clip_torch torch scikit-learn pytest
python scripts/make_scenarios.py && python scripts/make_audio.py
uvicorn backend.app:app --port 8000
cloudflared tunnel --url http://localhost:8000      # → https://<random>.trycloudflare.com
```
1. Open `https://<tunnel>/control/` on the laptop. On the phone paired with the glasses, open `https://<tunnel>/phone/` and tap **Start**. Open `https://<tunnel>/camera/` on the device you'll use as the "glasses camera" for the seat check.
2. On https://displayglasses.dev paste `https://<tunnel>/hud/` into **Web App Link** → Load. Position **Top Right** or **Mid Right**, Medium. Use **Point of View** mode with a street/driving background for screenshots, and **Record** for the demo video.
3. Click into the simulator iframe so arrow keys and Enter reach the HUD.

Write these steps into `README.md`.

---

## 8. Stretch goals (only after §9 M5 is done)
1. **Caregiver escalation:** an unacked PULL_OVER after 2 min sends an SMS (Twilio trial) or a push to a `/caregiver` page with value, trend and "driving". Mock location.
2. **Ridge forecaster** trained on CITY, with an RMSE slide.
3. **Real CGM:** Dexcom developer sandbox API or a Nightscout URL as an alternative `CGMSource`.
4. **Path-to-production doc:** a short `docs/real-hardware.md`: a native phone app (Activity Recognition / Core Motion + car Bluetooth for trips, TTS through the glasses, push notifications to the display) and the DAT seat check → `/ws/frames` during a wearer-opened session, so judges see the path to production.

**Out of scope:** insulin dosing, route/store navigation, carb estimation, accounts, persistence.

---

## 9. Milestones (build in this order; each ends runnable)

| # | Target time | Deliverable | Done when |
|---|---|---|---|
| M0 | h0–2 | Repo skeleton, config, models, DemoClock, `/api/health`, static mounts | `uvicorn` runs, `/hud/` serves a black page |
| M1 | h2–6 | Synthetic scenarios + ReplaySource + baseline forecaster + `/ws/state` + HUD ambient layout | HUD in DisplayGlasses.dev (via tunnel) shows a live, moving glucose value + arrow |
| M2 | h6–10 | Alert engine (all 5 levels) + unit tests + control panel with in-car/seat overrides + **phone page speaks and notifies alerts** | Forcing in-car on `falling_while_driving` shows LOW_SOON then PULL_OVER at the right times, spoken by the phone. Tests pass. |
| M3 | h10–16 | CLIP detector + seat smoothing + camera page (webcam + video modes, 3-min seat-check session) | Pointing a phone at a steering wheel (or a POV video) confirms "driver" within ~3–5 s. Passenger/indoor frames don't. |
| M4 | h16–22 | PRE_DRIVE (seat check + trip start), RECOVERING, ack via Enter, audio mp3s, stage audio, dedupe/escalation | Full scenario runs hands-free end to end: phone detects trip, alerts spoken by the phone |
| M5 | h22–30 | Polish HUD for legibility (test over bright backgrounds in the simulator), stale-data states, `eval_vision.py` numbers, CITY forecaster eval | Screenshots look clean on bright and dark scenes. Accuracy/RMSE numbers exist. |
| M6 | h30–40 | Stretch goals (§8) as time allows. Record demo video in a parked car. | — |
| M7 | h40–46 | Freeze features. README, pitch deck, backup video, rehearse. | Demo runs 3× in a row without touching code |
| — | h46–48 | Buffer / submission | |

---

## 10. Testing checklist
- `test_alert_engine.py`: each scenario CSV produces the expected sequence of alert levels and times (± one reading). `stable_drive` produces **zero** alerts. Not driving → never LOW_SOON or PULL_OVER. Ack silences repeats. Hysteresis prevents flapping on noisy data around 70.
- `test_forecast.py`: a flat trace gives a flat forecast. A linear fall is extrapolated within tolerance. A sensor gap gives no forecast.
- `test_driving_state.py`: one false-positive frame doesn't decide the seat; steady driver/passenger frames decide within a session. Phone speed must hold before a trip starts; a car connection starts it at once; a traffic-light stop doesn't end it; a silent phone ends it after `TRIP_END_S`. Unconfirmed in-car counts as driving; a confirmed passenger doesn't, until the trip ends. A parked seat check carries into the trip. Overrides win.
- Not in a car, or a confirmed passenger → never LOW_SOON or PULL_OVER.
- Manual: the HUD is legible in the simulator at Medium size over the brightest background. Every view is reachable with arrows and Enter only. Killing the backend shows "Reconnecting…" and recovers. The HUD shows useful state within 1 s of opening. The phone page speaks an alert with the screen on and the page in front.
- Re-read §1.1 (challenge requirements) and tick each one off.

---

## 11. Demo script (~2 min)
1. **Problem (15 s):** CGM alarms go off in a pocket or bag while you drive. You can't pick up your phone, and a dashboard phone doesn't know you're the one driving.
2. **Pre-drive (30 s):** the wearer sits in the driver's seat and opens LowSight on the glasses. The seat check sees the steering wheel ("Driver seat ✓") and the HUD shows "CHECK BEFORE DRIVING" with audio, because glucose is already 4.6 and falling.
3. **Low soon → pull over (45 s):** switch to the `falling_while_driving` scenario at 60×; the phone reports a trip (connected to car / speed). The glasses are closed, as they would be while driving. The phone speaks "Heads up: you may go low in about 20 minutes" through the glasses speakers, and a notification appears on the display. Then "PULL OVER", spoken. Tap the notification: the HUD opens on the "PULL OVER" banner. Enter (Neural Band pinch) acknowledges, and the HUD moves to "WAIT · RECHECK".
4. **Why POV (15 s):** the phone knows you're in a car; only the first-person view knows you're the driver. Same glucose, different behaviour for the driver and a passenger. No interaction needed, eyes stay up.
5. **Credibility (15 s):** vision accuracy on our labelled frames, forecaster RMSE (CITY, if allowed), and a path to production that respects the platform: 3-minute wearer-started sessions, phone does the always-on work. Decision support, not dosing advice.

**Fallbacks:** in-car and seat override toggles if the phone or vision is flaky on stage. Simulated-speed slider on the phone page. Pre-recorded POV video in camera mode B. Control panel "Stage audio". Full backup screen recording from DisplayGlasses.dev.

---

## 12. Known risks
- **Vision false positives** (passenger seat, car interiors in photos): mitigated by the passenger prompts, the hold time and the override toggles. Report the measured accuracy honestly.
- **No seat check this trip** (wearer didn't open the glasses): role stays `unknown` and LowSight alerts anyway (safe default). A passenger may get alerts they don't need.
- **Phone web page limits:** a backgrounded or locked browser tab may stop GPS, speech and timers. For the demo keep the page in front with the wake lock. A native app (§8) fixes this.
- **Web notifications on the glasses:** confirmed for phone notifications in general, unverified for a browser page. Speech through the glasses speakers is the main channel.
- **CGM lag and low-range inaccuracy:** this is part of why forecasting matters. Mention it in Q&A.
- **Simulator ≠ hardware:** HUD web-app audio and real camera streaming via DAT are unverified on device. State this clearly and show the path to production.
- **Data terms:** CITY stays local. Demo on synthetic traces.
