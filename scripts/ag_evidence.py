#!/usr/bin/env python3
"""Fail-closed validation for captured Antigravity evidence.

This module deliberately does not start Antigravity. A caller supplies the
process result and before/after filesystem snapshots, and this module decides
whether those facts are sufficient for an AG_PASS. That keeps an AG claim of
SUCCESS from becoming a LinkedAI completion claim by itself. The caller must
also explicitly provide a trusted project-scoped isolation receipt; this module
cannot prove host containment on its own.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Optional, Sequence


class EvidenceError(ValueError):
    """Raised when supplied evidence cannot be interpreted safely."""


PERMISSION_MARKERS = (
    "permission denied",
    "auto-denied",
    "auto denied",
    "soft-denied",
    "soft denied",
    "cannot prompt",
    "headless mode cannot",
    "required the \"",
    "no output produced",
)


def canonical_root(root: os.PathLike[str] | str) -> Path:
    """Return an existing directory's canonical path."""

    candidate = Path(root).expanduser().resolve(strict=True)
    if not candidate.is_dir():
        raise EvidenceError(f"project root is not a directory: {root}")
    return candidate


def safe_relative_path(root: os.PathLike[str] | str, raw: Any) -> str:
    """Normalize a relative path and reject traversal or symlink escapes."""

    project_root = canonical_root(root)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise EvidenceError("path must be a non-empty string without NUL")

    posix_path = PurePosixPath(raw)
    windows_path = PureWindowsPath(raw)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise EvidenceError(f"path must be relative to project root: {raw!r}")
    if any(part == ".." for part in posix_path.parts) or any(
        part == ".." for part in windows_path.parts
    ):
        raise EvidenceError(f"path traversal is not allowed: {raw!r}")

    parts = tuple(part for part in posix_path.parts if part not in {"", "."})
    if not parts:
        raise EvidenceError("path must identify an entry below project root")
    normalized = Path(*parts).as_posix()
    resolved = (project_root / Path(*parts)).resolve(strict=False)
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise EvidenceError(f"path resolves outside project root: {raw!r}") from exc
    return normalized


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError:
        return False
    return True


