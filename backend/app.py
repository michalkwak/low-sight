"""LowSight backend: FastAPI app, static mounts, websocket hub, tick loop.

Run:  uvicorn backend.app:app --port 8000
"""
import asyncio
import contextlib
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
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
URGENT_LEVELS = ("PULL_OVER", "PRE_DRIVE")  # a wearer "passenger" can't clear these


def scenario_exists(name: str) -> bool:
    return name in synthetic.SCENARIOS or (settings.SCENARIO_DIR / f"{name}.csv").exists()


def load_scenario(name: str):
    path = settings.SCENARIO_DIR / f"{name}.csv"
    df = load_csv(path) if path.exists() else synthetic.generate(name)
    return ReplaySource(df, ANCHOR)


class Runtime:
    def __init__(self, code: str = "main") -> None:
        self.code = code
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
            self.engine, EngineInputs(reading=reading, trend=slope, forecast=fc, driving=driving, wall_s=wall), now
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
            demo=self.code,
        )

    def ack(self, alert_id: str | None) -> bool:
        self.engine, effects = acknowledge(self.engine, alert_id, self.clock.now())
        self._log(effects)
        return bool(effects)

    def confirm_seat(self, role: str) -> bool:
        """The wearer says which seat they're in (voice via Meta AI, or the phone page).
        A "passenger" is ignored while PULL_OVER or PRE_DRIVE is up: a wrong passenger
        silences driving alerts, so one stray tap or misheard sentence must not clear an
        urgent warning. (The backend has no auth by design for the hackathon: any client
        on /ws/state can send this, as it can use the control panel's overrides.)"""
        if role == "passenger" and self.engine.alert.level in URGENT_LEVELS:
            log.info("wearer said passenger during %s: ignored", self.engine.alert.level)
            return False
        self.ctx.confirm_role(role, time.monotonic())
        log.info("seat confirmed by the wearer: %s", role)
        return True

    def mark_spoken(self, alert_id: str | None) -> bool:
        """A phone (or stage audio) spoke this alert, so the HUD shouldn't repeat it."""
        if alert_id and alert_id == self.engine.alert.id and alert_id != self.spoken_id:
            self.spoken_id = alert_id
            return True
        return False


# ---------------------------------------------------------------- per-visitor demos
MAIN = "main"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no O/0 or I/1: easy to read and type
CODE_RE = re.compile(f"[{CODE_ALPHABET}]{{4}}")


@dataclass
class Demo:
    """One independent demo: its own clock, scenario, alert engine, trip and seat state,
    and the pages (sockets) watching it."""

    code: str
    rt: Runtime
    hub: Hub
    last_seen: float
    last_sig: tuple | None = None
    last_push: float = 0.0


class Demos:
    """The shared "main" demo (glasses, old links, no code) plus private demos by code.

    A demo is updated only while a page has it open, so idle demos cost no CPU; at most
    MAX_ACTIVE_DEMOS can be open at once (Render's free plan has a tenth of a core).
    Demos idle for DEMO_IDLE_MIN are deleted. Anything that can't get a private demo
    (switched off, or full) gets the shared one: the worst case is the old behaviour."""

    def __init__(self) -> None:
        self.main = Demo(MAIN, Runtime(MAIN), Hub(), time.monotonic())
        self.rooms: dict[str, Demo] = {}

    @staticmethod
    def normalize(code: str | None) -> str | None:
        code = (code or "").strip().upper()
        return code if CODE_RE.fullmatch(code) else None

    def active(self) -> int:
        return sum(1 for d in self.rooms.values() if d.hub.count > 0)

    def _room_allowed(self) -> bool:
        self.prune()
        return (
            settings.PER_VISITOR_DEMOS
            and self.active() < settings.MAX_ACTIVE_DEMOS
            and len(self.rooms) < settings.MAX_DEMOS
        )

    def _new_room(self, code: str) -> Demo:
        d = self.rooms[code] = Demo(code, Runtime(code), Hub(), time.monotonic())
        log.info("demo %s created (%d demos, %d active)", code, len(self.rooms), self.active())
        return d

    def create(self) -> tuple[Demo, str | None]:
        """A new private demo, or (main, reason) when that isn't possible."""
        if not settings.PER_VISITOR_DEMOS:
            return self.main, "off"
        if not self._room_allowed():
            return self.main, "busy"
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
            if code not in self.rooms:
                return self._new_room(code), None

    def get(self, code: str | None, create: bool = False) -> Demo | None:
        """The demo for a code. No code, a malformed code, or the off switch → main.
        A valid code NEVER falls back to main (that would let a visitor drive the shared
        glasses demo): an unknown one is created only when ``create`` (the live socket
        does that, e.g. after a server restart) and there is room; otherwise None."""
        c = self.normalize(code)
        if c is None or not settings.PER_VISITOR_DEMOS:
            return self.main
        d = self.rooms.get(c)
        if d is None:
            if not create or not self._room_allowed():
                return None
            d = self._new_room(c)
        d.last_seen = time.monotonic()
        return d

    def can_open(self, d: Demo) -> bool:
        """Opening a page on a private demo that nobody has open makes it active (updated
        every tick), so it counts against MAX_ACTIVE_DEMOS."""
        return d is self.main or d.hub.count > 0 or self.active() < settings.MAX_ACTIVE_DEMOS

    def prune(self) -> None:
        cutoff = time.monotonic() - settings.DEMO_IDLE_MIN * 60
        for code, d in list(self.rooms.items()):
            if d.hub.count == 0 and d.last_seen < cutoff:
                del self.rooms[code]
                log.info("demo %s expired", code)

    def ticking(self) -> list[Demo]:
        return [self.main] + [d for d in self.rooms.values() if d.hub.count > 0]


