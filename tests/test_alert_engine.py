"""Alert engine (plan §5.6, §10). The engine is pure, so these tests drive it over a
reading list on a 30 s demo-time tick, the way the app's tick loop does."""
import copy
from datetime import datetime, timedelta, timezone

import pytest

from backend.alerts.engine import EngineInputs, EngineState, acknowledge, evaluate, minutes_to_low
from backend.cgm.loaders import load_csv
from backend.cgm.source import ReplaySource
from backend.config import settings
from backend.forecast import baseline
from backend.models import CGMReading, DrivingState, Forecast

T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
STEP = timedelta(seconds=30)


def ds(in_vehicle=True, role="unknown"):
    return DrivingState(driving=in_vehicle and role != "passenger", in_vehicle=in_vehicle, role=role, since=T0)


def scenario(name):
    src = ReplaySource(load_csv(settings.SCENARIO_DIR / f"{name}.csv"), T0)
    return src.readings_until(T0 + timedelta(days=1))


def trace(values, start_min=-20, step=5):
    return [CGMReading(t=T0 + timedelta(minutes=start_min + i * step), mgdl=v) for i, v in enumerate(values)]


def minute(t):
    return (t - T0).total_seconds() / 60


def run(readings, driving, end=120, start=0, state=None, on_tick=None):
    """Tick from ``start`` to ``end`` demo-minutes. ``driving`` is a DrivingState or a
    function of the minute. ``on_tick(state, t) -> (state, effects)`` runs after each
    evaluate (e.g. to acknowledge). Returns (state, [(minute, effect), ...])."""
    s = state or EngineState(epoch="test")
    events = []
    t = T0 + timedelta(minutes=start)
    while t <= T0 + timedelta(minutes=end):
        rs = [r for r in readings if r.t <= t]
        d = driving(minute(t)) if callable(driving) else driving
        inp = EngineInputs(rs[-1] if rs else None, baseline.trend(rs, t), baseline.forecast(rs, t), d)
        s, eff = evaluate(s, inp, t)
        if on_tick:
            s, more = on_tick(s, t)
            eff = eff + more
        events += [(minute(t), e) for e in eff]
        t += STEP
    return s, events


def raises(events):
    return [(m, e["level"]) for m, e in events if e["type"] == "raise"]


def ack_pull_over(s, t):
    if s.alert.level == "PULL_OVER" and not s.alert.acked:
        return acknowledge(s, s.alert.id, t)
    return s, []


# ---------------------------------------------------------------- scenarios
def test_falling_while_driving_low_soon_then_pull_over():
    _, ev = run(scenario("falling_while_driving"), ds())
    r = raises(ev)
    assert [lvl for _, lvl in r[:2]] == ["LOW_SOON", "PULL_OVER"]
    # LOW_SOON: the +30 min forecast first drops below 70 at the 50-min reading (102.5).
    # PULL_OVER: at the 60-min reading (80.5, below 90 and falling faster than -2/min).
    assert r[0][0] == pytest.approx(50, abs=5)
    assert r[1][0] == pytest.approx(60, abs=5)
    spoken = [e for _, e in ev if e["type"] == "raise"]
    assert spoken[0]["speak"].startswith("Heads up: you may go low in about")
    assert spoken[1]["speak"].startswith("Your glucose is low. Pull over")


def test_stable_drive_gives_zero_alerts():
    _, ev = run(scenario("stable_drive"), ds())
    assert ev == []


@pytest.mark.parametrize("name", ["falling_while_driving", "low_before_drive", "treated_recovery"])
def test_not_in_car_never_alerts(name):
    _, ev = run(scenario(name), ds(in_vehicle=False))
    assert ev == []


# ---------------------------------------------------------------- confirmed passenger
@pytest.mark.parametrize("name", ["falling_while_driving", "low_before_drive", "treated_recovery"])
def test_confirmed_passenger_gets_gentle_low_soon_never_pull_over(name):
    _, ev = run(scenario(name), ds(role="passenger"))
    levels = {lvl for _, lvl in raises(ev)}
    assert levels == {"LOW_SOON"}  # warned, but never PULL_OVER or PRE_DRIVE
    assert not any(e["type"] == "repeat" for _, e in ev)
    for _, e in ev:
        if e["type"] == "raise" and e["speak"]:
            assert "Treat it when you can" in e["speak"] and "Pull over" not in e["speak"]


