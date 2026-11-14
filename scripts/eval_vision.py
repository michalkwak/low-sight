"""Seat-check accuracy on labelled frames: the number for the pitch slide (plan §5.5).

Put frames in data/vision/<label>/ (gitignored), with label one of driver, passenger, other:
    data/vision/driver/*.jpg      parked, from the driver's seat (steering wheel in view)
    data/vision/passenger/*.jpg   from the passenger seat
    data/vision/other/*.jpg       indoors, street, shop ...
About 1 frame/s from phone clips works well, e.g.
    ffmpeg -i driver_seat.mp4 -vf fps=1 data/vision/driver/d_%03d.jpg

    python scripts/eval_vision.py [--dir data/vision]

Prints per-frame accuracy (top prompt group), the confusion matrix, driver-vs-not accuracy
at p_driver > 0.5, and what the seat tracker (EMA + 3 s hold) decides when each folder's
frames are fed in order at 2 fps as if they were one glasses session.
Needs the vision dependencies: pip install torch open_clip_torch pillow
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import ROOT  # noqa: E402
from backend.vision.clip_detector import PROMPTS, get_detector, seat_score  # noqa: E402
from backend.vision.driving_state import SeatTracker  # noqa: E402

LABELS = list(PROMPTS)  # driver, passenger, other
EXTS = {".jpg", ".jpeg", ".png"}
FPS = 2


def confusion(rows: list[tuple[str, dict[str, float]]]):
    """rows = [(true label, {group: probability})] → (matrix[true][pred], accuracy, driver-vs-not accuracy)."""
    m = {t: dict.fromkeys(LABELS, 0) for t in LABELS}
    for label, probs in rows:
        m[label][max(probs, key=probs.get)] += 1
    n = len(rows)
    if not n:
        return m, 0.0, 0.0
    acc = sum(m[lbl][lbl] for lbl in LABELS) / n
    binary = sum((probs["driver"] > 0.5) == (label == "driver") for label, probs in rows) / n
    return m, acc, binary


def session_decision(scores: list[float]) -> tuple[str, float | None]:
    """Feed seat scores to a fresh SeatTracker at FPS; return (decision, seconds) or ("undecided", None)."""
    tr = SeatTracker()
    for i, p in enumerate(scores):
        seat = tr.update(p, i / FPS)
        if seat:
            return seat, i / FPS
    return "undecided", None


def report(rows: list[tuple[str, dict[str, float]]]) -> str:
    m, acc, binary = confusion(rows)
    counts = {lbl: sum(1 for label, _ in rows if label == lbl) for lbl in LABELS}
    lines = [
        f"{len(rows)} frames (" + ", ".join(f"{lbl} {counts[lbl]}" for lbl in LABELS) + ")",
        f"Accuracy (top group):           {acc:.1%}",
        f"Driver vs not (p_driver > 0.5): {binary:.1%}",
        "",
        "true \\ pred " + "".join(f"{p:>11}" for p in LABELS),
    ]
    lines += [f"{t:<12}" + "".join(f"{m[t][p]:>11}" for p in LABELS) for t in LABELS]
    lines += ["", "As one 2 fps session per folder (EMA + hold):"]
    for lbl in LABELS:
        ps = [seat_score(probs) for label, probs in rows if label == lbl]  # what the app feeds the tracker
        if ps:
            seat, secs = session_decision(ps)
            lines.append(f"  {lbl:<10} → {seat}" + (f" after {secs:.1f} s" if secs is not None else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, default=ROOT / "data" / "vision", help="folder with driver/ passenger/ other/")
    args = ap.parse_args(argv)
    files = [
        (label, p)
        for label in LABELS
        for p in sorted((args.dir / label).glob("*"))
        if p.suffix.lower() in EXTS
    ]
    if not files:
        print(f"No labelled frames found under {args.dir}/{{{','.join(LABELS)}}}/. See the docstring for the layout.")
        return 1
    detector, why = get_detector()
    if detector is None:
        print(why)
        return 1
    from PIL import Image  # noqa: PLC0415 — installed with the vision dependencies

    rows = []
    for label, path in files:
        with Image.open(path) as im:
            rows.append((label, detector.probs(im)))
    print(report(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
