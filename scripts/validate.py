#!/usr/bin/env python3
"""Validate LinkedAI's active repository shape and checked-in examples."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from contracts import validate_repository  # noqa: E402


def main() -> int:
    errors = validate_repository(ROOT)
    if errors:
        print("LinkedAI validation FAILED")
        for error in errors:
            print(f" - {error}")
        return 1
    print("LinkedAI validation OK")
    print(f"root: {ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