def test_passenger_wording_follows_the_glucose():
    seen = []

    def watch(s, t):
        if s.alert.level != "NONE":
            seen.append((s.alert.title, s.alert.line))
        return s, []

    _, ev = run(scenario("falling_while_driving"), ds(role="passenger"), on_tick=watch)
    assert raises(ev)[0] == (pytest.approx(50, abs=5), "LOW_SOON")  # same timing as for a driver
    assert seen[0][0].startswith("LOW IN ~") and seen[0][1] == "Treat when you can"
    assert ("LOW GLUCOSE", "Treat when you can") in seen  # once the reading is below 70
    spoken = [e["speak"] for _, e in ev if e["type"] == "raise" and e["speak"]]
    assert len(spoken) == 1  # the wording changes silently; said once per episode


def test_wrong_passenger_mid_alert_softens_pull_over_instead_of_silencing_it():
    # Unknown seat (treated as driving) until minute 70, then the seat check says passenger.
    def driving(m):
        return ds(role="passenger" if m >= 70 else "unknown")

    s, ev = run(scenario("falling_while_driving"), driving, end=75)
    assert [lvl for _, lvl in raises(ev)] == ["LOW_SOON", "PULL_OVER", "LOW_SOON"]
    assert s.alert.level == "LOW_SOON" and s.alert.title == "LOW GLUCOSE"
    assert not any(e["type"] == "clear" for _, e in ev)  # never silent in between


def test_low_soon_title_counts_down_to_the_forecast_crossing():
    seen = []

    def watch(s, t):
        if s.alert.level == "LOW_SOON":
            seen.append(s.alert.title)
        return s, []

    run(scenario("falling_while_driving"), ds(), end=58, on_tick=watch)
    assert seen and all(t.startswith("LOW IN ~") and t.endswith(" MIN") for t in seen)
    minutes = [int(t.split("~")[1].split()[0]) for t in seen]
    assert all(m % 5 == 0 and m >= 5 for m in minutes)
    assert minutes == sorted(minutes, reverse=True)  # never counts up while falling


# ---------------------------------------------------------------- ack, repeat, dedupe
def test_unacked_pull_over_repeats_audio_once():
    _, ev = run(scenario("falling_while_driving"), ds(), end=100)
    pull_at = next(m for m, lvl in raises(ev) if lvl == "PULL_OVER")
    repeats = [(m, e) for m, e in ev if e["type"] == "repeat"]
    assert len(repeats) == 1
    assert repeats[0][0] - pull_at == pytest.approx(settings.REPEAT_PULL_OVER_MIN, abs=0.5)
    assert repeats[0][1]["speak"]
    ids = [e["id"] for _, e in ev if e["type"] in ("raise", "repeat")]
    assert len(ids) == len(set(ids))  # the repeat is a new id, so the phone speaks it


def test_ack_silences_the_repeat_but_keeps_the_banner():
    s, ev = run(scenario("falling_while_driving"), ds(), end=100, on_tick=ack_pull_over)
    assert not any(e["type"] == "repeat" for _, e in ev)
    assert s.alert.level == "PULL_OVER" and s.alert.acked  # still low and flat: banner stays


def test_ack_needs_the_current_alert_id():
    s, _ = run(scenario("falling_while_driving"), ds(), end=62)
    assert s.alert.level == "PULL_OVER"
    same, eff = acknowledge(s, "some-older-alert", T0)
    assert eff == [] and not same.alert.acked
    acked, eff = acknowledge(s, s.alert.id, T0)
    assert eff and acked.alert.acked and not s.alert.acked  # pure: prev unchanged
    assert acknowledge(EngineState(), None, T0)[1] == []  # nothing to ack


def test_noisy_readings_around_70_do_not_flap():
    values = [72, 71, 73, 72] + [71, 68, 72, 69, 71, 67, 72, 69, 73, 68, 71, 69, 72, 68] * 2
    _, ev = run(trace(values), ds(), end=5 * (len(values) - 5))
    pull_at = next(m for m, lvl in raises(ev) if lvl == "PULL_OVER")
    after = [(m, e) for m, e in ev if m > pull_at and e["type"] in ("raise", "clear")]
    assert after == []  # no flapping once PULL_OVER is up
    spoken = [e for _, e in ev if e["type"] == "raise" and e["level"] == "PULL_OVER" and e["speak"]]
    assert len(spoken) == 1


