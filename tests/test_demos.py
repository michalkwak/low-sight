"""Per-visitor demos: each simulator visitor gets a private demo by code, so people trying it
at the same time don't drive each other's demo. No code (glasses, old links) = the shared demo."""
import time

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.app import app, demos, rt
from backend.config import settings


@pytest.fixture(autouse=True)
def clean_demos():
    demos.rooms.clear()
    yield
    demos.rooms.clear()


def new_code(c):
    r = c.post("/api/demos").json()
    assert r["private"] is True and r["reason"] is None and len(r["code"]) == 4
    return r["code"]


def test_two_visitors_have_independent_demos():
    with TestClient(app) as c:
        a, b = new_code(c), new_code(c)
        assert a != b
        sa = c.post(f"/api/control?s={a}", json={"scenario": "stable_drive", "force_driving": "on", "pause": True}).json()
        sb = c.post(f"/api/control?s={b}", json={"scenario": "falling_while_driving", "force_driving": "off", "pause": True}).json()
        assert sa["scenario"] == "stable_drive" and sb["scenario"] == "falling_while_driving"
        # Each stays put when the other changes, and the shared demo is untouched.
        assert c.get(f"/api/state?s={a}").json()["scenario"] == "stable_drive"
        assert c.get(f"/api/state?s={b}").json()["driving"]["in_vehicle"] is False
        assert c.get(f"/api/state?s={a}").json()["driving"]["in_vehicle"] is True
        assert c.get("/api/state").json()["scenario"] == rt.scenario


def test_sockets_phone_and_seat_follow_the_code():
    with TestClient(app) as c:
        a, b = new_code(c), new_code(c)
        c.post(f"/api/control?s={a}", json={"scenario": "low_before_drive", "force_driving": "off", "pause": True})
        with c.websocket_connect(f"/ws/state?s={a}") as ws:
            ws.receive_json()
            ws.send_json({"type": "seat", "role": "driver"})
            for _ in range(20):
                s = ws.receive_json()
                if s["driving"]["role"] == "driver":
                    break
            assert s["driving"]["role"] == "driver"
        assert c.get(f"/api/state?s={b}").json()["driving"]["role"] == "unknown"  # b didn't hear it
        assert c.get("/api/state").json()["driving"]["role"] != "driver" or rt.ctx.force_role == "driver"
        d = c.post(f"/api/phone?s={b}", json={"speed_kmh": 0, "car_connected": True}).json()
        assert d["in_vehicle"] is True
        assert c.get(f"/api/state?s={a}").json()["driving"]["in_vehicle"] is False


def test_no_code_or_a_bad_code_is_the_shared_demo():
    with TestClient(app) as c:
        assert demos.get(None) is demos.main
        assert demos.get("not-a-code") is demos.main
        assert demos.get("O0I1") is demos.main  # letters codes never use
        assert c.get("/api/state?s=nope").json()["scenario"] == rt.scenario


def test_unknown_valid_code_is_recreated_by_the_live_page_after_a_restart():
    with TestClient(app) as c:
        assert demos.get("K7F2") is None  # not created by a lookup
        assert c.get("/api/state?s=K7F2").status_code == 404  # a plain request can't create demos
        with c.websocket_connect("/ws/state?s=k7f2") as ws:  # the simulator's live socket can
            assert ws.receive_json()["demo"] == "K7F2"
        assert "K7F2" in demos.rooms


def test_a_valid_code_never_drives_the_shared_demo(monkeypatch):
    """Reviewer's repro: with the server full, POST /api/control?s=ZZZZ used to change main."""
    with TestClient(app) as c:
        before = rt.clock.speed
        monkeypatch.setattr(settings, "MAX_DEMOS", 0)  # full
        assert c.post("/api/control?s=ZZZZ", json={"speed": 7}).status_code == 404
        assert c.post("/api/phone?s=ZZZZ", json={"speed_kmh": 50, "car_connected": True}).status_code == 404
        assert rt.clock.speed == before and rt.ctx.vehicle.last is None or rt.ctx.vehicle.last.speed_kmh != 50
        with c.websocket_connect("/ws/state?s=ZZZZ") as ws:
            with pytest.raises(Exception):
                ws.receive_json()  # closed with 1013 (busy), never served main
        assert "ZZZZ" not in demos.rooms


def test_off_switch_and_busy(monkeypatch):
    with TestClient(app) as c:
        monkeypatch.setattr(settings, "PER_VISITOR_DEMOS", False)
        assert c.post("/api/demos").json() == {"code": "main", "private": False, "reason": "off"}
        assert demos.get("K7F2") is demos.main  # switched off: everything is the shared demo
        monkeypatch.setattr(settings, "PER_VISITOR_DEMOS", True)
        monkeypatch.setattr(settings, "MAX_ACTIVE_DEMOS", 1)
        first, second = new_code(c), new_code(c)  # creating is fine while nothing is open
        with c.websocket_connect(f"/ws/state?s={first}") as ws:  # one demo now open
            assert ws.receive_json()["demo"] == first
            r = c.post("/api/demos").json()
            assert r["private"] is False and r["reason"] == "busy"
            with c.websocket_connect(f"/ws/state?s={second}") as ws2:  # opening a second is refused
                with pytest.raises(Exception):
                    ws2.receive_json()
            with c.websocket_connect(f"/ws/state?s={first}") as ws3:  # a second tab on an open demo is fine
                assert ws3.receive_json()["demo"] == first


def test_only_open_demos_are_updated_and_idle_ones_expire(monkeypatch):
    with TestClient(app) as c:
        code = new_code(c)
        d = demos.rooms[code]
        assert d not in demos.ticking()  # nobody watching: no CPU spent on it
        with c.websocket_connect(f"/ws/state?s={code}") as ws:
            ws.receive_json()
            assert d in demos.ticking()
        monkeypatch.setattr(settings, "DEMO_IDLE_MIN", 0.0)
        d.last_seen = time.monotonic() - 1
        demos.prune()
        assert code not in demos.rooms


def test_health_reports_demos():
    with TestClient(app) as c:
        new_code(c)
        h = c.get("/api/health").json()
        assert h["per_visitor_demos"] is True and h["demos"] == 1 and "active_demos" in h
        assert app_module.MAIN == "main"


def test_a_stalled_client_is_dropped_and_closed_so_it_reconnects():
    import asyncio

    from backend.hub import Hub

    class Stalled:
        closed_with = None
        async def send_text(self, text):
            await asyncio.sleep(10)  # never finishes: stops reading
        async def close(self, code=1000):
            Stalled.closed_with = code

    class Fine:
        got = []
        async def send_text(self, text):
            Fine.got.append(text)

    async def run():
        hub = Hub()
        hub._clients.update({Stalled(), Fine()})
        await hub.broadcast("state")
        await asyncio.sleep(0.05)  # let the close task run
        return hub.count

    assert asyncio.run(run()) == 1  # the stalled one is gone
    assert Fine.got == ["state"] and Stalled.closed_with == 1011
