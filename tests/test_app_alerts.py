"""App wiring: control panel → alert engine → /ws/state, acks, "spoken" reports, and the
seat-check frame socket. The CLIP detector is stubbed so these run without torch."""
from fastapi.testclient import TestClient

from backend.app import app, rt
from backend.config import settings
from backend.vision import clip_detector


def start(c, **extra):
    """falling_while_driving, phone override "in car", clock paused at minute 0."""
    body = {"scenario": "falling_while_driving", "force_driving": "on", "force_role": "auto", "pause": True}
    return c.post("/api/control", json=body | extra).json()


def restore(c):
    c.post(
        "/api/control",
        json={"scenario": settings.SCENARIO, "force_driving": "auto", "force_role": "auto", "pause": False, "reset": True},
    )


def receive_until(ws, pred, attempts=20):
    for _ in range(attempts):
        s = ws.receive_json()
        if pred(s):
            return s
    raise AssertionError("state never matched")


def test_forced_in_car_on_falling_gives_low_soon_then_pull_over():
    with TestClient(app) as c:
        try:
            start(c)
            s = c.post("/api/control", json={"seek_min": 50}).json()
            assert s["alert"]["level"] == "LOW_SOON" and s["alert"]["speak"] and s["alert"]["id"]
            s = c.post("/api/control", json={"seek_min": 10}).json()
            assert s["alert"]["level"] == "PULL_OVER" and s["alert"]["title"] == "PULL OVER"
            assert s["force_driving"] == "on"
        finally:
            restore(c)


def test_hud_enter_acks_and_phone_reports_spoken():
    with TestClient(app) as c:
        try:
            start(c, seek_min=60)
            with c.websocket_connect("/ws/state") as ws:
                a = ws.receive_json()["alert"]
                assert a["level"] == "PULL_OVER" and not a["acked"] and not a["spoken"]
                ws.send_json({"type": "spoken", "id": a["id"]})
                receive_until(ws, lambda s: s["alert"]["spoken"])
                ws.send_text("not json")  # ignored; the socket stays up
                ws.send_json({"type": "ack", "id": "an-older-alert"})  # ignored: not what's shown
                ws.send_json({"type": "ack", "id": a["id"]})
                s = receive_until(ws, lambda s: s["alert"]["acked"])
                assert s["alert"]["id"] == a["id"] and s["alert"]["level"] == "PULL_OVER"
        finally:
            restore(c)


def test_control_panel_ack_and_bad_scenario():
    with TestClient(app) as c:
        try:
            s = start(c, seek_min=60)
            assert s["alert"]["level"] == "PULL_OVER" and not s["alert"]["acked"]
            assert c.post("/api/control", json={"ack": True}).json()["alert"]["acked"] is True
            assert c.post("/api/control", json={"scenario": "nope"}).status_code == 400
        finally:
            restore(c)


def test_hud_has_glasses_metadata():
    with TestClient(app) as c:
        html = c.get("/hud/").text
        assert '<meta name="mrbd-web-app-capable" content="yes">' in html
        assert '<meta name="description"' in html
        assert "width=device-width" in html
        assert c.get("/hud/favicon.svg").status_code == 200
        assert c.get("/camera/").status_code == 200


def test_frames_go_to_the_detector_and_decide_the_seat(monkeypatch):
    class FakeDetector:
        def frame_probs(self, jpeg: bytes) -> dict[str, float]:
            return {"driver": 0.95, "passenger": 0.05, "other": 0.0}

    monkeypatch.setattr(clip_detector, "get_detector", lambda: (FakeDetector(), None))
    monkeypatch.setattr(rt.ctx.seat, "hold_s", 0.0)  # decide on the first confident frame
    with TestClient(app) as c:
        try:
            c.post("/api/control", json={"reset": True})
            with c.websocket_connect("/ws/frames") as ws:
                ws.send_bytes(b"\xff\xd8 a jpeg")
                r = ws.receive_json()
                assert r["p_frame"] == 0.95 and r["seat"] == "driver" and r["role"] == "driver"
                assert c.get("/api/state").json()["driving"]["seat_checking"] is True
        finally:
            c.post("/api/control", json={"reset": True})


def test_frames_without_the_vision_model_say_why(monkeypatch):
    monkeypatch.setattr(clip_detector, "get_detector", lambda: (None, "vision model not installed (torch)"))
    with TestClient(app) as c, c.websocket_connect("/ws/frames") as ws:
        ws.send_bytes(b"\xff\xd8 a jpeg")
        r = ws.receive_json()
        assert "not installed" in r["error"] and r["seat"] is None
        ws.send_text("garbage")
        assert "expected" in ws.receive_json()["error"]
