"""Load the clearly labelled SYNTHETIC demonstration data into the configured database.

Usage (from the project folder, with the virtual environment active):
    python scripts/seed_demo_data.py

Demo records are marked source_type='demo' and can be removed from Settings in the app.
This is never run automatically.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from textile_resource_intelligence.config import AppSettings  # noqa: E402
from textile_resource_intelligence.exceptions import ValidationFailed  # noqa: E402
from textile_resource_intelligence.services.container import build_container  # noqa: E402


def main() -> int:
    settings = AppSettings.from_env()
    container = build_container(settings)
    try:
        resource, production = container.demo.load()
    except ValidationFailed as exc:
        print(f"Nothing loaded: {exc}")
        return 1
    print(f"Loaded {resource} synthetic resource and {production} synthetic production records into {settings.database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
