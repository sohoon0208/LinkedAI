#!/usr/bin/env python3
"""Safely install LinkedAI Echo Mode as a separate Codex skill."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def default_target() -> Path:
    codex_home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    return Path(codex_home).expanduser() / "skills" / "linkedai-echo-mode"


def install(target: Path) -> tuple[Path, Path | None]:
    target = target.expanduser().resolve(strict=False)
    if target.name != "linkedai-echo-mode":
        raise RuntimeError("target must end with linkedai-echo-mode")
    if target == ROOT or ROOT in target.parents or target in ROOT.parents:
        raise RuntimeError("source and target must not overlap")

    validator = ROOT / "scripts" / "validate.py"
    check = subprocess.run([sys.executable, str(validator)], cwd=ROOT, capture_output=True, text=True)
    if check.returncode:
        raise RuntimeError((check.stdout + check.stderr).strip())

    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists() or target.is_symlink():
        backup_root = target.parent.parent / "skill-backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_root / f"linkedai-echo-mode-{stamp}"
        target.rename(backup)

    stage = target.parent / ".linkedai-echo-mode.stage"
    if stage.exists() or stage.is_symlink():
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage)
        else:
            stage.unlink()
    try:
        shutil.copytree(ROOT, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        stage.rename(target)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        if backup is not None and not target.exists():
            backup.rename(target)
        raise
    return target, backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Install LinkedAI Echo Mode")
    parser.add_argument("--target", type=Path, default=default_target())
    args = parser.parse_args()
    try:
        target, backup = install(args.target)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"LinkedAI Echo Mode install failed: {exc}", file=sys.stderr)
        return 1
    print(f"backup preserved: {backup or 'none (fresh install)'}")
    print(f"installed LinkedAI Echo Mode -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
