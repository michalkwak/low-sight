"""LowSight backend: FastAPI app, static mounts, websocket hub, tick loop.

Run:  uvicorn backend.app:app --port 8000
"""
import asyncio
import contextlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.alerts.engine import EngineInputs, EngineState, acknowledge, evaluate
from backend.cgm import synthetic
from backend.cgm.loaders import load_csv
from backend.cgm.source import ReplaySource
from backend.clock import DemoClock
from backend.config import settings
from backend.driving.context import DrivingContext
from backend.driving.phone import PhoneSignal
from backend.forecast import baseline
from backend.hub import Hub
from backend.models import AppState
from backend.vision import clip_detector

log = logging.getLogger("lowsight")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

ANCHOR = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)  # scenario minute 0
HISTORY_H = 3


def scenario_exists(name: str) -> bool:
    return name in synthetic.SCENARIOS or (settings.SCENARIO_DIR / f"{name}.csv").exists()


def load_scenario(name: str):
    path = settings.SCENARIO_DIR / f"{name}.csv"
    df = load_csv(path) if path.exists() else synthetic.generate(name)
    return ReplaySource(df, ANCHOR)


class Runtime:
    def __init__(self) -> None:
        self.units = settings.UNITS
        self.clock = DemoClock(speed=settings.SPEED)
        self.ctx = DrivingContext()
        self.engine = EngineState()
        self.spoken_id = ""
        self.load(settings.SCENARIO)

    def load(self, name: str) -> None:
        self.scenario = name
        self.source = load_scenario(name)
        self.clock.reset(start=ANCHOR)
        self.engine = EngineState()
        self.spoken_id = ""
        self._last_driving = self.ctx.driving
        self.driving_since = self.clock.now()

    @staticmethod
    def _log(effects: list[dict]) -> None:
        for e in effects:
            log.info("alert %s %s %s%s", e["type"], e["level"], e.get("id", ""), " (silent)" if e["type"] == "raise" and not e.get("speak") else "")

    def compute(self) -> AppState:
        """Advance the alert engine to the demo clock's now and build the state."""
        now = self.clock.now()
        readings = self.source.readings_until(now)
        history = [r for r in readings if r.t >= now - timedelta(hours=HISTORY_H)]
        reading = readings[-1] if readings else None
        slope = baseline.trend(readings, now)
        fc = baseline.forecast(readings, now)

        wall = time.monotonic()
        self.ctx.tick(wall)
        if self.ctx.driving != self._last_driving:
            self._last_driving = self.ctx.driving
            self.driving_since = now
        driving = self.ctx.snapshot(self.driving_since, wall)

        self.engine, effects = evaluate(
            self.engine, EngineInputs(reading=reading, trend=slope, forecast=fc, driving=driving), now
        )
        self._log(effects)
        alert = self.engine.alert
        if alert.id and alert.id == self.spoken_id:
            alert = alert.model_copy(update={"spoken": True})
        return AppState(
            now=now,
            reading=reading,
            trend_mgdl_min=round(slope or 0.0, 2),
            arrow=baseline.arrow(slope),
            forecast=fc,
            driving=driving,
            alert=alert,
            history=history,
            units=self.units,
            scenario=self.scenario,
            speed=self.clock.speed,
            paused=self.clock.paused,
            force_driving=self.ctx.force_vehicle,
            force_role=self.ctx.force_role,
        )

    def ack(self, alert_id: str | None) -> bool:
        self.engine, effects = acknowledge(self.engine, alert_id, self.clock.now())
        self._log(effects)
        return bool(effects)

    def mark_spoken(self, alert_id: str | None) -> bool:
        """A phone (or stage audio) spoke this alert, so the HUD shouldn't repeat it."""
        if alert_id and alert_id == self.engine.alert.id and alert_id != self.spoken_id:
            self.spoken_id = alert_id
            return True
        return False


rt = Runtime()
hub = Hub()


async def tick_loop() -> None:
    last_sig = None
    last_push = 0.0
    while True:
        try:
            state = rt.compute()
            t = time.monotonic()
            a = state.alert
            sig = (a.id, a.acked, a.spoken, a.title, a.line)
            if sig != last_sig or t - last_push >= 1.0:
                await hub.broadcast(state.model_dump_json())
                last_push, last_sig = t, sig
        except Exception:
            log.exception("tick failed")
        await asyncio.sleep(settings.TICK_S)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(tick_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="LowSight", lifespan=lifespan)
# Hackathon: open CORS. No X-Frame-Options/frame-ancestors so DisplayGlasses.dev can iframe the HUD.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
def root():
    return RedirectResponse("/hud/")


@app.get("/api/health")
def health():
    return {"ok": True, "scenario": rt.scenario, "clients": hub.count, "now": rt.clock.now().isoformat()}


@app.get("/api/state")
def get_state():
    return rt.compute()


@app.get("/api/scenarios")
def scenarios():
    return {"scenarios": synthetic.SCENARIOS, "current": rt.scenario}


class Control(BaseModel):
    scenario: str | None = None
    speed: float | None = None
    pause: bool | None = None
    seek_min: float | None = None
    seek_to_crossing_min: float | None = None  # e.g. 5 → jump to 5 min before first reading < LOW
    force_driving: Literal["on", "off", "auto"] | None = None  # overrides the phone's in-vehicle signal
    force_role: Literal["driver", "passenger", "auto"] | None = None  # overrides the glasses seat check
    units: Literal["mmol", "mgdl"] | None = None
    reset: bool | None = None
    ack: bool | None = None  # acknowledge the current alert (same as Enter on the HUD)


