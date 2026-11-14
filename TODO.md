# LowSight: to-do list

Tasks follow the milestones in [LOWSIGHT_BUILD_PLAN.md §9](LOWSIGHT_BUILD_PLAN.md#9-milestones-build-in-this-order-each-ends-runnable). Each milestone should end with something that runs.
Put your name in brackets after a task when you take it, e.g. `[Anna]`.

## ✅ Done

- [x] Repo skeleton, config, data models, demo clock, `/api/health`, static pages (M0)
- [x] Four synthetic glucose scenarios, replay source, baseline forecaster, trend arrows (M1)
- [x] Live state over `/ws/state`; ambient HUD with value, arrow, sparkline and forecast band (M1)
- [x] HUD redesign: value in a ring with an orbiting trend spike, alert-coloured ring, sparkline moved to the Forecast view; `/hud/dev.html` slider page (E0W)
- [x] Chose the plain HUD over the React + UI Toolkit version (~36 KB vs ~500 KB); the React one is archived in `archive/hud-app/`
- [x] Phone trip detection (speed + car connection) and driver/passenger context
- [x] Phone page (`/phone`): sends trip signals, speaks alerts, shows notifications
- [x] Control panel: scenario, clock, jump to crossing, in-car and seat overrides, units
- [x] Alert engine with all five levels, dedupe, hysteresis, ack, PULL_OVER repeat (M2, M4)
- [x] Camera page, `/ws/frames` with the CLIP detector slot, seat feedback on the HUD (M3)
- [x] HUD meets Meta's web-app metadata rules; forecast floor; stale states (M5, partly)
- [x] 53 pytest tests passing (alert engine, app wiring, forecast, trip detection, seat check, eval script, plus the 20 JS voice-tool tests run as one)

---

## 1. Do first: check the setup works

- [x] Open the HUD in Meta's **Meta Ray-Ban Display Simulator** Chrome extension on `localhost`: it loads and runs.
- [ ] Install `cloudflared` (`winget install --id Cloudflare.cloudflared`) and repeat over the tunnel URL; confirm ←/→ and Enter (the simulator's D-pad and Select) work and the "View on Glasses QR" is generated.
- [ ] Open `/phone` on a real phone over the tunnel. Check GPS speed, the wake lock, speech, and that notifications appear.
- [ ] **Check whether a browser notification from `/phone` shows on the glasses.** Meta confirmed this for phone app notifications, but not for browser pages. If it doesn't, rely on speech plus the HUD, and say so in the pitch.
- [ ] Check that speech from the phone page plays through the glasses speakers.
- [ ] Open `/camera` on a phone over the tunnel: camera permission, frames streaming, "Checking seat…" then "Driver seat ✓" on the HUD (use the simulate buttons until the vision deps are installed).

## 2. M2: alert engine

- [x] `backend/alerts/engine.py`: pure functions `evaluate(prev_state, inputs, now) -> (state, effects)` and `acknowledge(...)`, with all five levels:
  - [x] **PULL_OVER**: when driving and the reading is below 70, the +10 min forecast is below 70, or the reading is below 90 and falling at −2 mg/dL/min or faster
  - [x] **LOW_SOON**: when driving and the +30 min forecast is below 70 while the reading is still 70 or above; "Low in ~N min", with N rounded to 5 min
  - [x] **PRE_DRIVE**: when low or dropping, and the seat check confirms the driver or a trip starts; escalate to PULL_OVER if it persists 60 s into driving
  - [x] **RECOVERING**: after an acknowledged PULL_OVER while rising; 15-min countdown; clears at 90 or above with a flat or rising trend
  - [x] **NONE** otherwise
- [x] Dedupe: speak each level once per episode. An episode ends after 10 demo-minutes without the condition.
- [x] Hysteresis: only drop to a lower level after 2 consecutive readings without the condition.
- [x] Alert `id` changes for each new alert, so the phone speaks and notifies each one once.
- [x] Wire acknowledgement: Enter on the HUD (`{"type":"ack"}`) and a control-panel button set `acked = True`.
- [x] `tests/test_alert_engine.py`:
  - [x] `falling_while_driving` → LOW_SOON, then PULL_OVER, at the expected times (± one reading): 50 and 60 min
  - [x] `stable_drive` → zero alerts
  - [x] Not in a car, or a confirmed passenger → never LOW_SOON or PULL_OVER
  - [x] Ack silences repeats; noisy readings around 70 don't flap
- [ ] **Done when:** forcing in-car on `falling_while_driving` gives LOW_SOON, then PULL_OVER, spoken by the phone. Verified against the live server with a scripted phone client; **still to hear on a real phone.**

## 3. M3: seat check (vision)

- [x] Vision dependencies are listed in `requirements.txt`; the uv install is `uv sync --extra vision --group dev` (large downloads).
- [x] `backend/vision/clip_detector.py`: CLIP ViT-B-32 zero-shot with driver, passenger and other prompt groups → `p_driver`. A reported run and prompt update moved the public-photo driver examples from 2/4 to 4/4; this is not a representative accuracy result.
  - [x] Downscale to 224 px; skip a frame if the previous one is still processing (never queue).
- [x] Wire the detector into `/ws/frames` for binary JPEG frames.
- [x] `web/camera/`: build the page.
  - [x] Mode A: webcam (`getUserMedia`)
  - [x] Mode B: play a POV video file
  - [x] **"Start seat check"** button: sends frames for at most 3 min, stops early once the seat is decided
  - [x] Overlay showing `p_driver` and the seat result
- [x] HUD: show "Driver seat ✓" / "Passenger seat" when the check decides ("Checking seat…" while frames arrive).
- [ ] Record labelled footage in a parked car: driver's seat, passenger seat, plus indoor clips. Put frames in `data/vision/{driver,passenger,other}/` (gitignored).
- [x] `scripts/eval_vision.py`: accuracy and confusion matrix on ~50 labelled frames. **Run it once the footage exists: this number goes on a pitch slide.**
- [ ] **Done when:** pointing at a steering wheel (or the POV video) confirms "driver" within about 3–5 s, and passenger or indoor frames don't. A reported run found ~3.1 s on steady scores and indoor frames now resolve to "can't tell"; real parked-car passenger and indoor footage still needs validation.

## 4. M4: full hands-free flow

- [x] PRE_DRIVE through both paths: the seat check while parked, and a trip starting without a check.
- [x] RECOVERING countdown on the HUD (mm:ss on the demo clock).
- [ ] ~~`scripts/make_audio.py`~~: probably not needed. Meta's docs say `speechSynthesis` works in glasses web apps (one en-US voice) and don't document `<audio>`, so the HUD speaks directly. Pre-generated mp3s in `web/hud/audio/` are still used as a fallback if a browser has no `speechSynthesis`. Decide whether a fixed recorded voice is worth it.
- [x] HUD audio: don't double up with the phone (skip if the phone already spoke this alert `id`).
- [x] Control panel "Stage audio" toggle: speaks alerts through the laptop speakers.
- [x] Repeat the PULL_OVER audio once if it's unacknowledged for 2 demo-minutes.
- [ ] **Done when:** the full scenario runs with no one touching anything: the phone detects the trip and speaks the alerts. (Needs a real phone run.)

## 5. M5: polish and numbers

- [ ] HUD legibility in the simulator at Medium size over the **brightest** background; fix contrast and sizes.
- [ ] Review the ring + spike design against plan §5.8:
  - [ ] Position: the gauge sits upper-centre, where the plan had the value top right to keep the road view clear. Check it over a driving background.
  - [ ] Colour-blind safety: the spike blends green → red when falling. The angle carries the meaning too; consider a small arrow inside the ring.
  - [ ] PULL_OVER: the banner must not crowd the ring.
- [ ] HUD shows useful state within 1 s of opening (sessions are short). The first load is ~36 KB in 5 requests, about 0.6 s at Meta's 1 KB ≈ 16 ms (budget: under 300 KB and 15 requests), and the server pushes state on connect. Time it in Chrome with network and CPU throttling, then on the glasses.
- [x] Stale-data states: "No CGM data", "x min ago", "Reconnecting…". Still to do: test by killing the backend with the HUD open.
- [x] HUD about view: "Decision support, not medical advice" disclaimer, plus the controls.
- [x] Cap the forecast at 40 mg/dL (and 400) so the band doesn't dip to unrealistic values on steep drops.
- [x] Meta web-app rules: `mrbd-web-app-capable` and `description` meta tags, `width=device-width` viewport, favicon, layout derived from the viewport instead of a fixed 600×600.
- [ ] If the data terms allow: forecaster error on CITY data (`backend/forecast/evaluate.py`: RMSE/MAE at +15/+30 min). Replace the fixed error band with measured quantiles.
- [ ] **Done when:** screenshots look clean on bright and dark scenes, and the accuracy and error numbers exist.

## 6. M7: submission and demo (from h40)

- [ ] Freeze features.
- [ ] Final README: run steps, screenshots, architecture.
- [ ] Pitch deck: problem → demo → why first-person view → numbers → path to production → disclaimer.
- [ ] Use the one-liner and description from the submission draft; add the real vision accuracy and forecast error.
- [ ] Record a backup demo video with the simulator's recorder (driving background).
- [ ] Rehearse the 2-min demo script (plan §11) until it runs **3 times in a row** without touching code. Use **Jump to −20 min** so LOW_SOON shows before PULL_OVER.
- [ ] Check every judging criterion in plan §1.1 against the demo and slides.

---

## Further implementations

### During the hackathon, if time allows (plan §8)

- [ ] **Caregiver escalation:** an unacknowledged PULL_OVER after 2 min pushes to a `/caregiver` page (or SMS via a Twilio trial) with value, trend and "driving". Use a mock location.
- [ ] **Better forecaster:** ridge regression on CITY data (last 6 values, deltas, time of day), split by patient. Switch only if it beats the baseline; put the comparison on a slide.
- [ ] **Real glucose data:** a Nightscout URL or the Dexcom developer sandbox as an alternative glucose source.
- [ ] **`docs/real-hardware.md`:** the path to production (native phone app + DAT seat check), so judges see it's buildable.
- [x] **Voice control (WebMCP):** `web/hud/webmcp.js` registers `lowsight_get_status`, `lowsight_acknowledge_alert` and `lowsight_show_view` for Meta AI; guardrails in every result and the page description; dev-page Voice panel; 20 Node tests (run by pytest) plus an end-to-end check of ack confirmation against the live backend.
  - [ ] On real glasses with WebMCP enabled (Developer Mode, relaunch the app): `await document.modelContext.getTools()` lists all 3 tools, and "Hey Meta, what's my glucose?" answers in one short sentence without dosing advice.
  - [ ] Pitch: show the dev page's Voice panel, or a screen recording of it, as the hands-free demo if no glasses are available.

### After the hackathon: toward a real product

- [ ] **Native phone app (Android first):**
  - Android Activity Recognition (`IN_VEHICLE`) / iOS Core Motion for trips
  - car Bluetooth / Android Auto / CarPlay connection
  - background service, so it keeps working with the screen locked (fixes the browser-tab limits)
  - native push notifications to the glasses display
- [ ] **DAT seat check:** stream glasses-camera frames from the native app during the session the wearer opens (DAT supports Meta Ray-Ban Display; iOS 17.2+ / Android 10+).
- [ ] **On-device vision:** run a small seat classifier on the phone instead of the server (privacy, works offline, no backend needed).
- [ ] **Direct CGM integration:** official partner APIs (e.g. Dexcom, Abbott) or HealthKit / Health Connect, instead of replays.
- [ ] **Personalised forecasting:** adapt the forecast to each user's history; add insulin-on-board and carbs if the user logs them.
- [ ] **Smarter driver detection without a seat check:** learn from habits (e.g. which car, who usually drives) so fewer passenger trips trigger alerts.
- [ ] **Stop suggestions:** "Petrol station in 2 km" with LOW_SOON (mapping integration; currently out of scope).
- [ ] **Trip log:** a history of lows and alerts during drives, to share with a diabetes care team (needs accounts and storage; currently out of scope).
- [ ] **Localisation:** spoken alerts and HUD text in Finnish, Swedish and other languages; mmol/L vs mg/dL per region.
- [ ] **Accessibility:** adjustable text size and alert volume, colour-blind-safe alert colours, haptic alerts via the Neural Band if the platform allows it.
- [ ] **Clinical and regulatory path:** validate with people with T1D and clinicians, and check medical-device rules (EU MDR) before any claims beyond decision support.

### Never in scope

- Insulin dosing advice
- Carb estimation
- Anything that requires interaction while driving