demos = Demos()
rt = demos.main.rt  # the shared demo (tests and the code-less endpoints use it)
hub = demos.main.hub


async def tick_loop() -> None:
    last_prune = time.monotonic()
    while True:
        for d in demos.ticking():
            try:
                state = d.rt.compute()
                t = time.monotonic()
                a = state.alert
                sig = (a.id, a.acked, a.spoken, a.title, a.line)
                if sig != d.last_sig or t - d.last_push >= 1.0:
                    await d.hub.broadcast(state.model_dump_json())
                    d.last_push, d.last_sig = t, sig
                if d is not demos.main:
                    d.last_seen = t
            except Exception:
                log.exception("tick failed for demo %s", d.code)
        if time.monotonic() - last_prune > 30:
            demos.prune()
            last_prune = time.monotonic()
        await asyncio.sleep(settings.TICK_S)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(tick_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="LowSight", lifespan=lifespan)
# Hackathon: open CORS. No X-Frame-Options/frame-ancestors, so /hud/dev.html (and any simulator) can iframe the HUD.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
def root():
    """Start page for visitors and judges: what LowSight is, plus links to every page.
    The glasses use /hud/ directly."""
    return RedirectResponse("/start/")


@app.get("/llms.txt")
def llms_txt():
    """Page instructions for Meta AI (the glasses' agent). Also served at /hud/llms.txt,
    beside the app; which path the host fetches is unverified, so both work."""
    return FileResponse(settings.WEB_DIR / "hud" / "llms.txt", media_type="text/plain; charset=utf-8")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "scenario": rt.scenario,
        "clients": hub.count,
        "now": rt.clock.now().isoformat(),
        "per_visitor_demos": settings.PER_VISITOR_DEMOS,
        "demos": len(demos.rooms),
        "active_demos": demos.active(),
    }


@app.post("/api/demos")
def new_demo():
    """A private demo for one visitor. ``private`` is false (with ``reason`` "off" or
    "busy") when they get the shared demo instead."""
    d, reason = demos.create()
    return {"code": d.code, "private": d is not demos.main, "reason": reason}


def demo_for(s: str | None) -> Demo:
    """HTTP endpoints act on an existing demo only (no creating demos with a plain GET).
    A valid but unknown code (expired, or the server restarted) is a 404, never main."""
    d = demos.get(s)
    if d is None:
        raise HTTPException(404, "unknown demo: open the simulator again for a new one")
    return d


@app.get("/api/state")
def get_state(s: str | None = None):
    return demo_for(s).rt.compute()


@app.get("/api/scenarios")
def scenarios(s: str | None = None):
    return {"scenarios": synthetic.SCENARIOS, "current": demo_for(s).rt.scenario}


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
async def control(c: Control, s: str | None = None):
    d = demo_for(s)
    rt = d.rt
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
    await d.hub.broadcast(state.model_dump_json())
    return state


@app.websocket("/ws/state")
async def ws_state(ws: WebSocket, s: str | None = None):
    """Server → client: AppState JSON at ~1 Hz and on every alert change.
    Client → server: {"type": "ack", "id": …} (Enter on the HUD),
    {"type": "spoken", "id": …} (the phone or stage audio spoke that alert) and
    {"type": "seat", "role": "driver" | "passenger"} (the wearer says which seat they're in).
    ``?s=CODE`` picks a private demo; without it, the shared one."""
    d = demos.get(s, create=True)
    if d is None or not demos.can_open(d):
        await ws.accept()
        await ws.close(code=1013, reason="busy")  # 1013 = try again later; never main for a private code
        return
    rt, hub = d.rt, d.hub
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
            elif msg.get("type") == "seat" and msg.get("role") in ("driver", "passenger"):
                changed = rt.confirm_seat(msg["role"])
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
async def phone(p: PhoneIn, s: str | None = None):
    """Phone context signal, sent about once a second by the /phone page."""
    rt = demo_for(s).rt
    rt.ctx.on_phone(PhoneSignal(speed_kmh=p.speed_kmh, car_connected=p.car_connected, wall_s=time.monotonic()))
    return rt.ctx.snapshot(rt.driving_since, time.monotonic())


@app.websocket("/ws/frames")
async def ws_frames(ws: WebSocket, s: str | None = None):
    """One seat check = one connection, limited to SESSION_MAX_S like a glasses session.

    Binary JPEG frames go to the CLIP detector. The latest frame wins: a frame that
    arrives while the previous one is still being scored replaces any waiting frame,
    so frames never queue. A text message ``{"p_driver": 0.9}`` feeds a score directly
    (tests, and the camera page's simulate buttons). Every scored frame gets a reply
    ``{p_driver (smoothed), p_frame, seat, role, elapsed_s}``, plus ``error`` or ``done``."""
    d = demos.get(s, create=True)
    await ws.accept()
    if d is None:
        await ws.close(code=1013, reason="busy")
        return
    rt = d.rt
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


for name in ("start", "tour", "hud", "control", "camera", "phone"):
    app.mount(f"/{name}", StaticFiles(directory=settings.WEB_DIR / name, html=True), name=name)