def test_each_level_is_spoken_once_per_episode():
    # A steady 75 with a forecast that dips below 70 at +30 min → LOW_SOON. During the
    # blips the forecast stays in range, so LOW_SOON drops after 2 readings (hysteresis).
    # One reading a minute; the forecast is given directly so the blips are exact.
    blips = {
        "short": (20, 23),  # condition off for 3 min → same episode → silent when it returns
        "long": (40, 55),  # off for 15 min → new episode → spoken again
    }
    s = EngineState(epoch="test", in_vehicle=True)  # mid-trip: a trip start would arm PRE_DRIVE
    events = []
    t = T0
    while t <= T0 + timedelta(minutes=70):
        m = minute(t)
        r = CGMReading(t=T0 + timedelta(minutes=int(m)), mgdl=75)
        off = any(a <= m < b for a, b in blips.values())
        mean = [80, 82, 84] if off else [74, 72, 68]
        fc = Forecast(t0=r.t, horizons_min=[10, 20, 30], mean=mean, lo=[v - 6 for v in mean], hi=[v + 6 for v in mean])
        s, eff = evaluate(s, EngineInputs(r, 0.0, fc, ds()), t)
        events += [(m, e) for e in eff]
        t += STEP
    low_soon = [(m, e["speak"] is not None) for m, e in events if e["type"] == "raise"]
    assert low_soon == [(0.0, True), (23.0, False), (55.0, True)]


def test_alert_ids_are_unique_across_engine_resets():
    a, ev_a = run(scenario("falling_while_driving"), ds(), end=70, state=EngineState())
    b, ev_b = run(scenario("falling_while_driving"), ds(), end=70, state=EngineState())
    ids_a = {e["id"] for _, e in ev_a if "id" in e}
    ids_b = {e["id"] for _, e in ev_b if "id" in e}
    assert ids_a and ids_b and not ids_a & ids_b  # a rerun of the demo is spoken again


# ---------------------------------------------------------------- pre-drive
def test_pre_drive_from_a_parked_seat_check():
    # Parked (no trip), glasses session at minute 5 confirms the driver's seat.
    def driving(m):
        return ds(in_vehicle=False, role="driver" if m >= 5 else "unknown")

    _, ev = run(scenario("low_before_drive"), driving, end=90)
    assert raises(ev) == [(5.0, "PRE_DRIVE")]
    raise_ev = next(e for _, e in ev if e["type"] == "raise")
    assert raise_ev["speak"].startswith("Before you drive")
    clear_at = next(m for m, e in ev if e["type"] == "clear")
    assert clear_at == pytest.approx(55, abs=5)  # two readings >= 90 (95.0 at 50, 103.3 at 55)


def test_pre_drive_on_trip_start_escalates_after_60s_of_driving():
    flat85 = trace([85] * 40)  # below 90, but not low or falling: no PULL_OVER by itself

    def driving(m):
        return ds(in_vehicle=m >= 10)

    _, ev = run(flat85, driving, end=30)
    r = raises(ev)
    assert [lvl for _, lvl in r] == ["PRE_DRIVE", "PULL_OVER"]
    assert r[0][0] == 10.0
    assert r[1][0] - r[0][0] == pytest.approx(settings.PRE_DRIVE_ESCALATE_S / 60, abs=0.5)


def test_no_pre_drive_for_a_confirmed_passenger():
    flat85 = trace([85] * 40)
    _, ev = run(flat85, lambda m: ds(in_vehicle=m >= 10, role="passenger"), end=30)
    assert ev == []


def test_low_reading_at_trip_start_goes_straight_to_pull_over():
    # PULL_OVER outranks PRE_DRIVE: already low (70.8 and falling) when the trip starts.
    _, ev = run(scenario("low_before_drive"), ds(), end=10)
    assert raises(ev)[0] == (0.0, "PULL_OVER")


# ---------------------------------------------------------------- recovering
def test_recovering_after_acknowledged_pull_over():
    seen = []

    def ack_and_watch(s, t):
        s, eff = ack_pull_over(s, t)
        if s.alert.level == "RECOVERING":
            seen.append(s.alert)
        return s, eff

    _, ev = run(scenario("treated_recovery"), ds(), end=90, on_tick=ack_and_watch)
    levels = [lvl for _, lvl in raises(ev)]
    assert levels == ["LOW_SOON", "PULL_OVER", "RECOVERING"]
    rec_at = next(m for m, lvl in raises(ev) if lvl == "RECOVERING")
    assert rec_at == pytest.approx(45, abs=5)  # first reading with a clear rise after treatment
    a = seen[0]
    assert a.title == "WAIT · RECHECK" and a.until - a.since == timedelta(minutes=settings.RECOVER_WAIT_MIN)
    cleared = next(m for m, e in ev if e["type"] == "clear")
    assert cleared > rec_at
    assert not any(e["type"] == "repeat" for _, e in ev)


