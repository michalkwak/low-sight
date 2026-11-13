"""Write synthetic demo scenarios to data/scenarios/*.csv."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.cgm import synthetic  # noqa: E402
from backend.config import settings  # noqa: E402


def main() -> None:
    settings.SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in synthetic.generate_all().items():
        path = settings.SCENARIO_DIR / f"{name}.csv"
        df.to_csv(path, index=False)
        low = df[df.mgdl < settings.LOW]
        first = f"first <{settings.LOW:.0f} at {low.minute.iloc[0]} min" if len(low) else "no low"
        print(f"{path.relative_to(settings.SCENARIO_DIR.parent.parent)}: {len(df)} rows, {first}")


if __name__ == "__main__":
    main()
