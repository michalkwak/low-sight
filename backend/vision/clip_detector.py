"""Zero-shot seat classifier: is this first-person frame from the driver's seat?

CLIP (open_clip ``CLIP_MODEL`` / ``CLIP_PRETRAINED``, default ViT-B-32 laion2b_s34b_b79k)
scores each frame against three prompt groups (plan §5.5). The text embeddings are
averaged per group, and ``probs = softmax(100 · cos(image, group))``. ``seat_score(probs)``
turns that into the per-frame score SeatTracker (driving_state.py) smooths into a decision.

torch, open_clip_torch and pillow are optional (large downloads, plus ~600 MB of
weights on first use). Without them ``get_detector()`` returns ``(None, reason)``
and the app keeps working: use the control-panel seat override, or send
``{"p_driver": …}`` test messages (the camera page's "simulate" buttons).
"""
import io
import logging
import threading

from backend.config import settings

log = logging.getLogger("lowsight.vision")

# Deviates from plan §5.5 on purpose: the plan's passenger prompt said "...with no steering
# wheel in front", but CLIP can't do negation, so "steering wheel" pulled real driver views
# toward "passenger". On 24 public photos (4 genuine driver views), the plan's prompts put
# 2/4 driver views over ENTER_P (one scored 0.15); these put 4/4 over it (0.74-0.93), with no
# room above 0.05. One side view of a bus driver's seat scored 0.70. Measure on your own
# footage with scripts/eval_vision.py before trusting either number.
PROMPTS: dict[str, list[str]] = {
    "driver": [
        "a first-person view from the driver's seat of a car, steering wheel in front",
        "POV of a person driving a car, hands on the steering wheel",
        "car dashboard and steering wheel seen by the driver",
        "a steering wheel and instrument cluster seen from the driver's seat",
    ],
    "passenger": [
        "first-person view from the passenger seat of a car",
        "view of a car dashboard and glovebox from the front passenger seat",
    ],
    "other": [
        "a person walking on a street, first-person view",
        "indoors in a room",
        "an office desk with a laptop",
        "a kitchen",
        "a supermarket aisle",
    ],
}
INPUT_PX = 224  # CLIP input size; JPEGs are decoded straight at about this size


def seat_score(probs: dict[str, float]) -> float:
    """What a frame says about the seat, for SeatTracker: 1 = driver's seat, 0 = passenger
    seat, 0.5 = can't tell. For a car interior this equals p(driver); a frame that isn't a
    car interior ("other") pulls toward 0.5. Feeding raw p(driver) instead would let a few
    seconds of kitchen "confirm passenger", and that silences driving alerts for the trip."""
    return 0.5 + 0.5 * (probs["driver"] - probs["passenger"])


class ClipSeatDetector:
    def __init__(self, model_name: str | None = None, pretrained: str | None = None, device: str = "cpu"):
        import open_clip  # noqa: PLC0415 — optional dependency
        import torch  # noqa: PLC0415

        self._torch = torch
        self.device = device
        name = model_name or settings.CLIP_MODEL
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            name, pretrained=pretrained or settings.CLIP_PRETRAINED, device=device
        )
        self.model.eval()
        tokenizer = open_clip.get_tokenizer(name)
        self.groups = list(PROMPTS)
        with torch.no_grad():
            embs = []
            for g in self.groups:
                t = self.model.encode_text(tokenizer(PROMPTS[g]).to(device))
                t = t / t.norm(dim=-1, keepdim=True)
                mean = t.mean(dim=0)
                embs.append(mean / mean.norm())
            self.text = torch.stack(embs)  # (groups, dim)

    def probs(self, image) -> dict[str, float]:
        """Group probabilities for one PIL image."""
        torch = self._torch
        x = self.preprocess(image.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.no_grad():
            f = self.model.encode_image(x)
            f = f / f.norm(dim=-1, keepdim=True)
            p = (100.0 * f @ self.text.T).softmax(dim=-1)[0]
        return {g: float(v) for g, v in zip(self.groups, p)}

    def frame_probs(self, jpeg: bytes) -> dict[str, float]:
        """Group probabilities for one JPEG frame."""
        from PIL import Image  # noqa: PLC0415

        with Image.open(io.BytesIO(jpeg)) as im:
            im.draft("RGB", (INPUT_PX, INPUT_PX))  # let the JPEG decoder downscale (fast)
            return self.probs(im)


_lock = threading.Lock()
_detector: ClipSeatDetector | None = None
_missing: str | None = None  # set once if the optional dependencies aren't installed


def get_detector() -> tuple[ClipSeatDetector | None, str | None]:
    """The shared detector, loaded on first use (slow: call it from a worker thread).
    Returns ``(detector, None)`` or ``(None, reason)``."""
    global _detector, _missing
    with _lock:
        if _detector is not None or _missing is not None:
            return _detector, _missing
        try:
            _detector = ClipSeatDetector()
            log.info("CLIP seat detector ready (%s / %s)", settings.CLIP_MODEL, settings.CLIP_PRETRAINED)
            return _detector, None
        except ImportError as e:
            _missing = f"vision model not installed ({e.name}): pip install torch open_clip_torch pillow"
            log.warning(_missing)
            return None, _missing
        except Exception as e:  # e.g. weights download failed: allow a retry on a later frame
            log.exception("CLIP seat detector failed to load")
            return None, f"vision model failed to load: {e}"
