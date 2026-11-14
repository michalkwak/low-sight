"""Alert engine: a pure state machine (plan §5.6).

    evaluate(prev, inputs, now)        -> (state, effects)   # every tick
    acknowledge(prev, alert_id, now)   -> (state, effects)   # Enter on the HUD / control panel

Neither function mutates ``prev`` or does I/O, so both are unit-tested directly.

Levels, highest priority first ("driving" = in_vehicle and role != "passenger"):
  PULL_OVER   driving and (reading < LOW, or the +10 min forecast < LOW, or reading
              < DRIVE_MIN while falling at FAST_FALL or faster), or a PRE_DRIVE that
              is still true after PRE_DRIVE_ESCALATE_S of driving.
  PRE_DRIVE   reading < DRIVE_MIN or the +30 min forecast < LOW, armed when the seat
              check confirms the driver or a trip starts (not for a confirmed passenger).
  LOW_SOON    driving, reading >= LOW and the +30 min forecast < LOW (or its lower
              bound < LOW with the mean < LOW + 10). "Low in ~N min".
              A confirmed passenger in the car gets LOW_SOON (never PULL_OVER) for both
              the LOW_SOON and the PULL_OVER conditions, worded for someone who isn't
              driving ("Treat when you can"). A wrong "passenger" from the seat check
              therefore softens the wording but never silences the warning.
  RECOVERING  after a PULL_OVER once glucose is rising and the driver has stopped (they
              acknowledged it, or a live phone reports < PHONE_SPEED_OFF_KMH with glucose
              already >= LOW): wait RECOVER_WAIT_MIN, recheck. Clears at >= DRIVE_MIN with a
              flat or rising trend. A live phone showing the car moving again while glucose
              is still < DRIVE_MIN (or dropping) brings PULL_OVER back.
  NONE        otherwise.

Behaviour:
  - Escalation is immediate. Dropping a level needs its glucose condition to be false
    for HYSTERESIS_READINGS consecutive new readings, so noise around 70 can't flap.
    Leaving the car drops the driving-only levels at once; a confirmed passenger turns
    PULL_OVER into the passenger LOW_SOON at once.
  - Each level is spoken at most once per episode. An episode ends after its condition
    has been false for EPISODE_GAP_MIN. A silent alert has ``speak = None``.
  - Every alert gets a fresh ``id``, so the phone speaks and notifies it exactly once.
  - An unacknowledged PULL_OVER repeats its audio once after REPEAT_PULL_OVER_MIN, and no
    sooner than REPEAT_MIN_WALL_S real seconds after it was raised (keeps a fast demo clock
    from stacking the repeat on top of the first announcement).
  - Acknowledging silences the repeat but keeps the banner.
  - A reading older than STALE_MIN raises nothing new; without new readings an active
    alert is held (a sensor gap is not a reason to clear a warning).

All times are demo time (``now`` comes from the DemoClock), except ``inputs.wall_s``.
"""
import copy
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.config import settings
from backend.models import Alert, CGMReading, DrivingState, Forecast

LEVELS = ("NONE", "RECOVERING", "LOW_SOON", "PRE_DRIVE", "PULL_OVER")  # ascending priority
GLUCOSE_LEVELS = ("PULL_OVER", "PRE_DRIVE", "LOW_SOON")

SPEAK = {
    "PULL_OVER": "Your glucose is low. Pull over when it's safe and take fast-acting sugar.",
    "PRE_DRIVE": "Before you drive: your glucose is low or dropping. Treat it first.",
    "LOW_SOON": "Heads up: you may go low in about {n} minutes. Plan a stop.",
    "RECOVERING": "Glucose is rising. Wait {n} minutes and recheck before you drive on.",
    # A confirmed passenger: same warning, no driving instructions.
    "PASSENGER_SOON": "Heads up: you may go low in about {n} minutes. Treat it when you can.",
    "PASSENGER_LOW": "Your glucose is low. Treat it when you can.",
}


def _passenger(d: DrivingState) -> bool:
    """In the car with the seat check saying passenger (not driving)."""
    return d.in_vehicle and d.role == "passenger"


@dataclass
class EngineInputs:
    reading: CGMReading | None
    trend: float | None
    forecast: Forecast | None
    driving: DrivingState
    wall_s: float | None = None  # real seconds, monotonic and advancing; only spaces out the PULL_OVER repeat


@dataclass
class Episode:
    last_true: datetime | None = None  # last time the level's condition held
    spoken: bool = False
    repeated: bool = False  # PULL_OVER audio already repeated


def _new_epoch() -> str:
    return secrets.token_hex(3)


