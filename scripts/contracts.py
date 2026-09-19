#!/usr/bin/env python3
"""Deterministic validation, run-bundle, routing, and fingerprint contracts.

This module deliberately does not start agents or mutate a repository.  It
validates controller-stamped artifacts against JSON Schema and performs the
small amount of cross-artifact checking that JSON Schema cannot express.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import yaml
except ImportError as exc:  # pragma: no cover - requirements install path
    yaml = None
    _YAML_IMPORT_ERROR = exc

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover - requirements install path
    Draft202012Validator = None
    _JSONSCHEMA_IMPORT_ERROR = exc


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
ACTIVE_SCHEMAS = {
    "task-packet": SCHEMA_DIR / "task-packet.schema.json",
    "astra-plan": SCHEMA_DIR / "astra-plan.schema.json",
    "luna-result": SCHEMA_DIR / "luna-result.schema.json",
    "sol-verification": SCHEMA_DIR / "sol-verification.schema.json",
    "luna-verification": SCHEMA_DIR / "luna-verification.schema.json",
    "routing-decision": SCHEMA_DIR / "routing-decision.schema.json",
    "plan-gate": SCHEMA_DIR / "plan-gate.schema.json",
    "run-bundle": SCHEMA_DIR / "run-bundle.schema.json",
}

STAGE_BY_STATE = {
    "RETRY": "LUNA_EXECUTION",
    "REPLAN": "ASTRA_PLAN",
    "EVIDENCE": "LUNA_EVIDENCE",
    "REQUEST_EVIDENCE": "LUNA_EVIDENCE",
    "DONE": "STOP",
    "BLOCKED": "STOP_BLOCKED",
    "ESCALATE": "STOP_BLOCKED",
}
INTENTS = {"change", "investigate", "review", "explain"}
LUNA_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
ASTRA_ROLES = {"ASTRA", "ASTRA_PLAN"}
LUNA_ROLES = {"LUNA", "LUNA_EXECUTION", "LUNA_VERIFICATION"}
SOL_ROLES = {"SOL", "SOL_VERIFICATION"}
DISPATCH_MODES = ("FAST", "STANDARD", "DEEP")
DISPATCH_RANK = {mode: index for index, mode in enumerate(DISPATCH_MODES)}
VERIFICATION_PROFILES = ("BALANCED", "FULL", "QUICK")
VERIFICATION_PROFILE_BY_MODE = {
    "FAST": "BALANCED",
    "STANDARD": "BALANCED",
    "DEEP": "FULL",
}
ASTRA_HIGH_LUNA_SOL_WORKFLOW_STAGES = (
    "LUNA_RECON",
    "PACKET",
    "ASTRA_PLAN",
    "LUNA_EXECUTION",
    "SOL_VERIFICATION",
)
LUNA_ECHO_WORKFLOW_STAGES = (
    "LUNA_RECON",
    "PACKET",
    "ASTRA_PLAN",
    "LUNA_EXECUTION",
    "LUNA_VERIFICATION",
)
WORKFLOW_STAGES = ASTRA_HIGH_LUNA_SOL_WORKFLOW_STAGES
PLAN_APPROVAL_WORKFLOW_STAGES = (
    "LUNA_RECON",
    "PACKET",
    "ASTRA_PLAN",
    "WAITING_FOR_USER_APPROVAL",
)
APPROVED_PLAN_FAST_WORKFLOW_STAGES = (
    "LUNA_RECON",
    "PACKET",
    "ASTRA_PLAN",
    "USER_APPROVAL",
    "LUNA_EXECUTION",
    "SOL_VERIFICATION",
)
FAST_WORKFLOW_STAGES = (
    *ASTRA_HIGH_LUNA_SOL_WORKFLOW_STAGES,
)
ASTRA_HIGH_LUNA_SOL_VARIANT = "astra_high_luna_sol"
ASTRA_HIGH_LUNA_ECHO_VARIANT = "astra_high_luna_echo"
WORKFLOW_VARIANTS = {
    "FAST": ASTRA_HIGH_LUNA_SOL_VARIANT,
    "STANDARD": ASTRA_HIGH_LUNA_SOL_VARIANT,
    "DEEP": ASTRA_HIGH_LUNA_SOL_VARIANT,
}
WORKFLOW_STAGES_BY_MODE = {
    "FAST": ASTRA_HIGH_LUNA_SOL_WORKFLOW_STAGES,
    "STANDARD": ASTRA_HIGH_LUNA_SOL_WORKFLOW_STAGES,
    "DEEP": ASTRA_HIGH_LUNA_SOL_WORKFLOW_STAGES,
}
APPROVAL_POLICIES = {"AUTO", "REQUIRED"}
PLAN_APPROVAL_VARIANT = "plan_approval_gate"
APPROVED_PLAN_FAST_VARIANT = "approved_plan_fast_luna_sol"
LEGACY_FULL_VARIANT = "full_astra_luna_sol"
FAST_REQUIRED_SIGNALS = (
    "bounded_scope",
    "known_behavior",
    "known_dependencies",
    "sufficient_evidence",
    "direct_verification",
)
FAST_BLOCKING_SIGNALS = (
    "unresolved_failure",
    "material_risk",
    "material_architectural_uncertainty",
    "conflicting_evidence",
    "repeated_unresolved_failures",
)
DEEP_SIGNALS = (
    "material_architectural_uncertainty",
    "conflicting_evidence",
    "repeated_unresolved_failures",
)


class ContractError(Exception):
    """A user-facing contract or safety failure."""


def _require_jsonschema() -> Any:
    if Draft202012Validator is None:
        raise ContractError(
            "jsonschema is required for contract validation: "
            f"{_JSONSCHEMA_IMPORT_ERROR}"
        )
    return Draft202012Validator


def _require_yaml() -> Any:
    if yaml is None:
        raise ContractError(
            f"PyYAML is required for UI metadata validation: {_YAML_IMPORT_ERROR}"
        )
    return yaml


def _meaningful(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def canonical_sha256(value: Any) -> str:
    """Hash a JSON value without depending on object-key order or whitespace."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError(f"cannot canonically hash JSON value: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def approval_bindings(
    plan: Mapping[str, Any],
    packet: Mapping[str, Any],
    baseline_snapshot: Mapping[str, Any],
) -> Dict[str, str]:
    """Return hashes for the immutable inputs a user approves."""

    return {
        "plan_hash": canonical_sha256(plan),
        "packet_hash": canonical_sha256(packet),
        "baseline_hash": canonical_sha256(baseline_snapshot),
        "scope_hash": canonical_sha256(plan.get("change_scope", [])),
        "acceptance_hash": canonical_sha256(plan.get("acceptance_criteria", [])),
        "verification_hash": canonical_sha256(
            {
                "verification_plan": plan.get("verification_plan", []),
                "observation_plan": plan.get("observation_plan", []),
            }
        ),
    }