def test_unacked_pull_over_clears_without_recovering():
    _, ev = run(scenario("treated_recovery"), ds(), end=90)
    assert "RECOVERING" not in [lvl for _, lvl in raises(ev)]
    assert any(e["type"] == "clear" and e["level"] == "PULL_OVER" for _, e in ev)


def test_falling_again_while_recovering_returns_to_pull_over_and_speaks():
    # Treated (rise), then the rise fails and glucose falls below 70 again.
    values = [100, 92, 84, 76, 68, 60, 56, 62, 70, 76, 74, 68, 62, 56, 52, 50, 50, 50]
    s, ev = run(trace(values), ds(), end=5 * (len(values) - 5), on_tick=ack_pull_over)
    levels = [lvl for _, lvl in raises(ev)]
    i = levels.index("RECOVERING")
    assert "PULL_OVER" in levels[i + 1 :]
    back = next(e for m, e in ev if e["type"] == "raise" and e["level"] == "PULL_OVER" and m > raises(ev)[i][0])
    assert back["speak"]  # a failed treatment is a new warning, not a repeat


# ---------------------------------------------------------------- data quality, purity
def test_stale_reading_raises_nothing_and_a_gap_holds_the_alert():
    low = trace([60] * 5)  # last reading at minute 0
    _, ev = run(low, ds(), start=30, end=40)  # 30+ min later: no data
    assert ev == []
    s, ev = run(low, ds(), start=0, end=60)  # alert raised at 0, then the sensor goes quiet
    assert raises(ev) == [(0.0, "PULL_OVER")]
    assert not any(e["type"] == "clear" for _, e in ev) and s.alert.level == "PULL_OVER"


def test_evaluate_does_not_mutate_its_input():
    s, _ = run(scenario("falling_while_driving"), ds(), end=55)
    before = copy.deepcopy(s)
    rs = scenario("falling_while_driving")
    t = T0 + timedelta(minutes=70)
    now = [r for r in rs if r.t <= t]
    evaluate(s, EngineInputs(now[-1], baseline.trend(now, t), baseline.forecast(now, t), ds()), t)
    assert s == before


def test_minutes_to_low_interpolates_and_rounds_to_5():
    r = CGMReading(t=T0, mgdl=100)
    fc = Forecast(t0=T0, horizons_min=[10, 20, 30], mean=[80, 60, 40], lo=[74, 48, 20], hi=[86, 72, 60])
    assert minutes_to_low(r, fc, T0) == 15  # crosses 70 halfway between +10 and +20
    assert minutes_to_low(r, fc, T0 + timedelta(minutes=4)) == 10  # 11 min left → ~10
    late = T0 + timedelta(minutes=14)
    assert minutes_to_low(r, fc, late) == 5  # never below 5
    no_cross = Forecast(t0=T0, horizons_min=[10, 20, 30], mean=[78, 76, 75], lo=[72, 64, 55], hi=[84, 88, 95])
    assert minutes_to_low(r, no_cross, T0) == settings.LOW_SOON_HORIZON


# ---------------------------------------------------------------- repeat spacing, stopped-car recovery
def _drive_with_wall(readings, wall_per_tick, end=100):
    """Like run(), but with a real-time clock advancing ``wall_per_tick`` s per 30 s demo tick."""
    s, events, t, wall = EngineState(epoch="test"), [], T0, 0.0
    while t <= T0 + timedelta(minutes=end):
        rs = [r for r in readings if r.t <= t]
        inp = EngineInputs(rs[-1] if rs else None, baseline.trend(rs, t), baseline.forecast(rs, t), ds(), wall_s=wall)
        s, eff = evaluate(s, inp, t)
        events += [(wall, e) for e in eff]
        t += STEP
        wall += wall_per_tick
    return events


def test_pull_over_repeat_waits_for_real_time_on_a_fast_demo_clock():
    # 30× demo speed: a 30 s demo tick is 1 s real, so 2 demo-minutes is only 4 s real.
    ev = _drive_with_wall(scenario("falling_while_driving"), wall_per_tick=1.0)
    raised = next(w for w, e in ev if e["type"] == "raise" and e["level"] == "PULL_OVER")
    repeat = next(w for w, e in ev if e["type"] == "repeat")
    assert repeat - raised >= settings.REPEAT_MIN_WALL_S  # not stacked on the first announcement