@dataclass
class EngineState:
    alert: Alert = field(default_factory=Alert)
    epoch: str = field(default_factory=_new_epoch)  # keeps ids unique across engine resets
    seq: int = 0
    last_reading_t: datetime | None = None
    in_vehicle: bool = False  # previous tick, to detect a trip starting
    role: str = "unknown"  # previous tick, to detect a seat confirmation
    held: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(GLUCOSE_LEVELS, False))
    misses: dict[str, int] = field(default_factory=lambda: dict.fromkeys(GLUCOSE_LEVELS, 0))
    episodes: dict[str, Episode] = field(default_factory=dict)
    pre_armed: bool = False
    pre_driving_since: datetime | None = None
    pre_escalated: bool = False
    recovering: bool = False
    recover_ok: int = 0  # consecutive readings meeting the recovery clear condition
    recover_until: datetime | None = None
    alert_wall_s: float | None = None  # real time the current alert was raised
    drove_on: bool = False  # drove off during RECOVERING: a stop alone can't re-enter it until the alert clears


def _stopped(d: DrivingState) -> bool:
    """A live phone reports the car (nearly) stopped: evidence the driver has pulled over."""
    return d.speed_kmh is not None and not d.phone_stale and d.speed_kmh < settings.PHONE_SPEED_OFF_KMH


def _moving(d: DrivingState) -> bool:
    """A live phone reports the car clearly moving. Uses the trip-start speed, so 5–15 km/h
    (crawling, GPS jitter at a standstill) is neither stopped nor moving and can't flap."""
    return d.speed_kmh is not None and not d.phone_stale and d.speed_kmh >= settings.PHONE_SPEED_ON_KMH


# ---------------------------------------------------------------- forecast helpers
def _curve(reading: CGMReading, fc: Forecast, attr: str) -> list[tuple[float, float]]:
    return [(0.0, reading.mgdl)] + list(zip(map(float, fc.horizons_min), getattr(fc, attr)))


def _at(curve: list[tuple[float, float]], h: float) -> float | None:
    """Linear interpolation at ``h`` minutes after the forecast's t0 (None beyond it)."""
    for (t0, v0), (t1, v1) in zip(curve, curve[1:]):
        if t0 <= h <= t1:
            return v0 + (v1 - v0) * (h - t0) / (t1 - t0)
    return None


def minutes_to_low(reading: CGMReading, fc: Forecast, now: datetime) -> int:
    """Minutes from ``now`` until the forecast mean crosses LOW, rounded to 5 (min 5).
    If the mean never crosses inside the horizon (band-only trigger), use the horizon."""
    low = settings.LOW
    crossing = float(settings.LOW_SOON_HORIZON)
    curve = _curve(reading, fc, "mean")
    for (t0, v0), (t1, v1) in zip(curve, curve[1:]):
        if v0 >= low > v1:
            crossing = t0 + (v0 - low) / (v0 - v1) * (t1 - t0)
            break
    elapsed = (now - fc.t0).total_seconds() / 60
    return max(5, int(5 * round((crossing - elapsed) / 5)))


def _glucose_conditions(inp: EngineInputs, now: datetime) -> dict[str, bool]:
    r = inp.reading
    if r is None or now - r.t > timedelta(minutes=settings.STALE_MIN):
        return dict.fromkeys(GLUCOSE_LEVELS, False)
    v, trend, fc = r.mgdl, inp.trend, inp.forecast
    m_imm = m_soon = lo_soon = None
    if fc is not None:
        m_imm = _at(_curve(r, fc, "mean"), settings.IMMINENT_HORIZON)
        m_soon = _at(_curve(r, fc, "mean"), settings.LOW_SOON_HORIZON)
        lo_soon = _at(_curve(r, fc, "lo"), settings.LOW_SOON_HORIZON)
    low = settings.LOW
    falling_fast = trend is not None and trend <= settings.FAST_FALL
    return {
        "PULL_OVER": v < low
        or (m_imm is not None and m_imm < low)
        or (v < settings.DRIVE_MIN and falling_fast),
        "PRE_DRIVE": v < settings.DRIVE_MIN or (m_soon is not None and m_soon < low),
        "LOW_SOON": v >= low
        and m_soon is not None
        and (m_soon < low or (lo_soon is not None and lo_soon < low and m_soon < low + 10)),
    }