def select_dispatch_mode(
    decision: Mapping[str, Any], current_mode: Optional[str] = None
) -> Dict[str, Any]:
    """Select dispatch metadata without dispatching or changing workflow state."""

    if not isinstance(decision, Mapping):
        raise ContractError("dispatch decision must be a JSON object")
    if current_mode is not None:
        normalized_current = current_mode.strip().upper() if isinstance(current_mode, str) else ""
        if normalized_current not in DISPATCH_MODES:
            raise ContractError(
                f"current_mode must be one of {', '.join(DISPATCH_MODES)}"
            )
        current_mode = normalized_current

    invalid_inputs: List[str] = []
    requested_approval_policy = decision.get("approval_policy")
    if requested_approval_policy is not None:
        if (
            not isinstance(requested_approval_policy, str)
            or requested_approval_policy.upper() not in APPROVAL_POLICIES
        ):
            invalid_inputs.append("approval_policy must be AUTO or REQUIRED")
        else:
            requested_approval_policy = requested_approval_policy.upper()
    for field in ("intent", "reasons", "risk_flags", "changed_paths", "source_mutation"):
        if field not in decision:
            invalid_inputs.append(f"{field} is missing")
    intent = decision.get("intent")
    if intent not in INTENTS:
        invalid_inputs.append("intent is invalid")
    reasons = decision.get("reasons")
    if not isinstance(reasons, list) or not reasons or not all(
        isinstance(reason, str) and bool(reason.strip()) for reason in reasons
    ):
        invalid_inputs.append("reasons must be a non-empty array of meaningful strings")
    tier = decision.get("tier")
    if not isinstance(tier, int) or isinstance(tier, bool) or tier not in {0, 1, 2, 3}:
        invalid_inputs.append("tier is missing or invalid")
        tier = None
    risk_flags = decision.get("risk_flags")
    if risk_flags is not None and (
        not isinstance(risk_flags, list)
        or not all(isinstance(flag, str) and bool(flag.strip()) for flag in risk_flags)
    ):
        invalid_inputs.append("risk_flags must be an array of meaningful strings")
        risk_flags = []
    changed_paths = decision.get("changed_paths")
    if not isinstance(changed_paths, list) or not all(
        isinstance(path, str) and bool(path.strip()) for path in changed_paths
    ):
        invalid_inputs.append("changed_paths must be an array of meaningful strings")
    if not isinstance(decision.get("source_mutation"), bool):
        invalid_inputs.append("source_mutation must be boolean")
    eligibility = decision.get("eligibility")
    if eligibility is not None and not isinstance(eligibility, Mapping):
        invalid_inputs.append("eligibility must be an object")
        eligibility = None
    if isinstance(eligibility, Mapping):
        for key, value in eligibility.items():
            if key not in FAST_REQUIRED_SIGNALS and key not in FAST_BLOCKING_SIGNALS:
                invalid_inputs.append(f"eligibility contains unsupported signal {key!r}")
            elif not isinstance(value, bool):
                invalid_inputs.append(f"eligibility.{key} must be boolean")

    deep_reasons: List[str] = []
    eligibility_incomplete = False
    if tier == 3:
        deep_reasons.append("Tier 3 requires DEEP")
    if isinstance(eligibility, Mapping):
        for key in DEEP_SIGNALS:
            if eligibility.get(key) is True:
                deep_reasons.append(f"eligibility.{key} is true")

    if deep_reasons:
        proposed = "DEEP"
        reason = "; ".join(deep_reasons)
    elif tier in {1, 2}:
        proposed = "STANDARD"
        reason = f"Tier {tier} uses STANDARD by default"
    elif tier == 0 and intent == "change":
        missing = [
            key
            for key in FAST_REQUIRED_SIGNALS + FAST_BLOCKING_SIGNALS
            if not isinstance(eligibility, Mapping) or key not in eligibility
        ]
        eligibility_incomplete = bool(missing)
        false_required = [
            key for key in FAST_REQUIRED_SIGNALS
            if isinstance(eligibility, Mapping) and eligibility.get(key) is False
        ]
        true_blocking = [
            key for key in FAST_BLOCKING_SIGNALS
            if isinstance(eligibility, Mapping) and eligibility.get(key) is True
        ]
        if invalid_inputs or missing or false_required or true_blocking or risk_flags:
            proposed = "STANDARD"
            details = invalid_inputs + [f"missing eligibility.{key}" for key in missing]
            details += [f"eligibility.{key} is false" for key in false_required]
            details += [f"eligibility.{key} blocks FAST" for key in true_blocking]
            if risk_flags:
                details.append("risk_flags are present")
            reason = "FAST ineligible: " + "; ".join(details)
        else:
            proposed = "FAST"
            reason = "Tier 0 with all FAST eligibility signals satisfied"
    elif tier == 0:
        proposed = "STANDARD"
        reason = "FAST is reserved for bounded change execution; non-change work uses STANDARD"
    else:
        proposed = "STANDARD"
        reason = "invalid routing inputs; conservative STANDARD fallback"

    if invalid_inputs and proposed != "DEEP":
        proposed = "STANDARD"
        reason = "invalid routing inputs; conservative STANDARD fallback: " + "; ".join(invalid_inputs)

    selected = proposed
    escalated = False
    if current_mode is not None and DISPATCH_RANK[proposed] < DISPATCH_RANK[current_mode]:
        selected = current_mode
        reason = f"no automatic in-run downgrade; retained {current_mode}"
    elif current_mode is not None and DISPATCH_RANK[proposed] > DISPATCH_RANK[current_mode]:
        escalated = True
        reason = f"escalated from {current_mode} to {proposed}: {reason}"

    # V8 has one active automatic path. ``dispatch_mode`` remains useful risk
    # metadata, but it no longer selects an ASTRA bypass or a user-approval
    # pause. The old approval artifacts remain validator-compatible migration
    # data and are never emitted by current routing.
    approval_required = False
    approval_policy = "AUTO"
    post_approval_variant = None
    post_approval_stages: List[str] = []
    if requested_approval_policy == "REQUIRED":
        reason = f"{reason}; V8 approval gates are inactive"
    return {
        "dispatch_mode": selected,
        "dispatch_reason": reason,
        "proposed_mode": proposed,
        "current_mode": current_mode,
        "escalated": escalated,
        "input_valid": not invalid_inputs and not eligibility_incomplete,
        "workflow_variant": WORKFLOW_VARIANTS[selected],
        "workflow_stages": list(WORKFLOW_STAGES_BY_MODE[selected]),
        "verification_profile": VERIFICATION_PROFILE_BY_MODE[selected],
        "approval_policy": approval_policy,
        "approval_required": approval_required,
        "post_approval_variant": post_approval_variant,
        "post_approval_stages": post_approval_stages,
    }


