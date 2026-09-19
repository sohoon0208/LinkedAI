#!/usr/bin/env python3
"""Install LinkedAI as a self-contained Codex skill.

The installer deliberately uses only the Python standard library. It builds
and validates a sibling staging directory, then swaps it into place with
recoverable backups. Existing target data that is not part of the package is
carried into the staged result unchanged.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable


PACKAGE_ENTRIES = (
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "Makefile",
    "requirements.txt",
    "README.md",
    "SKILL.md",
    "agents",
    "docs",
    "prompts",
    "references",
    "references/runtime-contracts.md",
    "references/usage-and-evaluation.md",
    "schemas",
    "scripts",
    "scripts/contracts.py",
    "scripts/usage.py",
    "tests",
)
PACKAGE_DIRECTORIES = frozenset(
    {
        "agents",
        "docs",
        "prompts",
        "references",
        "schemas",
        "scripts",
        "tests",
    }
)

# These names are deliberately broader than the current repository's ignored
# directories. They prevent a local runtime/cache tree from becoming part of a
# skill install even when it appears below a package directory.
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "archive",
        "cache",
        "caches",
        "environment",
        "environments",
        "log",
        "logs",
        "output",
        "outputs",
        "profile",
        "profiles",
        "session",
        "sessions",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "linkedai-output",
    }
)
EXCLUDED_FILE_NAMES = frozenset({".ds_store"})
EXCLUDED_FILE_SUFFIXES = (".profraw",)

# Older AG artifacts are retained only under archive/antigravity. Cleaning
# these exact paths from an existing installed target avoids leaving a stale
# external-agent surface behind while still preserving unrelated target data.
LEGACY_AG_RELATIVE_PATHS = (
    Path("scripts/linkedai-broker.py"),
    Path("prompts/ag-preplanner.md"),
    Path("tests/test_broker.py"),
    Path("tests/fixtures/ag-preplan-smoke-packet.txt"),
)

# Echo Mode is a separately installed skill. Older main-skill installs bundled
# it below `linkedai/echo-mode`, which made Codex discover the same skill twice.
# Remove that exact legacy subtree from the next staged main install; the
# installer preserves the previous target in a recoverable backup first.
LEGACY_NESTED_SKILL_PATHS = (Path("echo-mode"),)


class InstallError(RuntimeError):
    """A safe, user-actionable installer failure."""


@dataclass(frozen=True)
class InstallResult:
    target: Path
    backup: Path | None = None
    no_op: bool = False


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _is_within(path: Path, parent: Path) -> bool:
    """Return whether path is parent or a descendant of parent."""

    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _same_directory(first: Path, second: Path) -> bool:
    """Catch filesystem aliases such as case-folded or bind-mounted paths."""

    try:
        return first.is_dir() and second.is_dir() and os.path.samefile(first, second)
    except OSError:
        return False


def _normalized_absolute(path: Path) -> Path:
    if not path.is_absolute():
        path = Path.cwd() / path
    # normpath removes lexical '..' components without dereferencing anything.
    return Path(os.path.normpath(os.fspath(path)))


def _excluded_relative(relative: Path, path: Path) -> bool:
    parts = relative.parts
    if any(part.lower() in EXCLUDED_DIRECTORY_NAMES for part in parts):
        return True
    if path.name.lower() in EXCLUDED_FILE_NAMES:
        return True
    if path.name.endswith(EXCLUDED_FILE_SUFFIXES):
        return True
    if relative in LEGACY_AG_RELATIVE_PATHS:
        return True
    if relative.parent == Path("schemas") and relative.name.startswith("ag-preplan"):
        return True
    return False


def _validate_symlink(path: Path, source: Path, relative: Path) -> None:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise InstallError(f"source symlink is dangling or unreadable: {relative}") from exc
    if not _is_within(resolved, source):
        raise InstallError(
            f"source symlink escapes the package: {relative} -> {os.readlink(path)}"
        )


def _validate_tree(path: Path, source: Path, relative: Path) -> None:
    if path.is_symlink():
        _validate_symlink(path, source, relative)
        return
    if path.is_dir():
        try:
            children = sorted(path.iterdir(), key=lambda child: child.name)
        except OSError as exc:
            raise InstallError(f"cannot read source directory: {relative}") from exc
        for child in children:
            child_relative = relative / child.name
            if _excluded_relative(child_relative, child):
                continue
            _validate_tree(child, source, child_relative)
        return
    if path.is_file():
        return
    raise InstallError(f"unsupported source entry: {relative}")


def validate_package(root: Path) -> None:
    """Validate the explicit package manifest and included source tree."""

    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise InstallError(f"source/stage directory is unavailable: {root}") from exc
    if not root.is_dir():
        raise InstallError(f"source/stage is not a directory: {root}")

    for relative_text in PACKAGE_ENTRIES:
        relative = Path(relative_text)
        entry = root / relative
        if not _lexists(entry):
            raise InstallError(f"source/stage is missing required package entry: {relative}")
        if relative_text in PACKAGE_DIRECTORIES:
            if entry.is_symlink() or not entry.is_dir():
                raise InstallError(f"package entry must be a real directory: {relative}")
        elif entry.is_symlink() or not entry.is_file():
            raise InstallError(f"package entry must be a regular file: {relative}")
        _validate_tree(entry, root, relative)


def _copy_existing_entry(source: Path, destination: Path) -> None:
    """Copy an existing target entry without following symlinks."""

    if source.is_symlink():
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.readlink(source), destination)
        return
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            _copy_existing_entry(child, destination / child.name)
        try:
            shutil.copystat(source, destination, follow_symlinks=False)
        except OSError:
            pass
        return
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)
        return
    raise InstallError(f"cannot preserve unsupported target entry: {source}")


def _remove_path(path: Path) -> None:
    """Remove one exact staged path, never following a symlink."""

    if not _lexists(path):
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _copy_source_symlink(
    source: Path, destination: Path, package_root: Path, stage: Path
) -> None:
    resolved = source.resolve(strict=True)
    if not _is_within(resolved, package_root):
        raise InstallError(f"source symlink escapes the package: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    _remove_path(destination)
    link_target = os.readlink(source)
    if os.path.isabs(link_target):
        relative_target = resolved.relative_to(package_root)
        mapped = stage / relative_target
        link_target = os.path.relpath(mapped, start=destination.parent)
    os.symlink(link_target, destination)


def _copy_source_entry(package_root: Path, stage: Path, relative: Path) -> None:
    source = package_root / relative
    destination = stage / relative
    if _excluded_relative(relative, source):
        return
    if source.is_symlink():
        _copy_source_symlink(source, destination, package_root, stage)
        return
    if source.is_dir():
        if destination.is_symlink() or destination.is_file():
            _remove_path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            child_relative = relative / child.name
            if _excluded_relative(child_relative, child):
                continue
            _copy_source_entry(package_root, stage, child_relative)
        try:
            shutil.copystat(source, destination, follow_symlinks=False)
        except OSError:
            pass
        return
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        _remove_path(destination)
        shutil.copy2(source, destination, follow_symlinks=False)
        return
    raise InstallError(f"unsupported source entry: {relative}")


def _clean_legacy_ag(stage: Path) -> None:
    for relative in LEGACY_AG_RELATIVE_PATHS:
        _remove_path(stage / relative)
    schemas = stage / "schemas"
    if schemas.is_dir() and not schemas.is_symlink():
        for path in schemas.glob("ag-preplan*.schema.json"):
            _remove_path(path)


def _clean_legacy_nested_skills(stage: Path) -> None:
    for relative in LEGACY_NESTED_SKILL_PATHS:
        _remove_path(stage / relative)


def _clean_staged_exclusions(root: Path) -> None:
    """Drop excluded runtime trees from the preserved copy of an old target."""

    for child in sorted(root.iterdir(), key=lambda item: item.name):
        relative = Path(child.name)
        if _excluded_relative(relative, child):
            _remove_path(child)
            continue
        if child.is_dir() and not child.is_symlink():
            _clean_staged_exclusions(child)


def _run_validator(root: Path) -> None:
    validator = root / "scripts" / "validate.py"
    if not validator.is_file() or validator.is_symlink():
        raise InstallError(f"validation script is missing or unsafe: {validator}")
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (os.fspath(root), existing_pythonpath) if part
    )
    try:
        result = subprocess.run(
            [sys.executable, str(validator)],
            cwd=str(root),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError(f"could not run package validation: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        if len(detail) > 4_000:
            detail = detail[-4_000:]
        raise InstallError(
            f"package validation failed for {root} (exit {result.returncode})"
            + (f":\n{detail}" if detail else "")
        )


def _check_dependencies() -> None:
    if sys.version_info < (3, 9):
        version = ".".join(str(part) for part in sys.version_info[:3])
        raise InstallError(f"Python 3.9 or newer is required (found {version})")
    # All installer operations intentionally use stdlib modules already loaded
    # above. This check documents the no-download dependency boundary.
    if not callable(getattr(shutil, "copy2", None)) or not callable(
        getattr(subprocess, "run", None)
    ):
        raise InstallError("Python standard-library file and process support is unavailable")


def _default_target() -> Path:
    codex_home = os.environ.get("CODEX_HOME") or os.fspath(Path.home() / ".codex")
    return Path(codex_home).expanduser() / "skills" / "linkedai"


def _validate_target(source: Path, requested: Path) -> Path:
    requested = _normalized_absolute(requested.expanduser())
    try:
        resolved = requested.resolve(strict=False)
    except OSError as exc:
        raise InstallError(f"cannot resolve target: {requested}") from exc

    # `/tmp` and `/var` are symlink aliases on macOS. Allow canonicalization of
    # those (and other parent components), but never treat a symlink at the
    # destination itself as a writable directory.
    same_source = resolved == source or _same_directory(requested, source)
    if same_source:
        if not source.is_dir():
            raise InstallError(f"source/stage is not a directory: {source}")
        return source

    if requested.name.lower() != "linkedai":
        raise InstallError("target must end with a directory named 'linkedai'")
    if resolved.parent == Path(resolved.anchor):
        raise InstallError(f"target is too broad or dangerous: {requested}")

    if requested.is_symlink() and not same_source:
        raise InstallError(f"target must not be a symlink: {requested}")

    if _is_within(resolved, source) or _is_within(source, resolved):
        raise InstallError("target and source overlap; an ancestor/descendant target is unsafe")

    if _lexists(requested):
        if requested.is_symlink():
            raise InstallError(f"target must not be a symlink: {requested}")
        if not requested.is_dir():
            raise InstallError(f"target exists but is not a directory: {requested}")
    return resolved


def _backup_parent(target: Path) -> Path:
    """Return a backup directory outside an active Codex skills directory."""

    if target.parent.name.lower() == "skills":
        return target.parent.parent / "skill-backups"
    return target.parent / "skill-backups"


def _ensure_backup_parent(target: Path) -> Path:
    parent = _backup_parent(target)
    if _lexists(parent):
        if parent.is_symlink() or not parent.is_dir():
            raise InstallError(f"backup directory is not a real directory: {parent}")
    else:
        try:
            parent.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise InstallError(f"could not create backup directory {parent}: {exc}") from exc
    try:
        if os.stat(parent).st_dev != os.stat(target).st_dev:
            raise InstallError(
                f"backup directory is on a different filesystem from the target: {parent}"
            )
    except OSError as exc:
        raise InstallError(f"could not inspect backup filesystem: {exc}") from exc
    return parent


def _unique_backup_path(target: Path) -> Path:
    parent = _ensure_backup_parent(target)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for _ in range(100):
        candidate = parent / f"{target.name}-{stamp}-{secrets.token_hex(6)}"
        if not _lexists(candidate):
            return candidate
    raise InstallError(f"could not allocate a unique backup path beside {target}")


def _remove_new_empty_backup_parent(parent: Path, existed_before: bool) -> None:
    if existed_before or not parent.is_dir():
        return
    try:
        if not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


def _safe_remove_stage(stage: Path, parent: Path) -> None:
    if stage.parent != parent or not stage.name.startswith(".linkedai.stage-"):
        raise InstallError(f"refusing to clean an unexpected staging path: {stage}")
    _remove_path(stage)


def _swap_stage(stage: Path, target: Path) -> Path | None:
    backup: Path | None = None
    if _lexists(target):
        backup_parent = _backup_parent(target)
        backup_parent_existed = _lexists(backup_parent)
        try:
            backup = _unique_backup_path(target)
        except Exception:
            _remove_new_empty_backup_parent(backup_parent, backup_parent_existed)
            raise
        try:
            os.rename(target, backup)
        except OSError as exc:
            _remove_new_empty_backup_parent(backup_parent, backup_parent_existed)
            raise InstallError(f"could not move current target to backup: {exc}") from exc
        try:
            os.rename(stage, target)
        except OSError as exc:
            try:
                os.rename(backup, target)
            except OSError as rollback_exc:
                raise InstallError(
                    "install swap failed and rollback failed; "
                    f"the recoverable backup is at {backup}: {rollback_exc}"
                ) from exc
            _remove_new_empty_backup_parent(backup_parent, backup_parent_existed)
            raise InstallError(
                f"install swap failed; the current target was restored: {exc}"
            ) from exc
        return backup

    try:
        os.rename(stage, target)
    except OSError as exc:
        raise InstallError(f"could not activate staged install: {exc}") from exc
    return None


def install(source: Path | None = None, target: Path | None = None) -> InstallResult:
    """Validate, stage, and atomically install the package."""

    _check_dependencies()
    source = (source or Path(__file__).resolve().parent.parent).expanduser().resolve(strict=True)
    if not source.is_dir():
        raise InstallError(f"source/stage is not a directory: {source}")

    # Source validation and dependency checks happen before creating or moving
    # anything at the target location.
    validate_package(source)
    _run_validator(source)

    requested_target = target.expanduser() if target is not None else _default_target()
    target_path = _validate_target(source, requested_target)
    if target_path == source:
        # A symlink alias to source reaches this branch too. It is deliberately
        # after source validation and performs no staging, backup, or deletion.
        return InstallResult(target=target_path, no_op=True)

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InstallError(f"could not create target parent {target_path.parent}: {exc}") from exc

    # Re-check the target after parent creation so a late symlink cannot be
    # mistaken for a normal destination.
    target_path = _validate_target(source, target_path)
    stage: Path | None = None
    try:
        stage = Path(tempfile.mkdtemp(prefix=".linkedai.stage-", dir=str(target_path.parent)))
        if _lexists(target_path):
            if target_path.is_symlink() or not target_path.is_dir():
                raise InstallError(f"target changed to an unsafe entry: {target_path}")
            for child in sorted(target_path.iterdir(), key=lambda item: item.name):
                _copy_existing_entry(child, stage / child.name)
            _clean_staged_exclusions(stage)

        for relative_text in PACKAGE_ENTRIES:
            _copy_source_entry(source, stage, Path(relative_text))
        _clean_legacy_ag(stage)
        _clean_legacy_nested_skills(stage)
        _clean_staged_exclusions(stage)

        validate_package(stage)
        _run_validator(stage)
        backup = _swap_stage(stage, target_path)
        stage = None
        return InstallResult(target=target_path, backup=backup)
    finally:
        if stage is not None and _lexists(stage):
            _safe_remove_stage(stage, target_path.parent)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely install LinkedAI as a Codex skill")
    parser.add_argument(
        "--target",
        type=Path,
        help="isolated destination; it must end with a directory named linkedai",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = install(target=args.target)
    except (InstallError, OSError, UnicodeError) as exc:
        print(f"LinkedAI install failed: {exc}", file=sys.stderr)
        return 1

    if result.no_op:
        print(f"no-op: source and target are the same validated path: {result.target}")
        return 0
    if result.backup is None:
        print("backup preserved: none (fresh install)")
    else:
        print(f"backup preserved: {result.backup}")
    print(f"installed LinkedAI -> {result.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