@app.post("/api/control")
async def control(c: Control):
    if c.scenario is not None:
        if not scenario_exists(c.scenario):
            raise HTTPException(400, f"unknown scenario {c.scenario!r}")
        rt.load(c.scenario)
    if c.reset:
        rt.load(rt.scenario)
        rt.ctx.reset()
    if c.speed is not None:
        rt.clock.set_speed(c.speed)
    if c.pause is True:
        rt.clock.pause()
    elif c.pause is False:
        rt.clock.resume()
    if c.seek_min is not None:
        rt.clock.seek(c.seek_min)
    if c.seek_to_crossing_min is not None:
        t = rt.source.first_crossing(settings.LOW)
        if t is not None:
            rt.clock.seek_to(t - timedelta(minutes=c.seek_to_crossing_min))
    if c.force_driving is not None:
        rt.ctx.force_vehicle = c.force_driving
    if c.force_role is not None:
        rt.ctx.force_role = c.force_role
    if c.units is not None:
        rt.units = c.units
    if c.ack:
        rt.compute()  # make sure we ack what is on screen now
        rt.ack(None)
    state = rt.compute()
    await hub.broadcast(state.model_dump_json())
    return state


@app.websocket("/ws/state")
async def ws_state(ws: WebSocket):
    """Server → client: AppState JSON at ~1 Hz and on every alert change.
    Client → server: {"type": "ack", "id": …} (Enter on the HUD) and
    {"type": "spoken", "id": …} (the phone or stage audio spoke that alert)."""
    await hub.connect(ws)
    try:
        await ws.send_text(rt.compute().model_dump_json())
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except (ValueError, KeyError):  # not JSON, or a binary frame
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "ack":
                changed = rt.ack(msg.get("id"))
            elif msg.get("type") == "spoken":
                changed = rt.mark_spoken(msg.get("id"))
            else:
                continue
            if changed:
                await hub.broadcast(rt.compute().model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(ws)


class PhoneIn(BaseModel):
    speed_kmh: float | None = None  # GPS speed; None if unavailable
    car_connected: bool = False  # car Bluetooth / CarPlay / Android Auto (stand-in toggle on /phone)


@app.post("/api/phone")
async def phone(p: PhoneIn):
    """Phone context signal, sent about once a second by the /phone page."""
    rt.ctx.on_phone(PhoneSignal(speed_kmh=p.speed_kmh, car_connected=p.car_connected, wall_s=time.monotonic()))
    return rt.ctx.snapshot(rt.driving_since, time.monotonic())


@app.websocket("/ws/frames")
async def ws_frames(ws: WebSocket):
    """One seat check = one connection, limited to SESSION_MAX_S like a glasses session.

    Binary JPEG frames go to the CLIP detector. The latest frame wins: a frame that
    arrives while the previous one is still being scored replaces any waiting frame,
    so frames never queue. A text message ``{"p_driver": 0.9}`` feeds a score directly
    (tests, and the camera page's simulate buttons). Every scored frame gets a reply
    ``{p_driver (smoothed), p_frame, seat, role, elapsed_s}``, plus ``error`` or ``done``."""
    await ws.accept()
    opened = time.monotonic()
    rt.ctx.start_seat_check()
    send_lock = asyncio.Lock()
    pending: list[bytes] = []  # at most one waiting frame
    wake = asyncio.Event()
    dropped = 0

    async def reply(p_frame: float | None = None, seat: str | None = None, **extra) -> None:
        msg = {
            "p_driver": round(rt.ctx.seat.ema, 3),
            "p_frame": None if p_frame is None else round(p_frame, 3),
            "seat": seat,
            "role": rt.ctx.role,
            "elapsed_s": round(time.monotonic() - opened, 1),
            "dropped": dropped,
            **extra,
        }
        async with send_lock:
            await ws.send_json(msg)

    async def score_frames() -> None:
        while True:
            await wake.wait()
            wake.clear()
            if not pending:
                continue
            frame = pending.pop()
            detector, why = await asyncio.to_thread(clip_detector.get_detector)
            if detector is None:
                await reply(error=why)
                continue
            try:
                probs = await asyncio.to_thread(detector.frame_probs, frame)
            except Exception as e:  # undecodable frame etc.
                log.warning("seat frame failed: %s", e)
                await reply(error=f"frame failed: {e}")
                continue
            p = clip_detector.seat_score(probs)
            await reply(
                p_frame=p,
                seat=rt.ctx.on_frame(p, time.monotonic()),
                probs={k: round(v, 3) for k, v in probs.items()},
            )

    worker = asyncio.create_task(score_frames())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if time.monotonic() - opened > settings.SESSION_MAX_S:
                await reply(done=True, reason="session limit")
                break
            if msg.get("bytes"):
                if pending:
                    pending.clear()
                    dropped += 1
                pending.append(msg["bytes"])
                wake.set()
            elif msg.get("text"):
                try:
                    p = min(max(float(json.loads(msg["text"])["p_driver"]), 0.0), 1.0)
                except (ValueError, KeyError, TypeError):
                    await reply(error='expected a JPEG frame or {"p_driver": 0..1}')
                    continue
                await reply(p_frame=p, seat=rt.ctx.on_frame(p, time.monotonic()))
    except WebSocketDisconnect:
        pass
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await worker
        rt.ctx.end_seat_check()
        with contextlib.suppress(Exception):
            await ws.close()


for name in ("hud", "control", "camera", "phone"):
    app.mount(f"/{name}", StaticFiles(directory=settings.WEB_DIR / name, html=True), name=name)