def _schema_key(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ContractError("schema name is required")
    candidate = Path(name.strip()).name
    if candidate.endswith(".schema.json"):
        candidate = candidate[: -len(".schema.json")]
    elif candidate.endswith(".json"):
        candidate = candidate[:-len(".json")]
    candidate = candidate.replace("_", "-").lower()
    if candidate not in ACTIVE_SCHEMAS:
        raise ContractError(
            f"unknown active schema {name!r}; expected one of "
            f"{', '.join(sorted(ACTIVE_SCHEMAS))}"
        )
    return candidate


def load_json(path: Path | str) -> Any:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot read JSON artifact {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON in {path}: {exc}") from exc


def _schema_paths(root: Path | str = ROOT) -> Dict[str, Path]:
    root_path = Path(root)
    return {key: root_path / "schemas" / path.name for key, path in ACTIVE_SCHEMAS.items()}


def load_schema(name: str, root: Path | str = ROOT) -> Tuple[str, Dict[str, Any]]:
    key = _schema_key(name)
    path = _schema_paths(root)[key]
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError(f"cannot read schema {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON in schema {path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ContractError(f"schema {path} must be a JSON object")
    return key, schema


def validate_schema(name: str, root: Path | str = ROOT) -> List[str]:
    """Meta-validate an active schema with Draft 2020-12."""

    validator_cls = _require_jsonschema()
    key, schema = load_schema(name, root)
    try:
        validator_cls.check_schema(schema)
    except Exception as exc:  # jsonschema.SchemaError without importing a type
        return [f"{key}: Draft 2020-12 meta-validation failed: {exc}"]
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        return [f"{key}: $schema must select Draft 2020-12"]
    if schema.get("type") != "object":
        return [f"{key}: top-level schema type must be object"]
    return []


def _error_path(error: Any) -> str:
    path = list(error.absolute_path)
    if not path:
        return "$"
    rendered = "$"
    for part in path:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += "." + str(part)
    return rendered


def validate_instance(name: str, instance: Any, root: Path | str = ROOT) -> List[str]:
    """Return deterministic Draft 2020-12 instance-validation errors."""

    validator_cls = _require_jsonschema()
    key, schema = load_schema(name, root)
    meta_errors = validate_schema(key, root)
    if meta_errors:
        return meta_errors
    validator = validator_cls(schema)
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda item: (list(item.absolute_path), item.validator or "", item.message),
    )
    messages = [f"{key} {_error_path(error)}: {error.message}" for error in errors]
    if not messages and isinstance(instance, dict):
        if key == "astra-plan":
            _criterion_ids(instance.get("acceptance_criteria"), "plan.acceptance_criteria", messages)
            _observation_ids(instance.get("observation_plan"), "plan.observation_plan", messages)
            _request_ids(instance.get("evidence_requests"), "plan.evidence_requests", messages)
        elif key == "luna-result":
            _criterion_ids(instance.get("criteria_evidence"), "result.criteria_evidence", messages)
            _observation_ids(instance.get("observations"), "result.observations", messages)
            _check_command_links(instance.get("commands"), messages)
        elif key in {"sol-verification", "luna-verification"}:
            _criterion_ids(instance.get("criteria"), "verification.criteria", messages)
            _request_ids(instance.get("evidence_requests"), "verification.evidence_requests", messages)
        elif key == "plan-gate":
            _validate_plan_gate_components(instance, messages, root)
    return messages


def _root_path(root: Path | str) -> Path:
    root_path = Path(root)
    if not root_path.exists():
        raise ContractError(f"root does not exist: {root_path}")
    if not root_path.is_dir():
        raise ContractError(f"root is not a directory: {root_path}")
    try:
        return root_path.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"cannot resolve root {root_path}: {exc}") from exc


def _relative_path(raw: Any, label: str = "path") -> str:
    if not isinstance(raw, str) or not raw:
        raise ContractError(f"{label} must be a nonempty relative path")
    if "\x00" in raw:
        raise ContractError(f"{label} contains NUL")
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise ContractError(f"{label} must be relative, got {raw!r}")
    parts = posix.parts
    if not parts or raw in {".", "./"} or any(part in {"", ".", ".."} for part in parts):
        raise ContractError(
            f"{label} contains traversal or non-canonical components: {raw!r}"
        )
    normalized = "/".join(parts)
    if normalized.startswith("../") or normalized == "..":
        raise ContractError(f"{label} escapes its root: {raw!r}")
    return normalized


def _safe_file(root: Path, relative: str, label: str = "path") -> Tuple[str, Path]:
    normalized = _relative_path(relative, label)
    candidate = root.joinpath(*PurePosixPath(normalized).parts)
    if not candidate.exists():
        raise ContractError(f"{label} does not exist: {normalized}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"cannot resolve {label} {normalized}: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ContractError(
            f"{label} symlink escapes root: {normalized} -> {resolved}"
        ) from exc
    try:
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise ContractError(f"cannot stat {label} {normalized}: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise ContractError(
            f"unsupported special file for {label} {normalized}; only regular files "
            "are fingerprintable"
        )
    return normalized, resolved


def _run_git(root: Path, args: Sequence[str], allow_failure: bool = False) -> bytes:
    command = ["git", "-C", str(root), *args]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise ContractError(f"cannot run git for fingerprint: {exc}") from exc
    if result.returncode != 0 and not allow_failure:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ContractError(
            f"git {' '.join(args)} failed with exit {result.returncode}"
            + (f": {detail}" if detail else "")
        )
    return result.stdout


def _git_toplevel(root: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise ContractError(f"cannot run git for fingerprint: {exc}") from exc
    if result.returncode != 0:
        return None
    text = result.stdout.decode("utf-8", "replace").strip()
    if not text:
        return None
    try:
        return Path(text).resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"cannot resolve Git worktree {text}: {exc}") from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ContractError(f"cannot read fingerprint file {path}: {exc}") from exc
    return digest.hexdigest()


def _make_snapshot(
    kind: str,
    root: Path,
    paths: Iterable[str],
    revision: str,
    repository_state: bytes = b"",
    allow_missing: bool = False,
) -> Dict[str, Any]:
    normalized_paths = sorted(paths)
    files = []
    for relative in normalized_paths:
        normalized = _relative_path(relative)
        candidate = root.joinpath(*PurePosixPath(normalized).parts)
        if allow_missing and not os.path.lexists(candidate):
            try:
                resolved = candidate.resolve(strict=False)
                resolved.relative_to(root)
            except ValueError as exc:
                raise ContractError(
                    f"path symlink escapes root: {normalized}"
                ) from exc
            except OSError as exc:
                raise ContractError(
                    f"cannot resolve missing fingerprint path {normalized}: {exc}"
                ) from exc
            files.append({"path": normalized, "missing": True})
            continue
        normalized, resolved = _safe_file(root, relative)
        files.append({"path": normalized, "sha256": _file_sha256(resolved)})
    canonical = {
        "kind": kind,
        "revision": revision,
        "files": files,
        "repository_state_sha256": hashlib.sha256(repository_state).hexdigest(),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "kind": kind,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "paths": normalized_paths,
        "revision": revision,
    }


def fingerprint_git(root: Path | str) -> Dict[str, Any]:
    """Fingerprint the complete nonignored Git worktree, not HEAD alone."""

    root_path = _root_path(root)
    toplevel = _git_toplevel(root_path)
    if toplevel is None:
        raise ContractError(
            f"{root_path} is not a Git worktree; use fingerprint --paths for "
            "a non-Git scoped fingerprint"
        )
    if toplevel != root_path:
        raise ContractError(
            f"Git fingerprint root must be the repository root {toplevel}, got {root_path}"
        )

    staged = _run_git(root_path, ["ls-files", "--stage", "-z"])
    for record in staged.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
        except ValueError as exc:
            raise ContractError("git returned an unreadable index entry") from exc
        mode = metadata.split(b" ", 1)[0]
        if mode == b"160000":
            path = raw_path.decode("utf-8", "replace")
            raise ContractError(f"unsupported Git submodule in fingerprint scope: {path}")

    raw_paths = _run_git(root_path, ["ls-files", "-co", "--exclude-standard", "-z"])
    paths: List[str] = []
    for raw_path in raw_paths.split(b"\0"):
        if not raw_path:
            continue
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError("Git path is not valid UTF-8; refusing unsafe fingerprint") from exc
        paths.append(_relative_path(path, "Git path"))
    if len(paths) != len(set(paths)):
        raise ContractError("Git returned duplicate paths")

    revision_bytes = _run_git(root_path, ["rev-parse", "--verify", "HEAD"], allow_failure=True)
    revision = revision_bytes.decode("ascii", "replace").strip() or "NO_HEAD"
    diff = _run_git(root_path, ["diff", "--no-ext-diff", "--binary", "HEAD", "--"], allow_failure=True)
    status = _run_git(
        root_path,
        ["status", "--porcelain=v1", "--untracked-files=all", "-z"],
        allow_failure=True,
    )
    repository_state = (
        diff
        + b"\0LINKEDAI_INDEX\0"
        + staged
        + b"\0LINKEDAI_STATUS\0"
        + status
    )
    return _make_snapshot(
        "git",
        root_path,
        paths,
        revision,
        repository_state,
        allow_missing=True,
    )


def fingerprint_paths(paths: Sequence[str], root: Path | str | None = None) -> Dict[str, Any]:
    """Fingerprint an explicit set of regular files in a non-Git root."""

    if not paths:
        raise ContractError("at least one path is required for a scoped fingerprint")
    root_path = _root_path(root or Path.cwd())
    if _git_toplevel(root_path) is not None:
        raise ContractError(
            "scoped fingerprints are for non-Git roots; Git mode must include every "
            "tracked and nonignored untracked file"
        )
    normalized = [_relative_path(path, "scoped path") for path in paths]
    if len(normalized) != len(set(normalized)):
        raise ContractError("scoped fingerprint paths must be unique")
    for path in normalized:
        _safe_file(root_path, path, "scoped path")
    return _make_snapshot("scoped", root_path, normalized, "non-git")


def _snapshot_current(snapshot: Mapping[str, Any], root: Path | str) -> Dict[str, Any]:
    kind = snapshot.get("kind")
    if kind == "git":
        return fingerprint_git(root)
    if kind == "scoped":
        paths = snapshot.get("paths")
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise ContractError("scoped snapshot paths must be a list of strings")
        return fingerprint_paths(paths, root)
    raise ContractError(f"unsupported snapshot kind {kind!r}")


def _criterion_ids(items: Any, label: str, errors: List[str]) -> set[str]:
    if not isinstance(items, list):
        errors.append(f"{label} must be an array")
        return set()
    ids: List[str] = []
    for index, item in enumerate(items):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(item["id"])
        else:
            errors.append(f"{label}[{index}] has no usable criterion id")
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        errors.append(f"{label} contains duplicate criterion ids: {', '.join(duplicates)}")
    return set(ids)


def _observation_ids(items: Any, label: str, errors: List[str]) -> set[str]:
    if items is None:
        return set()
    if not isinstance(items, list):
        errors.append(f"{label} must be an array")
        return set()
    ids: List[str] = []
    for index, item in enumerate(items):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(item["id"])
        else:
            errors.append(f"{label}[{index}] has no usable observation id")
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        errors.append(f"{label} contains duplicate observation ids: {', '.join(duplicates)}")
    return set(ids)


def _request_ids(items: Any, label: str, errors: List[str]) -> None:
    if not isinstance(items, list):
        return
    ids = [item.get("id") for item in items if isinstance(item, dict)]
    duplicates = sorted({item for item in ids if ids.count(item) > 1 and isinstance(item, str)})
    if duplicates:
        errors.append(f"{label} contains duplicate evidence request ids: {', '.join(duplicates)}")


def _check_receipt(
    slot: str,
    receipt: Any,
    payload: Mapping[str, Any],
    errors: List[str],
    *,
    plan_effort: str = "high",
    verification_authority: str = "SOL",
    strict: bool = True,
    warnings: Optional[List[str]] = None,
) -> None:
    if not isinstance(receipt, dict):
        errors.append(f"dispatch.{slot} must be a receipt object")
        return
    receipt_id = receipt.get("agent_id")
    payload_id = payload.get("agent_id")
    if receipt_id != payload_id:
        errors.append(
            f"{slot} payload agent_id {payload_id!r} does not match "
            f"dispatch.{slot}.agent_id {receipt_id!r}"
        )
    role = receipt.get("role")
    normalized_role = role.upper().replace("-", "_").replace(" ", "_") if isinstance(role, str) else ""
    expected_roles = ASTRA_ROLES if slot == "plan" else LUNA_ROLES if slot == "execution" else (
        LUNA_ROLES if verification_authority == "LUNA" else SOL_ROLES
    )
    if normalized_role not in expected_roles:
        expected = ", ".join(sorted(expected_roles))
        errors.append(f"dispatch.{slot} has wrong role {role!r}; expected {expected}")
    model = receipt.get("model")
    effort = receipt.get("reasoning_effort")
    metadata_issues: List[str] = []
    if slot == "plan":
        if model != "gpt-6-astra":
            metadata_issues.append(
                f"dispatch.{slot} must use model gpt-6-astra, got {model!r}"
            )
        if effort != plan_effort:
            metadata_issues.append(
                f"dispatch.{slot} must use reasoning_effort {plan_effort}, got {effort!r}"
            )
    elif slot == "verification":
        expected_model = "gpt-5.6-luna" if verification_authority == "LUNA" else "gpt-5.6-sol"
        expected_effort = "max" if verification_authority == "LUNA" else "high"
        if model != expected_model:
            metadata_issues.append(
                f"dispatch.{slot} must use model {expected_model}, got {model!r}"
            )
        if effort != expected_effort:
            metadata_issues.append(
                f"dispatch.{slot} must use reasoning_effort {expected_effort}, got {effort!r}"
            )
    else:
        if model != "gpt-5.6-luna":
            metadata_issues.append(
                f"dispatch.execution must use model gpt-5.6-luna, got {model!r}"
            )
        if effort != "max":
            metadata_issues.append(
                f"dispatch.execution must use reasoning_effort max, got {effort!r}"
            )
    if receipt.get("source") != "host":
        metadata_issues.append(f"dispatch.{slot}.source must be 'host'")
    if receipt.get("confirmed") is not True:
        metadata_issues.append(f"dispatch.{slot}.confirmed must be true")
    if metadata_issues:
        if strict:
            errors.extend(metadata_issues)
        elif warnings is not None:
            warnings.extend(metadata_issues)


def _validate_plan_gate_components(
    gate: Mapping[str, Any], errors: List[str], root: Path | str
) -> None:
    """Validate the packet, ASTRA plan, and approval bindings in a paused gate."""

    packet = gate.get("task_packet")
    plan = gate.get("plan")
    routing = gate.get("routing_decision")
    baseline = gate.get("baseline_snapshot")
    approval = gate.get("approval")

    errors.extend(validate_instance("task-packet", packet, root))
    errors.extend(validate_instance("astra-plan", plan, root))
    errors.extend(validate_instance("routing-decision", routing, root))

    if not all(isinstance(value, Mapping) for value in (packet, plan, routing, baseline, approval)):
        return

    if plan.get("run_id") != gate.get("run_id"):
        errors.append("plan.run_id does not match plan-gate.run_id")
    if packet.get("run_id") != gate.get("run_id"):
        errors.append("task_packet.run_id does not match plan-gate.run_id")
    if packet.get("plan_id") != plan.get("plan_id"):
        errors.append("plan-gate requires task_packet.plan_id to match plan.plan_id")
    if approval.get("run_id") != gate.get("run_id"):
        errors.append("approval.run_id does not match plan-gate.run_id")
    if approval.get("plan_id") != plan.get("plan_id"):
        errors.append("approval.plan_id does not match plan.plan_id")

    _check_packet_alignment(gate, plan, errors, plan_label="ASTRA plan")
    _check_receipt(
        "plan",
        gate.get("dispatch", {}).get("plan"),
        plan,
        errors,
        plan_effort="medium",
    )

    try:
        selected = select_dispatch_mode(routing).get("dispatch_mode")
    except ContractError as exc:
        errors.append(f"plan-gate routing decision is invalid: {exc}")
        selected = None
    if selected != gate.get("dispatch_mode"):
        errors.append(
            "plan-gate.dispatch_mode does not match routing decision: "
            f"expected {selected!r}, got {gate.get('dispatch_mode')!r}"
        )
    if selected == "FAST":
        errors.append("plan-gate cannot use the automatic FAST route")

    intent = gate.get("intent")
    expected_decision = "IMPLEMENT" if intent == "change" else "INVESTIGATE_MORE"
    if plan.get("decision") != expected_decision:
        errors.append(
            f"plan-gate requires ASTRA plan decision {expected_decision!r}; "
            f"got {plan.get('decision')!r}"
        )

    try:
        expected = approval_bindings(plan, packet, baseline)
    except ContractError as exc:
        errors.append(f"cannot compute plan-gate approval bindings: {exc}")
        return
    for key, value in expected.items():
        if approval.get(key) != value:
            errors.append(f"approval.{key} does not match the immutable plan-gate input")


def _check_command_links(commands: Any, errors: List[str]) -> Tuple[Dict[str, Mapping[str, Any]], set[str]]:
    if not isinstance(commands, list):
        errors.append("result.commands must be an array")
        return {}, set()
    by_id: Dict[str, Mapping[str, Any]] = {}
    positions: Dict[str, int] = {}
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            continue
        command_id = command.get("id")
        if not isinstance(command_id, str):
            continue
        if command_id in by_id:
            errors.append(f"result.commands contains duplicate id {command_id!r}")
        else:
            by_id[command_id] = command
            positions[command_id] = index

    resolved_failures: set[str] = set()

    def target(command_id: str, source_id: str, relation: str) -> Optional[Mapping[str, Any]]:
        if command_id not in by_id:
            errors.append(f"command {source_id!r} has nonexistent {relation} command {command_id!r}")
            return None
        return by_id[command_id]

    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            continue
        command_id = command.get("id")
        if not isinstance(command_id, str) or command_id not in positions:
            continue
        phase = command.get("phase")
        exit_code = command.get("exit_code")
        resolved_by = command.get("resolved_by")
        supersedes = command.get("supersedes")
        if resolved_by is not None:
            if phase != "verification" or exit_code == 0:
                errors.append(f"command {command_id!r} resolved_by is only valid on a failed verification")
            elif not isinstance(resolved_by, str):
                errors.append(f"command {command_id!r}.resolved_by must be a command id")
            else:
                later = target(resolved_by, command_id, "resolved_by")
                if later is not None:
                    later_index = positions[resolved_by]
                    if later_index <= index:
                        errors.append(f"command {command_id!r}.resolved_by must point to a later command")
                    if later.get("phase") != "verification" or later.get("exit_code") != 0:
                        errors.append(f"command {command_id!r}.resolved_by must point to a passing verification")
                    if later.get("command") != command.get("command"):
                        errors.append(f"command {command_id!r}.resolved_by must use the same command text")
                    else:
                        resolved_failures.add(command_id)
        if supersedes is not None:
            if phase != "verification" or exit_code != 0:
                errors.append(f"command {command_id!r}.supersedes is only valid on a passing verification")
            elif not isinstance(supersedes, str):
                errors.append(f"command {command_id!r}.supersedes must be a command id")
            else:
                earlier = target(supersedes, command_id, "supersedes")
                if earlier is not None:
                    earlier_index = positions[supersedes]
                    if earlier_index >= index:
                        errors.append(f"command {command_id!r}.supersedes must point to an earlier command")
                    if earlier.get("phase") != "verification" or earlier.get("exit_code") == 0:
                        errors.append(f"command {command_id!r}.supersedes must point to a failed verification")
                    if earlier.get("command") != command.get("command"):
                        errors.append(f"command {command_id!r}.supersedes must use the same command text")
                    else:
                        resolved_failures.add(supersedes)

    for command in commands:
        if not isinstance(command, dict):
            continue
        if command.get("phase") == "verification" and command.get("exit_code") != 0:
            command_id = command.get("id")
            if isinstance(command_id, str) and command_id not in resolved_failures:
                # A failed verification remains in history, but it blocks DONE
                # until an explicit valid link resolves it.
                continue
    return by_id, resolved_failures


def _check_packet_alignment(
    bundle: Mapping[str, Any],
    plan: Mapping[str, Any],
    errors: List[str],
    plan_label: str = "ASTRA plan",
) -> Optional[str]:
    packet = bundle.get("task_packet")
    candidates = []
    for label, value in (
        ("bundle.intent", bundle.get("intent")),
        ("plan.intent", plan.get("intent")),
        ("task_packet.intent", packet.get("intent") if isinstance(packet, dict) else None),
    ):
        if value is not None:
            if value not in INTENTS:
                errors.append(f"{label} must be one of {', '.join(sorted(INTENTS))}")
            else:
                candidates.append((label, value))
    required_intents = {
        "bundle.intent": bundle.get("intent"),
        "plan.intent": plan.get("intent"),
        "task_packet.intent": packet.get("intent") if isinstance(packet, dict) else None,
    }
    for label, value in required_intents.items():
        if value is None:
            errors.append(f"{label} is required; completion bundles cannot default to change")
    if candidates:
        first = candidates[0][1]
        for label, value in candidates[1:]:
            if value != first:
                errors.append(f"intent mismatch: {candidates[0][0]}={first!r}, {label}={value!r}")
        intent = first
    else:
        intent = "__missing__"

    if isinstance(packet, dict):
        packet_constraints = packet.get("constraints", [])
        plan_constraints = plan.get("constraints", [])
        if isinstance(packet_constraints, list) and isinstance(plan_constraints, list):
            missing = [item for item in packet_constraints if item not in plan_constraints]
            if missing:
                errors.append(
                    f"{plan_label} does not preserve packet constraints: "
                    + "; ".join(str(item) for item in missing)
                )
        packet_run_id = packet.get("run_id")
        if packet_run_id is not None and packet_run_id != bundle.get("run_id"):
            errors.append("task_packet.run_id does not match bundle.run_id")
    return intent


def _fast_plan_view(
    bundle: Mapping[str, Any], errors: List[str]
) -> Dict[str, Any]:
    """Build the controller's view of a FAST packet without fabricating ASTRA."""

    packet = bundle.get("task_packet")
    if not isinstance(packet, Mapping):
        errors.append("FAST bundle task_packet must be an object")
        return {}
    plan_id = packet.get("plan_id")
    if not _meaningful(plan_id):
        errors.append("FAST task_packet.plan_id must be a meaningful controller-issued id")
    intent = packet.get("intent")
    decision = "IMPLEMENT" if intent == "change" else "INVESTIGATE_MORE"
    return {
        "run_id": bundle.get("run_id"),
        "plan_id": plan_id,
        "intent": intent,
        "decision": decision,
        "decision_objective": packet.get("decision_objective"),
        "constraints": packet.get("constraints", []),
        "change_scope": packet.get("execution_scope", []),
        "acceptance_criteria": packet.get("acceptance_criteria", []),
        "verification_plan": packet.get("verification_plan", []),
        "observation_plan": packet.get("observation_plan", []),
        "evidence_requests": [],
    }


def _check_fast_bundle(
    bundle: Mapping[str, Any],
    plan: Mapping[str, Any],
    result: Mapping[str, Any],
    verification: Mapping[str, Any],
    errors: List[str],
) -> None:
    """Enforce the shorter FAST contract and its escalation boundary."""

    packet = bundle.get("task_packet")
    routing = bundle.get("routing_decision")
    if not isinstance(packet, Mapping):
        return
    if not isinstance(routing, Mapping):
        errors.append("FAST bundle requires routing_decision")
        return

    try:
        selected = select_dispatch_mode(routing).get("dispatch_mode")
    except ContractError as exc:
        errors.append(f"FAST routing decision is invalid: {exc}")
        selected = None
    if selected != "FAST":
        errors.append(
            f"FAST bundle routing_decision does not qualify for FAST (selected {selected!r})"
        )
    if routing.get("intent") != bundle.get("intent"):
        errors.append("FAST routing_decision.intent does not match bundle.intent")
    if routing.get("intent") != "change" or routing.get("source_mutation") is not True:
        errors.append("FAST is restricted to source-mutating change intent")

    packet_scope = set(packet.get("execution_scope", []))
    routing_scope = set(routing.get("changed_paths", []))
    if packet_scope != routing_scope:
        errors.append(
            "FAST execution_scope must exactly match routing_decision.changed_paths"
        )
    result_paths = set(result.get("changed_paths", []))
    if not result_paths.issubset(packet_scope):
        errors.append("FAST result.changed_paths exceeds the frozen execution_scope")

    packet_plan_id = packet.get("plan_id")
    if result.get("plan_id") != packet_plan_id:
        errors.append("FAST result.plan_id does not match task_packet.plan_id")
    if verification.get("plan_id") != packet_plan_id:
        errors.append("FAST verification.plan_id does not match task_packet.plan_id")
    if plan.get("plan_id") != packet_plan_id:
        errors.append("FAST effective plan id does not match task_packet.plan_id")

    attempts = verification.get("attempts")
    limits = verification.get("limits")
    if isinstance(attempts, Mapping) and attempts.get("astra_plans") != 0:
        errors.append("FAST verification.attempts.astra_plans must be 0")
    if isinstance(limits, Mapping):
        if limits.get("max_astra_plans") != 0:
            errors.append("FAST verification.limits.max_astra_plans must be 0")
        sol_limit = limits.get("max_sol_verifications")
        if not isinstance(sol_limit, int) or sol_limit > 2:
            errors.append("FAST allows at most one repair cycle: max_sol_verifications must be 2 or less")


def _check_approved_plan_fast_bundle(
    bundle: Mapping[str, Any],
    plan: Mapping[str, Any],
    result: Mapping[str, Any],
    verification: Mapping[str, Any],
    errors: List[str],
) -> None:
    """Enforce execution against one user-approved ASTRA plan."""

    packet = bundle.get("task_packet")
    routing = bundle.get("routing_decision")
    approval = bundle.get("approval")
    baseline = bundle.get("baseline_snapshot")
    if not all(
        isinstance(value, Mapping)
        for value in (packet, routing, approval, baseline)
    ):
        return

    if bundle.get("dispatch_mode") not in {"STANDARD", "DEEP"}:
        errors.append("APPROVED_PLAN_FAST requires an originating STANDARD or DEEP route")
    try:
        selected = select_dispatch_mode(routing).get("dispatch_mode")
    except ContractError as exc:
        errors.append(f"APPROVED_PLAN_FAST routing decision is invalid: {exc}")
        selected = None
    if selected != bundle.get("dispatch_mode"):
        errors.append(
            "APPROVED_PLAN_FAST dispatch_mode does not match routing decision: "
            f"expected {selected!r}, got {bundle.get('dispatch_mode')!r}"
        )
    if bundle.get("intent") != "change" or routing.get("intent") != "change":
        errors.append("APPROVED_PLAN_FAST is restricted to change intent")
    if routing.get("source_mutation") is not True:
        errors.append("APPROVED_PLAN_FAST requires source-mutating routing")
    if plan.get("decision") != "IMPLEMENT":
        errors.append("APPROVED_PLAN_FAST requires an ASTRA IMPLEMENT plan")

    plan_scope = set(plan.get("change_scope", []))
    packet_scope = set(packet.get("execution_scope", []))
    routing_scope = set(routing.get("changed_paths", []))
    if not plan_scope:
        errors.append("APPROVED_PLAN_FAST requires a nonempty approved plan scope")
    if packet_scope != plan_scope:
        errors.append("approved task_packet.execution_scope must equal plan.change_scope")
    if routing_scope != plan_scope:
        errors.append("approved plan scope must equal routing_decision.changed_paths")
    result_paths = set(result.get("changed_paths", []))
    if not result_paths.issubset(plan_scope):
        errors.append("APPROVED_PLAN_FAST result.changed_paths exceeds approved plan scope")

    if packet.get("plan_id") != plan.get("plan_id"):
        errors.append("approved task_packet.plan_id does not match plan.plan_id")
    if approval.get("run_id") != bundle.get("run_id"):
        errors.append("approval.run_id does not match bundle.run_id")
    if approval.get("plan_id") != plan.get("plan_id"):
        errors.append("approval.plan_id does not match plan.plan_id")
    if approval.get("state") != "APPROVED":
        errors.append("APPROVED_PLAN_FAST requires approval.state APPROVED")
    if approval.get("decision") != "APPROVE_IMPLEMENTATION":
        errors.append("APPROVED_PLAN_FAST requires approval decision APPROVE_IMPLEMENTATION")
    if approval.get("actor") != "USER":
        errors.append("APPROVED_PLAN_FAST requires approval.actor USER")

    try:
        expected = approval_bindings(plan, packet, baseline)
    except ContractError as exc:
        errors.append(f"cannot compute approval bindings: {exc}")
        expected = {}
    for key, value in expected.items():
        if approval.get(key) != value:
            errors.append(f"approval.{key} does not match the approved immutable input")

    attempts = verification.get("attempts")
    limits = verification.get("limits")
    if isinstance(attempts, Mapping) and attempts.get("astra_plans") != 1:
        errors.append("APPROVED_PLAN_FAST must record exactly one ASTRA plan attempt")
    if isinstance(limits, Mapping):
        if limits.get("max_astra_plans") != 1:
            errors.append("APPROVED_PLAN_FAST must set max_astra_plans to 1")
        sol_limit = limits.get("max_sol_verifications")
        if not isinstance(sol_limit, int) or sol_limit > 2:
            errors.append("APPROVED_PLAN_FAST allows at most one repair cycle")


def _check_verification_budget(
    verification: Mapping[str, Any],
    errors: List[str],
    *,
    profile: str = "FULL",
) -> None:
    """Reject counter overflow and profile-specific runaway verification."""

    attempts = verification.get("attempts")
    limits = verification.get("limits")
    if not isinstance(attempts, Mapping) or not isinstance(limits, Mapping):
        return
    authority = verification.get("authority")
    verification_pairs = (
        ("luna_verifications", "max_luna_verifications")
        if authority == "LUNA"
        else ("sol_verifications", "max_sol_verifications")
    )
    pairs = (
        verification_pairs,
        ("luna_attempts", "max_luna_attempts"),
        ("astra_plans", "max_astra_plans"),
    )
    for count_key, limit_key in pairs:
        count = attempts.get(count_key)
        limit = limits.get(limit_key)
        if isinstance(count, int) and isinstance(limit, int) and count > limit:
            errors.append(
                f"verification.{count_key} cannot exceed verification.{limit_key}"
            )
    state = verification.get("state")
    verification_count_key, verification_limit_key = verification_pairs
    sol_count = attempts.get(verification_count_key)
    sol_limit = limits.get(verification_limit_key)
    if (
        state not in {"DONE", "BLOCKED"}
        and isinstance(sol_count, int)
        and isinstance(sol_limit, int)
        and sol_count >= sol_limit
    ):
        errors.append(
            f"verification at the {authority or 'verification'} ceiling must be BLOCKED or a valid DONE"
        )

    if profile not in VERIFICATION_PROFILES:
        errors.append(
            f"verification profile must be one of {', '.join(VERIFICATION_PROFILES)}"
        )
        return

    # BALANCED and QUICK deliberately allow one repair cycle.  A larger
    # budget silently recreates the slow, open-ended loop these profiles are
    # intended to avoid.  DEEP/FULL retains the historical caller-selected
    # limits.
    bounded_limits = {
        "max_luna_attempts": limits.get("max_luna_attempts"),
        "max_astra_plans": limits.get("max_astra_plans"),
    }
    if authority == "LUNA":
        bounded_limits["max_luna_verifications"] = limits.get("max_luna_verifications")
    else:
        bounded_limits["max_sol_verifications"] = limits.get("max_sol_verifications")
    if profile in {"BALANCED", "QUICK"}:
        ceilings = {
            "max_luna_attempts": 2,
            "max_astra_plans": 1,
            "max_sol_verifications": 2,
            "max_luna_verifications": 2,
        }
        for limit_key, ceiling in ceilings.items():
            value = bounded_limits.get(limit_key)
            if isinstance(value, int) and value > ceiling:
                errors.append(
                    f"{profile} verification allows at most {ceiling} for verification.{limit_key}"
                )


def check_run(
    bundle_path: Path | str | Mapping[str, Any], root: Path | str
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Validate a complete bundle and compare its snapshot with current source."""

    bundle = (
        dict(bundle_path)
        if isinstance(bundle_path, Mapping)
        else _load_bundle(bundle_path)
    )
    errors: List[str] = []
    errors.extend(validate_instance("run-bundle", bundle))
    if errors:
        return False, errors, {}

    workflow_variant = bundle.get("workflow_variant")
    fast = workflow_variant == "fast_luna_sol"
    approved_plan_fast = workflow_variant == APPROVED_PLAN_FAST_VARIANT
    echo = workflow_variant == ASTRA_HIGH_LUNA_ECHO_VARIANT
    verification_profile = bundle.get("verification_profile") or "FULL"
    strict_verification = verification_profile == "FULL"
    receipt_warnings: List[str] = []
    plan = (
        _fast_plan_view(bundle, errors)
        if fast
        else bundle["plan"]
    )
    result = bundle["result"]
    verification = bundle["verification"]
    if not fast:
        errors.extend(validate_instance("astra-plan", plan))
    errors.extend(validate_instance("luna-result", result))
    verification_schema = "luna-verification" if echo else "sol-verification"
    errors.extend(validate_instance(verification_schema, verification))
    if isinstance(bundle.get("task_packet"), dict):
        errors.extend(validate_instance("task-packet", bundle["task_packet"]))
    _check_verification_budget(
        verification,
        errors,
        profile=verification_profile,
    )
    if fast:
        _check_fast_bundle(bundle, plan, result, verification, errors)
    elif approved_plan_fast:
        _check_approved_plan_fast_bundle(bundle, plan, result, verification, errors)
    else:
        attempts = verification.get("attempts")
        limits = verification.get("limits")
        if isinstance(attempts, Mapping) and attempts.get("astra_plans", 0) < 1:
            errors.append("workflow requires at least one ASTRA plan attempt")
        if isinstance(limits, Mapping) and limits.get("max_astra_plans", 0) < 1:
            errors.append("workflow requires a positive max_astra_plans limit")

    run_id = bundle.get("run_id")
    plan_id = plan.get("plan_id")
    if not fast and plan.get("run_id") != run_id:
        errors.append("plan.run_id does not match bundle.run_id")
    if result.get("run_id") != run_id:
        errors.append("result.run_id does not match bundle.run_id")
    if verification.get("run_id") != run_id:
        errors.append("verification.run_id does not match bundle.run_id")
    if result.get("plan_id") != plan_id:
        errors.append("result.plan_id does not match plan.plan_id")
    if verification.get("plan_id") != plan_id:
        errors.append("verification.plan_id does not match plan.plan_id")

    dispatch = bundle.get("dispatch", {})
    if isinstance(dispatch, dict):
        if not fast:
            legacy_plan = workflow_variant in {
                LEGACY_FULL_VARIANT,
                APPROVED_PLAN_FAST_VARIANT,
                PLAN_APPROVAL_VARIANT,
            } or workflow_variant is None
            _check_receipt(
                "plan",
                dispatch.get("plan"),
                plan,
                errors,
                plan_effort="medium" if legacy_plan else "high",
                strict=strict_verification,
                warnings=receipt_warnings,
            )
        _check_receipt(
            "execution",
            dispatch.get("execution"),
            result,
            errors,
            strict=strict_verification,
            warnings=receipt_warnings,
        )
        _check_receipt(
            "verification",
            dispatch.get("verification"),
            verification,
            errors,
            verification_authority="LUNA" if echo else "SOL",
            strict=strict_verification,
            warnings=receipt_warnings,
        )
        slot_ids = {
            slot: dispatch.get(slot, {}).get("agent_id")
            for slot in ("plan", "execution", "verification")
            if isinstance(dispatch.get(slot), dict)
        }
        if slot_ids.get("plan") == slot_ids.get("execution") and slot_ids.get("plan"):
            errors.append("one agent_id cannot occupy both ASTRA plan and LUNA execution slots")
        if slot_ids.get("verification") == slot_ids.get("execution") and slot_ids.get("verification"):
            errors.append("one agent_id cannot occupy both verification and LUNA execution slots")
        if slot_ids.get("verification") == slot_ids.get("plan") and slot_ids.get("verification"):
            errors.append("one agent_id cannot occupy both verification and ASTRA plan slots")

    plan_ids = _criterion_ids(plan.get("acceptance_criteria"), "plan.acceptance_criteria", errors)
    result_ids = _criterion_ids(result.get("criteria_evidence"), "result.criteria_evidence", errors)
    verification_ids = _criterion_ids(verification.get("criteria"), "verification.criteria", errors)
    if result_ids != plan_ids:
        errors.append(
            "result criteria coverage differs from plan: "
            f"missing={sorted(plan_ids - result_ids)}, unknown={sorted(result_ids - plan_ids)}"
        )
    if verification_ids != plan_ids:
        errors.append(
            "verification criteria coverage differs from plan: "
            f"missing={sorted(plan_ids - verification_ids)}, "
            f"unknown={sorted(verification_ids - plan_ids)}"
        )
    planned_observation_ids = _observation_ids(
        plan.get("observation_plan"), "plan.observation_plan", errors
    )
    result_observation_ids = _observation_ids(
        result.get("observations"), "result.observations", errors
    )
    if planned_observation_ids != result_observation_ids:
        errors.append(
            "observation coverage differs from plan: "
            f"missing={sorted(planned_observation_ids - result_observation_ids)}, "
            f"unknown={sorted(result_observation_ids - planned_observation_ids)}"
        )
    _request_ids(plan.get("evidence_requests"), "plan.evidence_requests", errors)
    _request_ids(verification.get("evidence_requests"), "verification.evidence_requests", errors)

    intent = _check_packet_alignment(
        bundle,
        plan,
        errors,
        plan_label="FAST packet" if fast else "ASTRA plan",
    )
    if (
        workflow_variant == ASTRA_HIGH_LUNA_SOL_VARIANT
        and bundle.get("verification_profile") is not None
        and isinstance(bundle.get("routing_decision"), Mapping)
    ):
        try:
            routed_profile = select_dispatch_mode(
                bundle["routing_decision"]
            ).get("verification_profile")
            if routed_profile != verification_profile:
                errors.append(
                    "verification_profile does not match the selected dispatch mode: "
                    f"expected {routed_profile!r}, got {verification_profile!r}"
                )
        except ContractError as exc:
            errors.append(f"cannot derive verification profile from routing decision: {exc}")
    final_snapshot = bundle.get("snapshot")
    result_snapshot = result.get("snapshot")
    verification_snapshot = verification.get("snapshot")
    snapshot_parts = (final_snapshot, result_snapshot, verification_snapshot)
    present_snapshot_parts = [value is not None for value in snapshot_parts]
    snapshot_complete = all(present_snapshot_parts)
    snapshot_required = strict_verification or intent != "change"
    if snapshot_required and not isinstance(final_snapshot, dict):
        errors.append(
            f"{verification_profile} verification requires bundle.snapshot"
        )
    if snapshot_required and not isinstance(result_snapshot, dict):
        errors.append(
            f"{verification_profile} verification requires result.snapshot"
        )
    if snapshot_required and not isinstance(verification_snapshot, dict):
        errors.append(
            f"{verification_profile} verification requires verification.snapshot"
        )
    if any(present_snapshot_parts) and not snapshot_complete:
        errors.append(
            "bundle, result, and verification snapshots must either all be present or all be omitted"
        )
    if snapshot_complete:
        if final_snapshot != result_snapshot:
            errors.append("bundle.snapshot must equal result.snapshot")
        if final_snapshot != verification_snapshot:
            errors.append("bundle.snapshot must equal verification.snapshot")
    baseline_snapshot = bundle.get("baseline_snapshot")
    if isinstance(final_snapshot, dict) and isinstance(baseline_snapshot, dict):
        if final_snapshot.get("kind") != baseline_snapshot.get("kind"):
            errors.append("snapshot and baseline_snapshot must use the same kind")
    if snapshot_required and not isinstance(baseline_snapshot, dict):
        errors.append(
            f"{verification_profile} verification requires baseline_snapshot"
        )

    changed_paths = result.get("changed_paths", [])
    if snapshot_complete and isinstance(final_snapshot, dict) and final_snapshot.get("kind") == "scoped":
        snapshot_paths = set(final_snapshot.get("paths", []))
        for changed_path in changed_paths if isinstance(changed_paths, list) else []:
            try:
                normalized = _relative_path(changed_path, "result.changed_paths entry")
            except ContractError as exc:
                errors.append(str(exc))
                continue
            if normalized not in snapshot_paths:
                errors.append(
                    f"scoped snapshot omits result.changed_paths entry {normalized!r}"
                )

    command_by_id, resolved_failures = _check_command_links(result.get("commands"), errors)
    verification_failures = {
        command_id
        for command_id, command in command_by_id.items()
        if command.get("phase") == "verification" and command.get("exit_code") != 0
    }
    unresolved_verification = verification_failures - resolved_failures

    if verification.get("state") == "DONE":
        expected_decision = "IMPLEMENT" if intent == "change" else "INVESTIGATE_MORE"
        if plan.get("decision") != expected_decision:
            errors.append(
                f"DONE requires approved plan decision {expected_decision} for intent {intent!r}; "
                f"got {plan.get('decision')!r}"
            )
        if result.get("status") != "IMPLEMENTATION_COMPLETE":
            errors.append("DONE requires result.status IMPLEMENTATION_COMPLETE")
        if result.get("failures_or_unknowns"):
            errors.append("DONE requires result.failures_or_unknowns to be empty")
        for label, items in (
            ("result.criteria_evidence", result.get("criteria_evidence", [])),
            ("verification.criteria", verification.get("criteria", [])),
        ):
            for item in items:
                if item.get("status") != "PASS":
                    errors.append(f"DONE requires {label} {item.get('id')!r} to be PASS")
                if not _meaningful(item.get("evidence")):
                    errors.append(f"DONE requires nonempty evidence for {label} {item.get('id')!r}")
        verification_commands = [
            command
            for command in result.get("commands", [])
            if command.get("phase") == "verification"
        ]
        observations = result.get("observations", [])
        if not verification_commands and not observations:
            errors.append("DONE requires at least one actual verification command or observation")
        if unresolved_verification:
            errors.append(
                "DONE is blocked by unresolved failed verification commands: "
                + ", ".join(sorted(unresolved_verification))
            )
        required_verifications = plan.get("verification_plan", [])
        for required in required_verifications if isinstance(required_verifications, list) else []:
            matching = [
                command
                for command in verification_commands
                if command.get("command") == required
            ]
            if not matching:
                errors.append(
                    f"DONE is missing required verification command {required!r}"
                )
            elif not any(
                command.get("exit_code") == 0
                and command.get("id") not in unresolved_verification
                for command in matching
            ):
                errors.append(
                    f"DONE has no passing resolved run for required verification {required!r}"
                )
        observation_by_id = {
            item.get("id"): item
            for item in observations
            if isinstance(item, dict)
        }
        for planned in plan.get("observation_plan", []) if isinstance(plan.get("observation_plan"), list) else []:
            observation_id = planned.get("id")
            observed = observation_by_id.get(observation_id)
            if observed is None:
                errors.append(f"DONE is missing planned observation {observation_id!r}")
            elif observed.get("status") != "PASS":
                errors.append(f"DONE requires planned observation {observation_id!r} to be PASS")
            elif not _meaningful(observed.get("evidence")):
                errors.append(f"DONE requires evidence for planned observation {observation_id!r}")

    # FULL (and all non-change runs) retain the expensive freshness proof.
    # BALANCED/QUICK change runs may omit fingerprints; if they provide one,
    # the cross-artifact equality and scoped-path checks above still apply.
    if strict_verification or intent != "change":
        if not isinstance(final_snapshot, dict):
            errors.append("cannot recompute current code snapshot without bundle.snapshot")
        else:
            try:
                current = _snapshot_current(final_snapshot, root)
                if current != final_snapshot:
                    if final_snapshot.get("kind") == "git" and set(current.get("paths", [])) != set(final_snapshot.get("paths", [])):
                        errors.append(
                            "stale Git snapshot scope: caller-supplied paths do not cover the "
                            "complete current tracked/nonignored worktree"
                        )
                    errors.append("stale code snapshot: current source differs from bundle.snapshot")
            except ContractError as exc:
                errors.append(f"cannot recompute current code snapshot: {exc}")

    # A baseline is especially important for review/investigation/explanation
    # runs: changed_paths can be falsely empty, so compare the whole declared
    # baseline to the current source as well.
    if intent in {"investigate", "review", "explain"}:
        if changed_paths:
            errors.append(f"non-change intent {intent!r} cannot report changed_paths")
        if bundle.get("source_mutation") is True:
            errors.append(f"non-change intent {intent!r} cannot report source_mutation")
        if not isinstance(baseline_snapshot, dict):
            errors.append("read-only run requires baseline_snapshot")
        else:
            try:
                current_baseline = _snapshot_current(baseline_snapshot, root)
                if current_baseline != baseline_snapshot:
                    errors.append("read-only source mutation detected against baseline_snapshot")
                if final_snapshot != baseline_snapshot:
                    errors.append("read-only run must retain an unchanged final snapshot")
            except ContractError as exc:
                errors.append(f"cannot recompute baseline_snapshot: {exc}")

    summary = {
        "valid": not errors,
        "run_id": run_id,
        "plan_id": plan_id,
        "state": verification.get("state"),
        "intent": intent,
        "verification_profile": verification_profile,
        "snapshot": final_snapshot,
        "resolved_verification_failures": sorted(resolved_failures),
        "warnings": sorted(set(receipt_warnings)),
    }
    return not errors, errors, summary


def _load_bundle(path: Path | str) -> Dict[str, Any]:
    candidate = Path(path)
    if candidate.is_dir():
        for name in ("run-bundle.json", "bundle.json", "plan-gate.json"):
            nested = candidate / name
            if nested.is_file():
                candidate = nested
                break
        else:
            raise ContractError(
                f"bundle directory {candidate} must contain run-bundle.json, bundle.json, or plan-gate.json"
            )
    value = load_json(candidate)
    if not isinstance(value, dict):
        raise ContractError(f"run bundle {candidate} must be a JSON object")
    return value


def check_plan_gate(
    gate_path: Path | str | Mapping[str, Any], root: Path | str
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Validate a paused ASTRA plan and prove its baseline is still fresh."""

    gate = dict(gate_path) if isinstance(gate_path, Mapping) else _load_bundle(gate_path)
    errors = validate_instance("plan-gate", gate)
    if errors:
        return False, errors, {}

    baseline = gate["baseline_snapshot"]
    try:
        current = _snapshot_current(baseline, root)
        if current != baseline:
            errors.append(
                "stale plan-gate baseline: repository changed before user approval"
            )
    except ContractError as exc:
        errors.append(f"cannot recompute plan-gate baseline: {exc}")

    summary = {
        "valid": not errors,
        "run_id": gate.get("run_id"),
        "plan_id": gate.get("plan", {}).get("plan_id"),
        "state": gate.get("approval", {}).get("state"),
        "next_action": "USER_APPROVAL" if not errors else "REPLAN",
        "dispatch_mode": gate.get("dispatch_mode"),
        "workflow_variant": gate.get("workflow_variant"),
    }
    return not errors, errors, summary


def next_stage(
    artifact: Mapping[str, Any],
    handoff_count: int = 0,
    max_handoffs: int = 5,
    intent: Optional[str] = None,
    changed_paths: Optional[Sequence[str]] = None,
    source_mutation: Optional[bool] = None,
) -> Dict[str, Any]:
    """Map a SOL verification state to the next bounded stage.

    A legacy ``adjudication`` wrapper may still be inspected for migration
    tooling, but it can never authorize a terminal DONE transition.
    """

    if handoff_count < 0:
        raise ContractError("handoff_count cannot be negative")
    if max_handoffs <= 0:
        raise ContractError("max_handoffs must be positive")
    if handoff_count > max_handoffs:
        raise ContractError("handoff_count cannot exceed max_handoffs")
    if not isinstance(artifact, Mapping):
        raise ContractError("next-stage artifact must be a JSON object")
    legacy = False
    expected_authority = "SOL"
    if "verification" in artifact and isinstance(artifact.get("verification"), dict):
        verification = artifact["verification"]
        bundle = artifact
        if bundle.get("workflow_variant") == ASTRA_HIGH_LUNA_ECHO_VARIANT:
            expected_authority = "LUNA"
    elif "adjudication" in artifact and isinstance(artifact.get("adjudication"), dict):
        verification = artifact["adjudication"]
        bundle = artifact
        legacy = True
    else:
        verification = artifact
        bundle = {}
        # A direct artifact is canonical only when it identifies SOL as its
        # authority. Bare state objects are retained for transition inspection
        # but may not authorize terminal completion.
        expected_authority = "LUNA" if verification.get("authority") == "LUNA" else "SOL"
        legacy = verification.get("authority") != expected_authority
    state = verification.get("state")
    if state not in STAGE_BY_STATE:
        raise ContractError(f"unsupported verification state {state!r}")

    artifact_intent = intent
    result_payload = (
        bundle.get("result") if isinstance(bundle.get("result"), dict) else
        artifact.get("result") if isinstance(artifact.get("result"), dict) else {}
    )
    for value in (
        bundle.get("intent"),
        verification.get("intent"),
        result_payload.get("intent"),
    ):
        if value is not None:
            if artifact_intent is not None and artifact_intent != value:
                raise ContractError("next-stage intent disagrees with artifact intent")
            artifact_intent = value
    if artifact_intent is None:
        raise ContractError("next-stage requires explicit intent; it cannot default to change")
    if artifact_intent not in INTENTS:
        raise ContractError(f"intent must be one of {', '.join(sorted(INTENTS))}")

    artifact_changed: List[str] = []
    for label, value in (
        ("bundle.changed_paths", bundle.get("changed_paths")),
        ("result.changed_paths", result_payload.get("changed_paths")),
        ("verification.changed_paths", verification.get("changed_paths")),
    ):
        if value is not None:
            if not isinstance(value, list) or not all(isinstance(path, str) for path in value):
                raise ContractError(f"{label} must be a list of strings")
            artifact_changed.extend(value)
    artifact_changed = list(dict.fromkeys(artifact_changed))
    if changed_paths is not None:
        if artifact_changed and set(artifact_changed) != set(changed_paths):
            raise ContractError("next-stage changed_paths disagrees with artifact")
        artifact_changed = list(changed_paths)
    if not isinstance(artifact_changed, list) or not all(isinstance(path, str) for path in artifact_changed):
        raise ContractError("changed_paths must be a list of strings")
    artifact_mutation = source_mutation
    for value in (
        bundle.get("source_mutation"),
        result_payload.get("source_mutation"),
        verification.get("source_mutation"),
    ):
        if value is not None:
            if artifact_mutation is not None and artifact_mutation != value:
                raise ContractError("next-stage source_mutation disagrees with artifact")
            artifact_mutation = value
    artifact_mutation = bool(artifact_mutation) if artifact_mutation is not None else bool(artifact_changed)
    if artifact_intent != "change" and (artifact_changed or artifact_mutation):
        raise ContractError(
            f"non-change intent {artifact_intent!r} rejects changed_paths/source mutation"
        )

    cap_reached = handoff_count >= max_handoffs
    approved_plan_fast = bundle.get("workflow_variant") == APPROVED_PLAN_FAST_VARIANT
    echo = bundle.get("workflow_variant") == ASTRA_HIGH_LUNA_ECHO_VARIANT
    verification_profile = bundle.get("verification_profile") or "FULL"
    if legacy and state == "DONE":
        next_name = "STOP_BLOCKED"
        allowed = False
        reason = f"non-{expected_authority} verification cannot authorize DONE"
    elif cap_reached and state == "DONE":
        # The final SOL verification is already the terminal decision; routing
        # it to STOP does not authorize an additional verifier call.
        next_name = "STOP"
        allowed = True
        reason = "terminal DONE at the handoff cap; no additional call is authorized"
    elif cap_reached:
        next_name = "STOP_BLOCKED"
        allowed = False
        reason = "handoff cap reached; no additional SOL verification call is authorized"
    elif approved_plan_fast and state == "REPLAN":
        next_name = "ASTRA_PLAN_APPROVAL"
        allowed = True
        reason = "approved plan is invalidated; a fresh ASTRA plan and user approval are required"
    elif echo and state == "REPLAN" and verification_profile == "QUICK":
        next_name = "STOP_BLOCKED"
        allowed = False
        reason = "QUICK echo verification does not authorize automatic replanning"
    elif state == "REPLAN" and verification_profile == "BALANCED":
        next_name = "STOP_BLOCKED"
        allowed = False
        reason = "BALANCED verification does not authorize automatic replanning; escalate to FULL"
    elif echo and state == "REPLAN":
        next_name = "ASTRA_PLAN"
        allowed = True
        reason = "echo verification requires a fresh ASTRA plan before execution"
    else:
        next_name = STAGE_BY_STATE[state]
        allowed = state not in {"BLOCKED", "ESCALATE"}
        reason = "state mapping"
        if not allowed:
            reason = "terminal blocked/escalated state"

    return {
        "state": state,
        "next_stage": next_name,
        "allowed": allowed,
        "handoff_count": handoff_count,
        "max_handoffs": max_handoffs,
        "cap_reached": cap_reached,
        "legacy_artifact": legacy,
        "intent": artifact_intent,
        "verification_profile": verification_profile,
        "reason": reason,
    }


def validate_ui_metadata(path: Path | str) -> List[str]:
    """Check YAML shape/nesting without asserting prompt wording."""

    yaml_module = _require_yaml()
    path = Path(path)
    try:
        value = yaml_module.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [f"UI metadata cannot be read: {exc}"]
    except Exception as exc:
        return [f"UI metadata is not valid YAML: {exc}"]
    if not isinstance(value, dict):
        return ["UI metadata must be a YAML mapping"]

    # The host contract uses one explicit interface mapping.  Accepting a flat
    # shape or guessing another nesting level would let a malformed UI file
    # pass unnoticed.
    container = value.get("interface")
    if not isinstance(container, dict):
        return ["UI metadata must contain an interface mapping"]
    errors = []
    for key in ("display_name", "short_description", "default_prompt"):
        if key not in container:
            errors.append(f"UI metadata missing nested field {key!r}")
        elif not _meaningful(container[key]):
            errors.append(f"UI metadata field {key!r} must be a meaningful string")
    return errors


def validate_repository(root: Path | str = ROOT) -> List[str]:
    """Validate active repository structure, schemas, fixtures, and UI shape."""

    root_path = _root_path(root)
    required = [
        "SKILL.md",
        "README.md",
        "LICENSE",
        "agents/openai.yaml",
        "requirements.txt",
        "schemas/task-packet.schema.json",
        "schemas/astra-plan.schema.json",
        "schemas/luna-result.schema.json",
        "schemas/sol-verification.schema.json",
        "schemas/luna-verification.schema.json",
        "schemas/routing-decision.schema.json",
        "schemas/plan-gate.schema.json",
        "schemas/run-bundle.schema.json",
        "scripts/linkedai",
        "scripts/contracts.py",
        "scripts/validate.py",
        "tests/test_repository.py",
        "tests/schemas",
        "tests/routing",
        "tests/fixtures/example-task-packet.json",
    ]
    errors = [f"missing active path: {relative}" for relative in required if not (root_path / relative).exists()]
    for key in ACTIVE_SCHEMAS:
        errors.extend(validate_schema(key, root_path))

    packet_path = root_path / "tests/fixtures/example-task-packet.json"
    if packet_path.is_file():
        try:
            errors.extend(validate_instance("task-packet", load_json(packet_path), root_path))
        except ContractError as exc:
            errors.append(str(exc))

    fixture_roots = [root_path / "tests/fixtures/current-run"]
    for fixture_root in fixture_roots:
        if not fixture_root.is_dir():
            errors.append(f"missing active fixture directory: {fixture_root.relative_to(root_path)}")
            continue
        for fixture in sorted(fixture_root.glob("*.json")):
            try:
                errors.extend(validate_instance("run-bundle", load_json(fixture), root_path))
            except ContractError as exc:
                errors.append(f"{fixture.relative_to(root_path)}: {exc}")

    errors.extend(validate_ui_metadata(root_path / "agents/openai.yaml"))
    return errors


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def _command_check(args: Sequence[str]) -> int:
    tokens = list(args)
    if not tokens:
        raise ContractError(
            "check syntax: check <schema-file> <instance-file> or "
            "check SCHEMA|INSTANCE <name> [instance-file]"
        )
    mode_token = tokens.pop(0)
    mode = mode_token.upper()
    if mode not in {"SCHEMA", "INSTANCE"}:
        # The concise file-oriented form is the public helper API:
        #   check schemas/astra-plan.schema.json run/plan.json
        if len(tokens) != 1:
            raise ContractError(
                "check syntax: check <schema-file> <instance-file> or "
                "check SCHEMA|INSTANCE <name> [instance-file]"
            )
        instance = load_json(tokens[0])
        errors = validate_instance(mode_token, instance)
        if errors:
            _json_print({"valid": False, "kind": "instance", "errors": errors})
            return 1
        _json_print({"valid": True, "kind": "instance", "schema": _schema_key(mode_token), "path": tokens[0]})
        return 0
    if not tokens:
        raise ContractError(f"check {mode} requires a schema name")
    name = tokens.pop(0)
    if mode == "SCHEMA":
        if tokens:
            raise ContractError("check SCHEMA accepts only one schema name")
        errors = validate_schema(name)
        if errors:
            _json_print({"valid": False, "kind": "schema", "errors": errors})
            return 1
        _json_print({"valid": True, "kind": "schema", "schema": _schema_key(name)})
        return 0
    if len(tokens) != 1:
        raise ContractError("check INSTANCE requires a schema name and one JSON file")
    instance = load_json(tokens[0])
    errors = validate_instance(name, instance)
    if errors:
        _json_print({"valid": False, "kind": "instance", "errors": errors})
        return 1
    _json_print({"valid": True, "kind": "instance", "schema": _schema_key(name), "path": tokens[0]})
    return 0


def _command_check_run(args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="contracts.py check-run")
    parser.add_argument("bundle")
    parser.add_argument("--root", default=str(Path.cwd()))
    namespace = parser.parse_args(list(args))
    valid, errors, summary = check_run(namespace.bundle, namespace.root)
    if valid:
        _json_print(summary)
        return 0
    _json_print({"valid": False, "errors": errors, **summary})
    return 1


def _command_check_plan(args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="contracts.py check-plan")
    parser.add_argument("gate")
    parser.add_argument("--root", default=str(Path.cwd()))
    namespace = parser.parse_args(list(args))
    valid, errors, summary = check_plan_gate(namespace.gate, namespace.root)
    if valid:
        _json_print(summary)
        return 0
    _json_print({"valid": False, "errors": errors, **summary})
    return 1


def _command_fingerprint(args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="contracts.py fingerprint")
    parser.add_argument("--root")
    parser.add_argument("--paths", nargs="+")
    namespace = parser.parse_args(list(args))
    if namespace.root is None and not namespace.paths:
        raise ContractError("fingerprint requires --root or --paths")
    if namespace.paths:
        snapshot = fingerprint_paths(namespace.paths, namespace.root or Path.cwd())
    else:
        snapshot = fingerprint_git(namespace.root)
    _json_print(snapshot)
    return 0


def _parse_bool(value: Optional[str]) -> bool:
    if value is None:
        return True
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ContractError(f"invalid boolean value {value!r}")


def _command_dispatch_mode(args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="contracts.py dispatch-mode")
    parser.add_argument("decision")
    parser.add_argument("--current-mode", choices=DISPATCH_MODES)
    namespace = parser.parse_args(list(args))
    decision = load_json(namespace.decision)
    _json_print(select_dispatch_mode(decision, current_mode=namespace.current_mode))
    return 0


def _command_next_stage(args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="contracts.py next-stage")
    parser.add_argument("artifact")
    parser.add_argument("--handoff-count", "--handoffs", type=int, default=0)
    parser.add_argument("--max-handoffs", type=int, default=5)
    parser.add_argument("--intent", choices=sorted(INTENTS))
    parser.add_argument("--changed-path", action="append", dest="changed_paths")
    parser.add_argument("--changed-paths", nargs="*", dest="changed_paths_many")
    parser.add_argument("--source-mutation", nargs="?", const="true")
    namespace = parser.parse_args(list(args))
    artifact = load_json(namespace.artifact)
    changed = namespace.changed_paths
    if namespace.changed_paths_many:
        changed = (changed or []) + namespace.changed_paths_many
    mutation = None
    if namespace.source_mutation is not None:
        mutation = _parse_bool(namespace.source_mutation)
    result = next_stage(
        artifact,
        handoff_count=namespace.handoff_count,
        max_handoffs=namespace.max_handoffs,
        intent=namespace.intent,
        changed_paths=changed,
        source_mutation=mutation,
    )
    _json_print(result)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    tokens = list(argv if argv is not None else sys.argv[1:])
    if not tokens:
        raise ContractError(
            "usage: contracts.py check|check-run|check-plan|fingerprint|dispatch-mode|next-stage ..."
        )
    command = tokens.pop(0).lower()
    if command == "check":
        return _command_check(tokens)
    if command == "check-run":
        return _command_check_run(tokens)
    if command == "check-plan":
        return _command_check_plan(tokens)
    if command == "fingerprint":
        return _command_fingerprint(tokens)
    if command == "dispatch-mode":
        return _command_dispatch_mode(tokens)
    if command == "next-stage":
        return _command_next_stage(tokens)
    raise ContractError(f"unknown contracts command {command!r}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, argparse.ArgumentError) as exc:
        print(f"LinkedAI contracts FAILED: {exc}", file=sys.stderr)
        raise SystemExit(2)
