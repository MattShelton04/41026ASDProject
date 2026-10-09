"""Run `python -m scripts.security` from the repository root."""

from __future__ import annotations

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.security.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