def test_pull_over_repeat_at_real_speed_is_unchanged():
    # 1× speed: a 30 s demo tick is 30 s real, so 2 demo-minutes already exceeds the minimum.
    ev = _drive_with_wall(scenario("falling_while_driving"), wall_per_tick=30.0)
    raised = next(w for w, e in ev if e["type"] == "raise" and e["level"] == "PULL_OVER")
    repeat = next(w for w, e in ev if e["type"] == "repeat")
    assert repeat - raised == pytest.approx(settings.REPEAT_PULL_OVER_MIN * 60, abs=30)


def test_unacknowledged_pull_over_recovers_when_the_phone_says_stopped():
    stopped = DrivingState(driving=True, in_vehicle=True, speed_kmh=0.0, phone_stale=False, since=T0)
    _, ev = run(scenario("treated_recovery"), stopped, end=90)
    levels = [lvl for _, lvl in raises(ev)]
    assert levels[-1] == "RECOVERING" and "PULL_OVER" in levels  # no ack needed


def test_unacknowledged_pull_over_while_moving_does_not_recover():
    moving = DrivingState(driving=True, in_vehicle=True, speed_kmh=60.0, phone_stale=False, since=T0)
    _, ev = run(scenario("treated_recovery"), moving, end=90)
    assert "RECOVERING" not in [lvl for _, lvl in raises(ev)]
    stale = DrivingState(driving=True, in_vehicle=True, speed_kmh=0.0, phone_stale=True, since=T0)
    _, ev = run(scenario("treated_recovery"), stale, end=90)  # an old speed isn't evidence
    assert "RECOVERING" not in [lvl for _, lvl in raises(ev)]


def _phone(kmh):
    return DrivingState(driving=True, in_vehicle=True, speed_kmh=kmh, phone_stale=False, since=T0)


def test_red_light_while_still_low_keeps_pull_over():
    # Reviewer's case: below 70 but rising, the phone reports 0 km/h for one minute (a red
    # light), then 50 km/h again. Stopping must not swap PULL_OVER for "wait · recheck".
    values = [100, 92, 84, 76, 68, 60, 52, 58, 63, 68, 69, 68, 66, 63, 60, 58, 57]
    _, ev = run(trace(values), lambda m: _phone(0.0 if 25 <= m < 26 else 50.0), end=5 * (len(values) - 5))
    levels = [lvl for _, lvl in raises(ev)]
    assert "RECOVERING" not in levels
    pull_at = next(m for m, lvl in raises(ev) if lvl == "PULL_OVER")
    assert not [e for m, e in ev if m > pull_at and e["type"] == "clear"]  # never cleared while low


def test_driving_on_before_recovering_brings_pull_over_back():
    # Stopped and treated (rising, >= 70) → "wait · recheck"; then drives off at 79.7 (< 90).
    _, ev = run(scenario("treated_recovery"), lambda m: _phone(0.0 if m < 47 else 50.0), end=90)
    r = raises(ev)
    rec_at = next(m for m, lvl in r if lvl == "RECOVERING")
    back = [(m, e) for m, e in ev if m > rec_at and e["type"] == "raise" and e["level"] == "PULL_OVER"]
    assert back and back[0][0] == pytest.approx(47, abs=0.5)
    assert back[0][1]["speak"]  # a new warning, said out loud


def _spoken(ev):
    return [(m, e["level"]) for m, e in ev if e["type"] in ("raise", "repeat") and e.get("speak")]


def test_gps_jitter_around_5_kmh_does_not_flap_or_respeak():
    # Reviewer's case C: speed alternates 3 / 7 km/h every tick after the PULL_OVER.
    jitter = lambda m: _phone(3.0 if int(m * 2) % 2 == 0 else 7.0) if m >= 44 else _phone(50.0)
    _, ev = run(scenario("treated_recovery"), jitter, end=70)
    spoken = [lvl for _, lvl in _spoken(ev)]
    assert spoken.count("RECOVERING") <= 1 and spoken.count("PULL_OVER") <= 2  # raise + one repeat


def test_stop_go_traffic_does_not_flap_or_respeak():
    # Reviewer's case D: 0 / 30 km/h alternating every minute after the PULL_OVER.
    stop_go = lambda m: _phone(0.0 if int(m) % 2 == 0 else 30.0) if m >= 44 else _phone(50.0)
    _, ev = run(scenario("treated_recovery"), stop_go, end=70)
    spoken = [lvl for _, lvl in _spoken(ev)]
    assert spoken.count("RECOVERING") <= 1  # the latch: no second "wait · recheck"
    # First PULL_OVER + its one repeat, then (drove off unacknowledged, still < 90) the returned
    # PULL_OVER + its one repeat. Without the fix this was a spoken flip every minute.
    assert spoken.count("PULL_OVER") <= 4