# ---------------------------------------------------------------- alert building
def _texts(level: str, s: EngineState, inp: EngineInputs, now: datetime) -> tuple[str, str, str]:
    """(title, line, speak) for a level, with the dynamic parts filled in."""
    if level == "PULL_OVER":
        return "PULL OVER", "Stop safely · take fast carbs", SPEAK["PULL_OVER"]
    if level == "PRE_DRIVE":
        return "CHECK BEFORE DRIVING", "Treat before you set off", SPEAK["PRE_DRIVE"]
    if level == "LOW_SOON":
        passenger = _passenger(inp.driving)
        if passenger and inp.reading is not None and inp.reading.mgdl < settings.LOW:
            return "LOW GLUCOSE", "Treat when you can", SPEAK["PASSENGER_LOW"]
        n = minutes_to_low(inp.reading, inp.forecast, now) if inp.forecast and inp.reading else settings.LOW_SOON_HORIZON
        if passenger:
            return f"LOW IN ~{n} MIN", "Treat when you can", SPEAK["PASSENGER_SOON"].format(n=n)
        return f"LOW IN ~{n} MIN", "Plan a stop", SPEAK["LOW_SOON"].format(n=n)
    if level == "RECOVERING":
        wait = f"{settings.RECOVER_WAIT_MIN:g}"
        done = s.recover_until is not None and now >= s.recover_until
        line = "Recheck now" if done else f"Wait {wait} min · recheck"
        return "WAIT · RECHECK", line, SPEAK["RECOVERING"].format(n=wait)
    return "", "", ""


def _next_id(s: EngineState, level: str) -> str:
    s.seq += 1
    return f"{s.epoch}-{s.seq}-{level.lower()}"


def _raise(level: str, s: EngineState, inp: EngineInputs, now: datetime) -> dict:
    ep = s.episodes.setdefault(level, Episode(last_true=now))
    title, line, speak = _texts(level, s, inp, now)
    if ep.spoken:
        speak = None  # dedupe: this level was already spoken this episode
    ep.spoken = True
    s.alert = Alert(
        level=level,
        title=title,
        line=line,
        speak=speak,
        id=_next_id(s, level),
        since=now,
        until=s.recover_until if level == "RECOVERING" else None,
    )
    s.alert_wall_s = inp.wall_s
    return {"type": "raise", "level": level, "id": s.alert.id, "speak": speak}


