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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.alerts.engine import EngineInputs, EngineState, evaluate
from backend.cgm import synthetic
from backend.cgm.loaders import load_csv
from backend.cgm.source import ReplaySource
from backend.clock import DemoClock
from backend.config import settings
from backend.forecast import baseline
from backend.hub import Hub
from backend.models import AppState
from backend.driving.context import DrivingContext
from backend.driving.phone import PhoneSignal

log = logging.getLogger("lowsight")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

ANCHOR = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)  # scenario minute 0
HISTORY_H = 3


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
        self.load(settings.SCENARIO)

    def load(self, name: str) -> None:
        self.scenario = name
        self.source = load_scenario(name)
        self.clock.reset(start=ANCHOR)
        self.engine = EngineState()
        self._last_driving = self.ctx.driving
        self.driving_since = self.clock.now()

    def compute(self) -> AppState:
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

        self.engine, _effects = evaluate(
            self.engine, EngineInputs(reading=reading, trend=slope, forecast=fc, driving=driving), now
        )
        return AppState(
            now=now,
            reading=reading,
            trend_mgdl_min=round(slope or 0.0, 2),
            arrow=baseline.arrow(slope),
            forecast=fc,
            driving=driving,
            alert=self.engine.alert,
            history=history,
            units=self.units,
            scenario=self.scenario,
            speed=self.clock.speed,
            paused=self.clock.paused,
        )


rt = Runtime()
hub = Hub()


async def tick_loop() -> None:
    last_level = None
    last_push = 0.0
    while True:
        try:
            state = rt.compute()
            t = time.monotonic()
            changed = state.alert.level != last_level
            if changed or t - last_push >= 1.0:
                await hub.broadcast(state.model_dump_json())
                last_push, last_level = t, state.alert.level
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


@app.post("/api/control")
async def control(c: Control):
    if c.scenario is not None:
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
    state = rt.compute()
    await hub.broadcast(state.model_dump_json())
    return state


@app.websocket("/ws/state")
async def ws_state(ws: WebSocket):
    await hub.connect(ws)
    try:
        await ws.send_text(rt.compute().model_dump_json())
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "ack":
                log.info("ack %s (engine ack handling lands in M4)", msg.get("id"))
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
    """Glasses-session camera frames (binary JPEG) for the seat check.
    M3 plugs the CLIP detector in here. Until then a text message
    ``{"p_driver": 0.9}`` feeds a score directly (handy for tests and demos)."""
    await ws.accept()
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            p = None
            if msg.get("text"):
                p = json.loads(msg["text"]).get("p_driver")
            # elif msg.get("bytes"): p = detector.p_driver(msg["bytes"])  # M3
            seat = rt.ctx.on_frame(float(p), time.monotonic()) if p is not None else None
            await ws.send_json({"p_driver": rt.ctx.seat.ema, "seat": seat, "role": rt.ctx.role})
    except WebSocketDisconnect:
        pass


for name in ("hud", "control", "camera", "phone"):
    app.mount(f"/{name}", StaticFiles(directory=settings.WEB_DIR / name, html=True), name=name)
