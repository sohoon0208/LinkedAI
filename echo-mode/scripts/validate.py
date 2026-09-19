#!/usr/bin/env python3
"""Validate the small Echo Mode skill package without network access."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    Path("SKILL.md"),
    Path("agents/openai.yaml"),
    Path("references/workflow.md"),
    Path("schemas/luna-verification.schema.json"),
)


def main() -> int:
    errors = [f"missing: {path}" for path in REQUIRED if not (ROOT / path).is_file()]
    schema = ROOT / "schemas/luna-verification.schema.json"
    if schema.is_file():
        try:
            value = json.loads(schema.read_text(encoding="utf-8"))
            if value.get("type") != "object":
                errors.append("verification schema must be an object schema")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"verification schema is invalid: {exc}")
    if errors:
        print("LinkedAI Echo Mode validation FAILED")
        for error in errors:
            print(f" - {error}")
        return 1
    print("LinkedAI Echo Mode validation OK")
    print(f"root: {ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