def snapshot_tree(root: os.PathLike[str] | str) -> dict[str, dict[str, Any]]:
    """Snapshot regular files and symlinks below root without following links.

    Symlinks are recorded but never traversed. A symlink whose target resolves
    outside root is retained with ``outside_root`` set so a later validator can
    reject it deterministically.
    """

    project_root = canonical_root(root)
    snapshot: dict[str, dict[str, Any]] = {}

    def visit(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise EvidenceError(f"cannot inspect {directory}: {exc}") from exc
        for entry in entries:
            entry_path = Path(entry.path)
            relative = entry_path.relative_to(project_root).as_posix()
            try:
                if entry.is_symlink():
                    link_target = os.readlink(entry.path)
                    resolved_target = entry_path.resolve(strict=False)
                    snapshot[relative] = {
                        "kind": "symlink",
                        "target": link_target,
                        "outside_root": not _inside(project_root, resolved_target),
                    }
                    continue
                if entry.is_dir(follow_symlinks=False):
                    visit(entry_path)
                    continue
                if entry.is_file(follow_symlinks=False):
                    resolved = entry_path.resolve(strict=False)
                    if not _inside(project_root, resolved):
                        raise EvidenceError(f"file resolves outside project root: {relative}")
                    snapshot[relative] = {
                        "kind": "file",
                        "sha256": _hash_file(entry_path),
                        "size": entry.stat(follow_symlinks=False).st_size,
                    }
                    continue
                raise EvidenceError(f"unsupported filesystem entry: {relative}")
            except OSError as exc:
                raise EvidenceError(f"cannot inspect {relative}: {exc}") from exc

    visit(project_root)
    return snapshot


def changed_paths(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    """Return sorted snapshot keys whose records differ."""

    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        raise EvidenceError("snapshots must be JSON objects")
    return sorted(
        str(path)
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )


def _meaningful_response(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, list)):
        return bool(value)
    return False


def _result_candidate(event: Any) -> Optional[Mapping[str, Any]]:
    if not isinstance(event, Mapping):
        return None
    nested = event.get("result")
    if isinstance(nested, Mapping) and (
        "status" in nested or "response" in nested or "structured_output" in nested
    ):
        return nested
    event_name = event.get("event", event.get("type"))
    if event_name == "result" or "status" in event or "response" in event:
        return event
    return None


def parse_stream_json(stdout: str) -> dict[str, Any]:
    """Parse AG NDJSON and return its final result plus denial evidence.

    A single JSON result object is accepted too, which makes captured batch
    output diagnosable. Any malformed non-empty line fails closed.
    """

    if not isinstance(stdout, str) or not stdout.strip():
        raise EvidenceError("AG produced no stdout")
    events: list[Mapping[str, Any]] = []
    denied_actions: list[Any] = []
    result: Optional[Mapping[str, Any]] = None
    model: Optional[str] = None
    for line_number, raw_line in enumerate(stdout.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"invalid JSON on AG output line {line_number}") from exc
        if not isinstance(event, Mapping):
            raise EvidenceError(f"AG output line {line_number} is not a JSON object")
        events.append(event)
        init = event.get("init")
        if isinstance(init, Mapping) and isinstance(init.get("model"), str):
            model = init["model"]
        candidate_denials = event.get("denied_actions")
        if candidate_denials:
            if isinstance(candidate_denials, list):
                denied_actions.extend(candidate_denials)
            else:
                denied_actions.append(candidate_denials)
        candidate = _result_candidate(event)
        if candidate is not None:
            result = candidate

    if result is None:
        raise EvidenceError("AG output has no final result object")
    nested_denials = result.get("denied_actions")
    if nested_denials:
        if isinstance(nested_denials, list):
            denied_actions.extend(nested_denials)
        else:
            denied_actions.append(nested_denials)
    response = result.get("structured_output", result.get("response"))
    if not _meaningful_response(response):
        raise EvidenceError("AG final result has an empty response")
    status = result.get("status")
    if not isinstance(status, str) or not status.strip():
        raise EvidenceError("AG final result has no status")
    if status.strip().upper() not in {"SUCCESS", "PASS", "OK", "COMPLETED"}:
        raise EvidenceError(f"AG final result status is not successful: {status!r}")
    return {
        "result": dict(result),
        "events": len(events),
        "model": model,
        "denied_actions": denied_actions,
        "response_present": True,
    }


def _snapshot_errors(root: Path, snapshot: Mapping[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    for raw_path, record in snapshot.items():
        try:
            relative = safe_relative_path(root, raw_path)
        except EvidenceError as exc:
            errors.append(f"{label} path {raw_path!r}: {exc}")
            continue
        if relative != raw_path:
            errors.append(f"{label} path is not normalized: {raw_path!r}")
        if isinstance(record, Mapping) and record.get("outside_root"):
            errors.append(f"{label} symlink escapes project root: {raw_path}")
    return errors


def validate_ag_evidence(
    root: os.PathLike[str] | str,
    allowed_paths: Sequence[str],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    returncode: int,
    stdout: str,
    stderr: str,
    expected_changed_paths: Optional[Sequence[str]] = None,
    isolation_proven: bool = False,
) -> dict[str, Any]:
    """Validate captured AG process, output, and filesystem evidence.

    ``AG_PASS`` is possible only when every supplied fact is clean. This
    function never considers an AG-reported SUCCESS sufficient on its own.
    """

    errors: list[str] = []
    parsed: Optional[dict[str, Any]] = None
    try:
        project_root = canonical_root(root)
    except EvidenceError as exc:
        return {"status": "AG_UNAVAILABLE", "errors": [str(exc)], "changed_paths": []}

    if isolation_proven is not True:
        errors.append("project-scoped AG isolation is not proven")

    normalized_allowed: list[str] = []
    for raw_path in allowed_paths:
        try:
            normalized = safe_relative_path(project_root, raw_path)
            if normalized not in normalized_allowed:
                normalized_allowed.append(normalized)
        except EvidenceError as exc:
            errors.append(f"allowed path {raw_path!r}: {exc}")

    errors.extend(_snapshot_errors(project_root, before, "before"))
    errors.extend(_snapshot_errors(project_root, after, "after"))
    try:
        modified = changed_paths(before, after)
    except EvidenceError as exc:
        modified = []
        errors.append(str(exc))

    undeclared = [path for path in modified if path not in normalized_allowed]
    if undeclared:
        errors.append("undeclared changed paths: " + ", ".join(undeclared))

    if expected_changed_paths is not None:
        expected: list[str] = []
        for raw_path in expected_changed_paths:
            try:
                normalized = safe_relative_path(project_root, raw_path)
                if normalized not in expected:
                    expected.append(normalized)
            except EvidenceError as exc:
                errors.append(f"expected path {raw_path!r}: {exc}")
        if modified != sorted(expected):
            errors.append(
                "changed paths do not match expectation: "
                f"expected {sorted(expected)}, observed {modified}"
            )

    combined_output = (stdout + "\n" + stderr).lower()
    for marker in PERMISSION_MARKERS:
        if marker in combined_output:
            errors.append(f"permission/transport marker detected: {marker}")
    try:
        parsed = parse_stream_json(stdout)
        if parsed["denied_actions"]:
            errors.append("AG reported denied_actions")
    except EvidenceError as exc:
        errors.append(str(exc))

    if returncode != 0:
        errors.append(f"AG exited with code {returncode}")

    status = "AG_PASS" if not errors else "AG_FAILED"
    if any(
        phrase in error.lower()
        for error in errors
        for phrase in (
            "permission",
            "denied",
            "cannot prompt",
            "no stdout",
            "empty response",
            "invalid json",
            "no final result",
            "exited with code",
            "isolation",
        )
    ):
        status = "AG_UNAVAILABLE"
    return {
        "status": status,
        "errors": errors,
        "changed_paths": modified,
        "allowed_paths": normalized_allowed,
        "result": parsed,
    }


def _command_evidence(path: str) -> int:
    evidence_path = Path(path).expanduser()
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        result = validate_ag_evidence(
            payload["root"],
            payload.get("allowed_paths", []),
            payload["before"],
            payload["after"],
            int(payload["returncode"]),
            payload.get("stdout", ""),
            payload.get("stderr", ""),
            payload.get("expected_changed_paths"),
            payload.get("isolation_proven", False),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "AG_UNAVAILABLE", "errors": [str(exc)]}, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] == "AG_PASS" else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate captured AG evidence only")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evidence_parser = subparsers.add_parser(
        "evidence", help="validate a captured evidence JSON file; never runs AG"
    )
    evidence_parser.add_argument("file")
    args = parser.parse_args(argv)
    if args.command == "evidence":
        return _command_evidence(args.file)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
