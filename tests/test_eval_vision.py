"""scripts/eval_vision.py scoring helpers (the CLIP model itself isn't needed here)."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "eval_vision.py"
spec = importlib.util.spec_from_file_location("eval_vision", SCRIPT)
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def probs(driver, passenger, other):
    return {"driver": driver, "passenger": passenger, "other": other}


def test_confusion_matrix_and_accuracies():
    rows = [
        ("driver", probs(0.8, 0.1, 0.1)),
        ("driver", probs(0.3, 0.6, 0.1)),  # mistaken for passenger
        ("passenger", probs(0.2, 0.7, 0.1)),
        ("other", probs(0.1, 0.1, 0.8)),
    ]
    m, acc, binary = ev.confusion(rows)
    assert m["driver"] == {"driver": 1, "passenger": 1, "other": 0}
    assert acc == 0.75 and binary == 0.75
    assert "75.0%" in ev.report(rows)


def test_session_decision_uses_the_seat_tracker():
    assert ev.session_decision([0.95] * 10)[0] == "driver"
    assert ev.session_decision([0.05] * 10)[0] == "passenger"
    assert ev.session_decision([0.5] * 10) == ("undecided", None)


def test_no_frames_exits_with_a_hint(tmp_path, capsys):
    assert ev.main(["--dir", str(tmp_path)]) == 1
    assert "No labelled frames" in capsys.readouterr().out
