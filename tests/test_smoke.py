"""End-to-end smoke test: app boots, health OK, HUD served, state streams."""
from fastapi.testclient import TestClient

from backend.app import app


def test_health_hud_and_state_ws():
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ok"] is True
        hud = c.get("/hud/")
        assert hud.status_code == 200 and "LowSight" in hud.text
        assert "x-frame-options" not in {k.lower() for k in hud.headers}
        with c.websocket_connect("/ws/state") as ws:
            s = ws.receive_json()
            assert s["reading"] is not None
            assert s["forecast"] is not None
            assert s["units"] in ("mmol", "mgdl")


def test_control_force_driving():
    with TestClient(app) as c:
        s = c.post("/api/control", json={"force_driving": "on"}).json()
        assert s["driving"]["driving"] is True and s["driving"]["source"] == "forced"
        c.post("/api/control", json={"force_driving": "auto"})


def test_phone_signal_and_seat_frames():
    with TestClient(app) as c:
        c.post("/api/control", json={"reset": True})
        d = c.post("/api/phone", json={"speed_kmh": 0, "car_connected": True}).json()
        assert d["in_vehicle"] is True and d["role"] == "unknown" and d["driving"] is True
        assert c.get("/phone/").status_code == 200
        with c.websocket_connect("/ws/frames") as ws:
            for _ in range(10):
                ws.send_text('{"p_driver": 0.95}')
                r = ws.receive_json()
        # Frames arrive faster than real time here, so the 3 s hold may not have elapsed;
        # the smoothed score must still be high.
        assert r["p_driver"] > 0.9
        c.post("/api/control", json={"reset": True})