# ---------------------------------------------------------------- public API
def evaluate(prev: EngineState, inp: EngineInputs, now: datetime) -> tuple[EngineState, list[dict]]:
    s = copy.deepcopy(prev)
    effects: list[dict] = []
    d = inp.driving
    new_reading = inp.reading is not None and inp.reading.t != s.last_reading_t
    glu = _glucose_conditions(inp, now)
    trend = inp.trend
    fresh = inp.reading is not None and now - inp.reading.t <= timedelta(minutes=settings.STALE_MIN)

    # 1. Hysteresis per glucose condition, counted in new readings.
    for lvl in GLUCOSE_LEVELS:
        if glu[lvl]:
            s.held[lvl], s.misses[lvl] = True, 0
        elif s.held[lvl] and new_reading:
            s.misses[lvl] += 1
            if s.misses[lvl] >= settings.HYSTERESIS_READINGS:
                s.held[lvl], s.misses[lvl] = False, 0

    # 2. RECOVERING starts when a PULL_OVER sees glucose rising and the driver has evidently
    #    stopped: they acknowledged it, or the phone reports the car stopped. (Without either,
    #    an unacknowledged PULL_OVER clears normally once glucose recovers.)
    cur = s.alert
    if (
        not s.recovering
        and cur.level == "PULL_OVER"
        and fresh
        # Stopped alone is weak evidence (a red light), so it never replaces PULL_OVER while
        # glucose is still below LOW; an acknowledgement is a deliberate act and can.
        and (cur.acked or (_stopped(d) and inp.reading.mgdl >= settings.LOW and not s.drove_on))
        and trend is not None
        and trend >= settings.RISE_MIN
    ):
        s.recovering, s.recover_ok = True, 0
        s.recover_until = now + timedelta(minutes=settings.RECOVER_WAIT_MIN)
        # The acknowledged PULL_OVER (and any PRE_DRIVE escalation behind it) is resolved.
        # Its episode closes, so if glucose falls again it is spoken again.
        s.pre_armed, s.pre_driving_since, s.pre_escalated = False, None, False
        s.episodes["PULL_OVER"] = Episode()
        s.episodes["RECOVERING"] = Episode(last_true=now)

    # 3. PRE_DRIVE: armed by a seat confirmation or a trip start while low or dropping.
    seat_confirmed = d.role == "driver" and s.role != "driver"
    trip_started = d.in_vehicle and not s.in_vehicle
    pre_context = d.role != "passenger" and (d.role == "driver" or d.in_vehicle)
    if (seat_confirmed or trip_started) and pre_context and glu["PRE_DRIVE"]:
        s.pre_armed = True
    pre_active = s.pre_armed and pre_context and s.held["PRE_DRIVE"]
    if not pre_active:
        s.pre_armed, s.pre_driving_since, s.pre_escalated = False, None, False
    elif d.driving:
        s.pre_driving_since = s.pre_driving_since or now
        if now - s.pre_driving_since >= timedelta(seconds=settings.PRE_DRIVE_ESCALATE_S):
            s.pre_escalated = True
    else:
        s.pre_driving_since = None

    passenger = _passenger(d)
    pull_active = d.driving and (s.held["PULL_OVER"] or s.pre_escalated)
    soon_active = (d.driving and s.held["LOW_SOON"]) or (passenger and (s.held["LOW_SOON"] or s.held["PULL_OVER"]))

    # 4. While recovering: fell again → PULL_OVER; recovered → NONE; otherwise wait.
    if s.recovering:
        if d.driving and glu["PULL_OVER"] and trend is not None and trend < 0:
            s.recovering = False  # fell again: back to PULL_OVER below
        elif d.driving and _moving(d) and glu["PRE_DRIVE"]:
            # Driving on before recovering (still < DRIVE_MIN, or dropping): back to PULL_OVER,
            # spoken again (its episode closed when RECOVERING began).
            s.recovering, s.drove_on = False, True  # latch: stop-go traffic can't flap it back
            s.pre_armed, s.pre_escalated, s.pre_driving_since = True, True, now
            pull_active = True
        else:
            ok = fresh and inp.reading.mgdl >= settings.DRIVE_MIN and trend is not None and trend >= 0
            if new_reading:
                s.recover_ok = s.recover_ok + 1 if ok else 0
            if s.recover_ok >= settings.HYSTERESIS_READINGS:
                s.recovering = False  # recovered: clears to NONE below
            else:
                pull_active = d.driving and s.pre_escalated
                soon_active = False  # we're already telling them to wait

    # 5. Episodes for dedupe (instantaneous conditions, demo time).
    raw = {
        "PULL_OVER": d.driving and (glu["PULL_OVER"] or s.pre_escalated),
        "PRE_DRIVE": s.pre_armed and pre_context and glu["PRE_DRIVE"],
        "LOW_SOON": (d.driving and glu["LOW_SOON"]) or (passenger and (glu["LOW_SOON"] or glu["PULL_OVER"])),
    }
    gap = timedelta(minutes=settings.EPISODE_GAP_MIN)
    for lvl, on in raw.items():
        ep = s.episodes.get(lvl)
        if not on:
            continue
        if ep is None or ep.last_true is None or now - ep.last_true >= gap:
            ep = s.episodes[lvl] = Episode()
        ep.last_true = now

    # 6. Pick the level.
    if pull_active:
        level = "PULL_OVER"
    elif pre_active:
        level = "PRE_DRIVE"
    elif soon_active:
        level = "LOW_SOON"
    elif s.recovering:
        level = "RECOVERING"
    else:
        level = "NONE"
    if level in GLUCOSE_LEVELS and s.recovering:
        s.recovering = False  # a newer warning supersedes the recovery wait

    # 7. Transitions, live text, repeat.
    if level != cur.level:
        if level == "NONE":
            s.alert = Alert()
            s.alert_wall_s, s.drove_on = None, False
            effects.append({"type": "clear", "level": cur.level})
        else:
            effects.append(_raise(level, s, inp, now))
    elif level != "NONE":
        title, line, _ = _texts(level, s, inp, now)
        if (title, line) != (cur.title, cur.line):
            s.alert = s.alert.model_copy(update={"title": title, "line": line})
        ep = s.episodes.setdefault(level, Episode(last_true=now))
        if (
            level == "PULL_OVER"
            and not s.alert.acked
            and not ep.repeated
            and s.alert.since is not None
            and now - s.alert.since >= timedelta(minutes=settings.REPEAT_PULL_OVER_MIN)
            and (
                inp.wall_s is None
                or s.alert_wall_s is None
                or inp.wall_s - s.alert_wall_s >= settings.REPEAT_MIN_WALL_S
            )
        ):
            ep.repeated = True
            s.alert = s.alert.model_copy(update={"id": _next_id(s, level), "speak": SPEAK["PULL_OVER"]})
            effects.append({"type": "repeat", "level": level, "id": s.alert.id, "speak": s.alert.speak})

    s.in_vehicle, s.role = d.in_vehicle, d.role
    if inp.reading is not None:
        s.last_reading_t = inp.reading.t
    return s, effects


def acknowledge(prev: EngineState, alert_id: str | None, now: datetime) -> tuple[EngineState, list[dict]]:
    """Mark the current alert acknowledged. ``alert_id`` must match the current alert
    (an ack for an alert that has since changed is ignored); None acks whatever is shown."""
    a = prev.alert
    if a.level == "NONE" or a.acked or (alert_id and alert_id != a.id):
        return prev, []
    s = copy.deepcopy(prev)
    s.alert = a.model_copy(update={"acked": True})
    return s, [{"type": "ack", "level": a.level, "id": a.id}]
