#!/usr/bin/env python3
"""Summarize offline cumulative token measurements for a LinkedAI run.

The event stream is NDJSON and accepts only these two shapes:

Normalized cumulative measurement::

    {"type":"usage","thread_id":"t1","sequence":2,
     "model":"gpt-6-astra",
     "cumulative":{"input_tokens":120,"output_tokens":18,
                    "cached_input_tokens":90,
                    "reasoning_output_tokens":3}}

Codex app-server notification::

    {"method":"thread/tokenUsage/updated",
     "params":{"threadId":"t1",
       "tokenUsage":{"total":{"inputTokens":120,
                                  "outputTokens":18,
                                  "cachedInputTokens":90,
                                  "reasoningOutputTokens":3,
                                  "totalTokens":138}}}}

``sequence`` or ``timestamp`` may be supplied at the event top level.  If
neither is supplied, input order is used and reported as a limitation.  The
manifest is the only source of selected threads.  Every reported cumulative
delta is latest-counter minus the explicit manifest baseline; updates are
never summed.  Unknown values remain ``null`` rather than becoming zero.

The manifest is JSON with ``run_id``, explicit ``participants`` containing
``thread_id``, ``role`` (``ASTRA``/``LUNA``/``SOL``/``CONTROLLER``), ``model``, and an
optional baseline object.  An optional ``stage_intervals`` array may contain
controller-stamped stage labels, attempts, thread IDs, counter epochs, and
explicit cumulative ``start``/``end`` boundaries.  ``run_complete`` and
``includes_final_response`` must both be true before ``complete_total`` is
emitted.  Stage accounting is separate from participant and role totals.

No broker, API, network, cost, quota, or model-pricing call is made.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import math
import sys
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROLES = ("ASTRA", "LUNA", "SOL", "CONTROLLER")
PARENT = ("input_tokens", "output_tokens")
SUBSETS = ("cached_input_tokens", "reasoning_output_tokens")
COUNTERS = PARENT + SUBSETS + ("total_tokens",)
CODEX_METHOD = "thread/tokenUsage/updated"
STAGE_INTERVALS_KEY = "stage_intervals"
STAGE_MEASURED = "MEASURED"
STAGE_NOT_APPLICABLE = "NOT_APPLICABLE"
STAGE_COVERAGES = ("EXACT", "PARTIAL", "UNAVAILABLE", "RESIDUAL", STAGE_NOT_APPLICABLE)

NORMALIZED_NAMES = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cached_input_tokens": "cached_input_tokens",
    "reasoning_output_tokens": "reasoning_output_tokens",
    "total_tokens": "total_tokens",
}
CODEX_NAMES = {
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cached_input_tokens": "cachedInputTokens",
    "reasoning_output_tokens": "reasoningOutputTokens",
    "total_tokens": "totalTokens",
}


class UsageInputError(ValueError):
    """A manifest or event file could not be read safely."""


class _DuplicateJSONKey(ValueError):
    pass


def _strict_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey("duplicate object key: %s" % key)
        result[key] = value
    return result


def _loads_strict(text: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError("non-standard JSON constant: %s" % value)

    return json.loads(
        text,
        object_pairs_hook=_strict_object,
        parse_constant=reject_constant,
    )


def _add_unique(items: List[str], message: str) -> None:
    if message not in items:
        items.append(message)


def _unique(items: Iterable[str]) -> List[str]:
    result: List[str] = []
    for item in items:
        _add_unique(result, item)
    return result


def _nonnegative_int(value: Any, label: str, errors: List[str]) -> Optional[int]:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _add_unique(errors, "%s must be a nonnegative integer; booleans are invalid" % label)
        return None
    return value


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass
class EventRecord:
    obj: Mapping[str, Any]
    ordinal: int
    source_line: Optional[int] = None


@dataclass
class Participant:
    index: int
    thread_id: Optional[str]
    role: Optional[str]
    model: Optional[str]
    baseline: Dict[str, Optional[int]]
    valid: bool
    issues: List[str] = field(default_factory=list)


@dataclass
class StageInterval:
    interval_id: Optional[str]
    stage: Optional[str]
    attempt: Optional[int]
    thread_id: Optional[str]
    agent_id: Optional[str]
    model: Optional[str]
    effort: Optional[str]
    counter_epoch: Optional[str]
    start: Dict[str, Optional[int]]
    end: Dict[str, Optional[int]]
    coverage: str
    valid: bool
    issues: List[str] = field(default_factory=list)


@dataclass
class Manifest:
    run_id: Optional[str]
    participants: List[Participant]
    run_complete: Optional[bool]
    includes_final_response: Optional[bool]
    stage_intervals: List[StageInterval]
    stage_metadata_present: bool
    errors: List[str]
    limitations: List[str]


@dataclass
class Sample:
    thread_id: str
    role: Optional[str]
    model: Optional[str]
    counters: Dict[str, Optional[int]]
    sequence: Optional[int]
    timestamp: Optional[Tuple[int, Any]]
    ordinal: int
    usable: bool
    problems: List[str]
    source_kind: str

    def identity(self) -> Optional[Tuple[str, Any]]:
        if self.sequence is not None:
            return "sequence", self.sequence
        if self.timestamp is not None:
            return "timestamp", self.timestamp
        return None

    def signature(self) -> Tuple[Any, ...]:
        return (
            tuple(self.counters[counter] for counter in COUNTERS),
            self.role,
            self.model,
        )


def _location(record: EventRecord, message: str) -> str:
    if record.source_line is not None:
        return "line %d: %s" % (record.source_line, message)
    return "event %d: %s" % (record.ordinal + 1, message)


def parse_event_stream(text: str) -> Tuple[List[EventRecord], List[str]]:
    """Parse NDJSON without coercing malformed or unknown data."""

    records: List[EventRecord] = []
    errors: List[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = _loads_strict(line)
        except (ValueError, TypeError) as exc:
            errors.append("line %d is malformed JSON: %s" % (line_number, exc))
            continue
        if not isinstance(value, Mapping):
            errors.append("line %d is not a JSON object" % line_number)
            continue
        records.append(EventRecord(value, len(records), line_number))
    return records, errors


def _timestamp(value: Any) -> Optional[Tuple[int, Any]]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return (0, value) if value >= 0 else None
    if isinstance(value, float):
        return (0, Decimal(str(value))) if math.isfinite(value) and value >= 0 else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        numeric = Decimal(text)
        if numeric.is_finite() and numeric >= 0:
            return 0, numeric
    except InvalidOperation:
        pass
    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = _datetime.datetime.fromisoformat(iso_text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_datetime.timezone.utc).replace(tzinfo=None)
    return 1, parsed.isoformat(timespec="microseconds")


def _order(obj: Mapping[str, Any], errors: List[str]) -> Tuple[Optional[int], Optional[Tuple[int, Any]]]:
    sequence = obj.get("sequence")
    timestamp = obj.get("timestamp")
    if sequence is not None and (not isinstance(sequence, int) or isinstance(sequence, bool)):
        errors.append("sequence must be a nonnegative integer or null")
        sequence = None
    elif sequence is not None and sequence < 0:
        errors.append("sequence must be a nonnegative integer or null")
        sequence = None
    timestamp_key = None
    if timestamp is not None:
        timestamp_key = _timestamp(timestamp)
        if timestamp_key is None:
            errors.append("timestamp must be a nonnegative number or ISO timestamp")
    return sequence, timestamp_key


def _event_kind(obj: Mapping[str, Any]) -> Optional[str]:
    if obj.get("type") == "usage":
        return "normalized"
    if obj.get("method") == CODEX_METHOD:
        return "codex"
    # A token-looking object with the wrong discriminator is not a zero or a
    # valid measurement.  Keep ordinary non-usage events ignorable.
    if any(key in obj for key in (
        "cumulative",
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    )):
        return "unknown"
    params = obj.get("params")
    if isinstance(params, Mapping) and "tokenUsage" in params:
        return "unknown"
    return None


def _thread_id(obj: Mapping[str, Any], kind: str, errors: List[str]) -> Optional[str]:
    if kind == "normalized":
        value = obj.get("thread_id")
        label = "thread_id"
    else:
        params = obj.get("params")
        value = params.get("threadId") if isinstance(params, Mapping) else None
        label = "params.threadId"
    if not _nonempty_string(value):
        errors.append("%s must be a non-empty string" % label)
        return None
    return value


def _model(obj: Mapping[str, Any], errors: List[str]) -> Optional[str]:
    value = obj.get("model")
    if value is None:
        return None
    if not _nonempty_string(value):
        errors.append("model must be a non-empty string or null")
        return None
    return value


def _role(obj: Mapping[str, Any], errors: List[str]) -> Optional[str]:
    value = obj.get("role")
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append("role must be a string or null")
        return None
    return value


def _sample(record: EventRecord) -> Tuple[Optional[Sample], List[str]]:
    obj = record.obj
    kind = _event_kind(obj)
    if kind is None:
        return None, []
    if kind == "unknown":
        return None, [_location(record, "unknown event shape ignored; no usage inferred")]

    errors: List[str] = []
    thread_id = _thread_id(obj, kind, errors)
    sequence, timestamp = _order(obj, errors)
    model = _model(obj, errors)
    role = _role(obj, errors) if kind == "normalized" else None
    counters = {counter: None for counter in COUNTERS}
    present = False

    if kind == "normalized":
        source = obj.get("cumulative")
        if not isinstance(source, Mapping):
            errors.append("normalized usage event requires cumulative object")
        else:
            counters, present = _read_counters(source, NORMALIZED_NAMES, "cumulative", errors)
    else:
        params = obj.get("params")
        token_usage = params.get("tokenUsage") if isinstance(params, Mapping) else None
        total = token_usage.get("total") if isinstance(token_usage, Mapping) else None
        if not isinstance(params, Mapping):
            errors.append("Codex usage event requires params object")
        elif not isinstance(token_usage, Mapping):
            errors.append("Codex usage event requires params.tokenUsage")
        elif not isinstance(total, Mapping):
            errors.append("Codex usage event requires params.tokenUsage.total")
        else:
            counters, present = _read_counters(total, CODEX_NAMES, "tokenUsage.total", errors)

    _validate_relationships(counters, "usage snapshot", errors)
    notes: List[str] = []
    if not present and kind == "normalized" and isinstance(obj.get("cumulative"), Mapping):
        notes.append("cumulative object has no recognized counters; usage is UNKNOWN, not zero")
    elif present and not any(value is not None for value in counters.values()):
        notes.append("usage counters are missing or null; usage is UNKNOWN, not zero")

    if thread_id is None:
        return None, [_location(record, message) for message in errors]
    return (
        Sample(
            thread_id=thread_id,
            role=role,
            model=model,
            counters=counters,
            sequence=sequence,
            timestamp=timestamp,
            ordinal=record.ordinal,
            usable=not errors,
            problems=(
                notes
                + [_location(record, message) for message in errors]
            ),
            source_kind=kind,
        ),
        [_location(record, message) for message in errors],
    )


def _read_counters(
    source: Mapping[str, Any],
    names: Mapping[str, str],
    label: str,
    errors: List[str],
) -> Tuple[Dict[str, Optional[int]], bool]:
    counters = {counter: None for counter in COUNTERS}
    present = False
    for counter, name in names.items():
        if name in source:
            present = True
            counters[counter] = _nonnegative_int(source[name], "%s.%s" % (label, name), errors)
    return counters, present


def _validate_relationships(
    counters: Mapping[str, Optional[int]], label: str, errors: List[str]
) -> None:
    input_tokens = counters["input_tokens"]
    output_tokens = counters["output_tokens"]
    cached = counters["cached_input_tokens"]
    reasoning = counters["reasoning_output_tokens"]
    total = counters["total_tokens"]
    if cached is not None and input_tokens is not None and cached > input_tokens:
        errors.append("%s.cached_input_tokens cannot exceed input_tokens (invalid subset)" % label)
    if reasoning is not None and output_tokens is not None and reasoning > output_tokens:
        errors.append("%s.reasoning_output_tokens cannot exceed output_tokens (invalid subset)" % label)
    if total is not None and input_tokens is not None and output_tokens is not None:
        if total != input_tokens + output_tokens:
            errors.append("%s.total_tokens must equal input_tokens + output_tokens; subsets are not additive" % label)


def _baseline(
    raw: Any, label: str, errors: List[str], limitations: List[str]
) -> Dict[str, Optional[int]]:
    result = {counter: None for counter in COUNTERS}
    if raw is None:
        limitations.append(
            "%s baseline is missing or null; a fresh participant must explicitly use baseline 0" % label
        )
        return result
    if not isinstance(raw, Mapping):
        errors.append("%s baseline must be an object or null" % label)
        return result
    local_errors: List[str] = []
    values, _ = _read_counters(
        raw,
        {
            "input_tokens": "input_tokens",
            "output_tokens": "output_tokens",
            "cached_input_tokens": "cached_input_tokens",
            "reasoning_output_tokens": "reasoning_output_tokens",
        },
        label + ".baseline",
        local_errors,
    )
    result.update(values)
    _validate_relationships(result, label + ".baseline", local_errors)
    errors.extend(local_errors)
    for counter in PARENT:
        if result[counter] is None:
            limitations.append("%s baseline.%s is missing or null; that delta is UNKNOWN" % (label, counter))
    return result


def _optional_stage_string(raw: Mapping[str, Any], name: str, label: str, issues: List[str]) -> Optional[str]:
    value = raw.get(name)
    if value is None:
        return None
    if not _nonempty_string(value):
        issues.append("%s must be a non-empty string or null" % label)
        return None
    return value


def _stage_snapshot(
    raw: Any, label: str, issues: List[str]
) -> Dict[str, Optional[int]]:
    if raw is None:
        return {counter: None for counter in COUNTERS}
    if not isinstance(raw, Mapping):
        issues.append("%s must be an object or null" % label)
        return {counter: None for counter in COUNTERS}
    local_errors: List[str] = []
    values, present = _read_counters(raw, NORMALIZED_NAMES, label, local_errors)
    _validate_relationships(values, label, local_errors)
    issues.extend(local_errors)
    if not present:
        issues.append("%s has no recognized counters" % label)
    return values


def _parse_stage_intervals(
    raw: Any,
    participants: Sequence[Participant],
    limitations: List[str],
) -> Tuple[List[StageInterval], bool]:
    """Parse optional controller-stamped interval metadata without touching events."""

    if raw is None:
        limitations.append("manifest.stage_intervals must be an array; stage accounting is UNAVAILABLE")
        return [], True
    if not isinstance(raw, list):
        limitations.append("manifest.stage_intervals must be an array; stage accounting is UNAVAILABLE")
        return [], True

    participant_threads = {
        spec.thread_id
        for spec in participants
        if spec.thread_id is not None and spec.valid
    }
    intervals: List[StageInterval] = []
    seen_ids: Dict[str, List[int]] = {}
    for index, value in enumerate(raw):
        label = "stage interval %d" % (index + 1)
        issues: List[str] = []
        if not isinstance(value, Mapping):
            limitations.append("%s must be an object; stage attribution is UNAVAILABLE" % label)
            intervals.append(
                StageInterval(
                    None, None, None, None, None, None, None, None,
                    {counter: None for counter in COUNTERS},
                    {counter: None for counter in COUNTERS},
                    "UNAVAILABLE", False, ["invalid interval object"],
                )
            )
            continue

        interval_id = value.get("id")
        if interval_id is None:
            interval_id = value.get("interval_id")
        if not _nonempty_string(interval_id):
            issues.append("id must be a non-empty string")
            interval_id = None
        else:
            seen_ids.setdefault(interval_id, []).append(index)

        stage = value.get("stage")
        if not _nonempty_string(stage):
            issues.append("stage must be a non-empty string")
            stage = None

        attempt = value.get("attempt")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            issues.append("attempt must be a positive integer")
            attempt = None

        thread_id = value.get("thread_id")
        if thread_id is not None and not _nonempty_string(thread_id):
            issues.append("thread_id must be a non-empty string or null")
            thread_id = None

        agent_id = _optional_stage_string(value, "agent_id", label + ".agent_id", issues)
        model = _optional_stage_string(value, "model", label + ".model", issues)
        effort = _optional_stage_string(value, "effort", label + ".effort", issues)
        counter_epoch = _optional_stage_string(
            value, "counter_epoch", label + ".counter_epoch", issues
        )

        raw_coverage = value.get("coverage")
        if raw_coverage is None:
            has_boundary = value.get("start") is not None or value.get("end") is not None
            coverage = STAGE_MEASURED if has_boundary else STAGE_NOT_APPLICABLE
        elif raw_coverage in (STAGE_MEASURED, STAGE_NOT_APPLICABLE):
            coverage = raw_coverage
        else:
            issues.append("coverage must be MEASURED or NOT_APPLICABLE")
            coverage = "UNAVAILABLE"

        start = {counter: None for counter in COUNTERS}
        end = {counter: None for counter in COUNTERS}
        if coverage == STAGE_MEASURED:
            if thread_id is None:
                issues.append("measured interval requires thread_id")
            elif thread_id not in participant_threads:
                issues.append("thread_id is not a valid manifest participant")
            if counter_epoch is None:
                issues.append("measured interval requires counter_epoch")
            start = _stage_snapshot(value.get("start"), label + ".start", issues)
            end = _stage_snapshot(value.get("end"), label + ".end", issues)
            if value.get("start") is None:
                issues.append("measured interval requires start boundary")
            if value.get("end") is None:
                issues.append("measured interval requires end boundary")
        elif value.get("start") is not None or value.get("end") is not None:
            issues.append("NOT_APPLICABLE interval cannot contain token boundaries")

        intervals.append(
            StageInterval(
                interval_id,
                stage,
                attempt,
                thread_id,
                agent_id,
                model,
                effort,
                counter_epoch,
                start,
                end,
                coverage,
                not issues,
                issues,
            )
        )

    for interval_id, indexes in seen_ids.items():
        if len(indexes) > 1:
            message = "stage interval id %r is duplicated" % interval_id
            limitations.append(message)
            for index in indexes:
                intervals[index].valid = False
                intervals[index].issues.append(message)

    for interval in intervals:
        if interval.issues:
            limitations.extend(
                "stage interval %r: %s" % (interval.interval_id or "<missing>", issue)
                for issue in interval.issues
            )
    return intervals, True


def _manifest(manifest: Any) -> Manifest:
    errors: List[str] = []
    limitations: List[str] = []
    if not isinstance(manifest, Mapping):
        return Manifest(None, [], None, None, [], False, ["manifest must be a JSON object"], [])
    run_id = manifest.get("run_id") if _nonempty_string(manifest.get("run_id")) else None
    if run_id is None:
        errors.append("manifest.run_id must be a non-empty string")
    raw_participants = manifest.get("participants")
    if not isinstance(raw_participants, list):
        errors.append("manifest.participants must be an array")
        raw_participants = []

    def flag(name: str) -> Optional[bool]:
        value = manifest.get(name)
        if value is None:
            return None
        if not isinstance(value, bool):
            errors.append("manifest.%s must be boolean or null" % name)
            return None
        return value

    participants: List[Participant] = []
    for index, raw in enumerate(raw_participants):
        label = "participant %d" % (index + 1)
        if not isinstance(raw, Mapping):
            errors.append("%s must be an object" % label)
            participants.append(Participant(index, None, None, None, {counter: None for counter in COUNTERS}, False, ["invalid participant object"]))
            continue
        issues: List[str] = []
        thread_id = raw.get("thread_id") if _nonempty_string(raw.get("thread_id")) else None
        if thread_id is None:
            issues.append("thread_id must be a non-empty string")
        role = raw.get("role") if isinstance(raw.get("role"), str) else None
        if role not in ROLES:
            issues.append("role must be one of ASTRA, LUNA, SOL, CONTROLLER")
        model = raw.get("model")
        if model is not None and not _nonempty_string(model):
            issues.append("model must be a non-empty string or null")
            model = None
        if model is None:
            limitations.append("%s model is missing or null; model attribution is UNKNOWN" % label)
        baseline = _baseline(raw.get("baseline"), label, errors, limitations)
        participants.append(Participant(index, thread_id, role, model, baseline, not issues, issues))

    locations: Dict[str, List[int]] = {}
    for spec in participants:
        if spec.thread_id is not None:
            locations.setdefault(spec.thread_id, []).append(spec.index)
    for thread_id, indexes in locations.items():
        if len(indexes) > 1:
            errors.append("thread_id %r is mapped by multiple participants" % thread_id)
            for index in indexes:
                participants[index].valid = False
                participants[index].issues.append("conflicting participant mapping")
    stage_metadata_present = STAGE_INTERVALS_KEY in manifest
    if stage_metadata_present:
        stage_intervals, _ = _parse_stage_intervals(
            manifest.get(STAGE_INTERVALS_KEY), participants, limitations
        )
    else:
        stage_intervals = []
    return Manifest(
        run_id,
        participants,
        flag("run_complete"),
        flag("includes_final_response"),
        stage_intervals,
        stage_metadata_present,
        _unique(errors),
        _unique(limitations),
    )


def _sort_key(sample: Sample) -> Tuple[int, Any, int]:
    if sample.sequence is not None:
        return 0, sample.sequence, sample.ordinal
    if sample.timestamp is not None:
        return 1, sample.timestamp, sample.ordinal
    return 2, sample.ordinal, sample.ordinal


def _order_samples(
    samples: List[Sample], limitations: List[str], label: str
) -> Tuple[List[Sample], bool]:
    if not samples:
        return [], False
    with_sequence = sum(sample.sequence is not None for sample in samples)
    with_timestamp = sum(sample.timestamp is not None for sample in samples)
    uncertain = False
    if with_sequence and with_sequence != len(samples):
        limitations.append("%s mixes sequenced and unsequenced snapshots" % label)
        uncertain = True
    elif not with_sequence and with_timestamp and with_timestamp != len(samples):
        limitations.append("%s mixes timestamped and untimestamped snapshots" % label)
        uncertain = True
    elif not with_sequence and not with_timestamp:
        limitations.append("%s snapshots have no sequence or timestamp; input order used" % label)
    if with_sequence == len(samples) and with_timestamp == len(samples):
        by_sequence = sorted(samples, key=lambda sample: (sample.sequence, sample.ordinal))
        if any(
            left.timestamp > right.timestamp
            for left, right in zip(by_sequence, by_sequence[1:])
        ):
            limitations.append("%s sequence and timestamp order disagree" % label)
            uncertain = True
    return sorted(samples, key=_sort_key), uncertain


def _deduplicate(samples: List[Sample], errors: List[str], limitations: List[str], label: str) -> List[Sample]:
    identities: Dict[Tuple[str, Any], Tuple[Any, Sample]] = {}
    signatures = set()
    result: List[Sample] = []
    for sample in samples:
        signature = sample.signature()
        identity = sample.identity()
        if identity is not None:
            previous = identities.get(identity)
            if previous is not None:
                if previous[0] == signature:
                    limitations.append("%s has duplicate snapshots; counted once" % label)
                    continue
                message = "%s has conflicting duplicate snapshots for %s=%r" % (label, identity[0], identity[1])
                errors.append(message)
                limitations.append(message)
                result.append(sample)
                continue
            identities[identity] = (signature, sample)
        elif signature in signatures:
            limitations.append("%s has duplicate snapshots; counted once" % label)
            continue
        signatures.add(signature)
        result.append(sample)
    return result


def _model_info(spec: Participant, samples: Sequence[Sample]) -> Tuple[Optional[str], str, List[str]]:
    seen: List[str] = []
    for sample in samples:
        if sample.model is not None and sample.model not in seen:
            seen.append(sample.model)
    if len(seen) > 1:
        return spec.model, "UNCERTAIN", ["multiple models were observed for one cumulative thread; attribution is UNCERTAIN"]
    if spec.model is None:
        return (seen[0], "CERTAIN", []) if seen else (None, "UNKNOWN", ["model attribution is UNKNOWN"])
    if seen and seen[0] != spec.model:
        return spec.model, "UNCERTAIN", ["observed model differs from manifest model; reroute attribution is UNCERTAIN"]
    return spec.model, "CERTAIN", []


def _participant_report(
    spec: Participant,
    samples: List[Sample],
    event_errors: Sequence[str],
    errors: List[str],
    run_complete: Optional[bool],
    includes_final_response: Optional[bool],
) -> Dict[str, Any]:
    label = "participant %d" % (spec.index + 1)
    limitations = list(spec.issues)
    ordered, ordering_uncertain = _order_samples(samples, limitations, label)
    ordered = _deduplicate(ordered, errors, limitations, label)
    usable = [sample for sample in ordered if sample.usable]
    model, model_state, model_limits = _model_info(spec, usable)
    limitations.extend(model_limits)
    for sample in ordered:
        limitations.extend(sample.problems)

    measured = {counter: None for counter in COUNTERS}
    reset = False
    if usable:
        previous: Dict[str, int] = {}
        for sample in usable:
            for counter in COUNTERS:
                value = sample.counters[counter]
                if value is not None:
                    if counter in previous and value < previous[counter]:
                        reset = True
                        message = "%s cumulative %s regressed; counter reset/regression detected" % (label, counter)
                        _add_unique(errors, message)
                        _add_unique(limitations, message)
                    previous[counter] = value
        latest = usable[-1]
        for counter in COUNTERS:
            current = latest.counters[counter]
            baseline = spec.baseline[counter]
            if current is None:
                if counter in PARENT or baseline is not None:
                    limitations.append("%s latest cumulative %s is missing or null; that value is UNKNOWN" % (label, counter))
            elif baseline is None:
                if counter != "total_tokens":
                    limitations.append("%s baseline.%s is missing or null; cumulative delta is UNKNOWN" % (label, counter))
            else:
                delta = current - baseline
                if delta < 0:
                    reset = True
                    message = "%s latest %s is below baseline; counter reset/regression detected" % (label, counter)
                    _add_unique(errors, message)
                    _add_unique(limitations, message)
                else:
                    measured[counter] = delta
        if measured["cached_input_tokens"] is not None and measured["input_tokens"] is not None:
            if measured["cached_input_tokens"] > measured["input_tokens"]:
                message = "%s delta cached_input_tokens exceeds input_tokens (invalid subset)" % label
                _add_unique(errors, message)
                _add_unique(limitations, message)
                measured["cached_input_tokens"] = None
        if measured["reasoning_output_tokens"] is not None and measured["output_tokens"] is not None:
            if measured["reasoning_output_tokens"] > measured["output_tokens"]:
                message = "%s delta reasoning_output_tokens exceeds output_tokens (invalid subset)" % label
                _add_unique(errors, message)
                _add_unique(limitations, message)
                measured["reasoning_output_tokens"] = None
        if measured["input_tokens"] is not None and measured["output_tokens"] is not None:
            measured["total_tokens"] = measured["input_tokens"] + measured["output_tokens"]
    if reset:
        measured = {counter: None for counter in COUNTERS}

    for issue in spec.issues:
        _add_unique(errors, "%s: %s" % (label, issue))
    raw_known = any(value is not None for sample in usable for value in sample.counters.values())
    delta_known = any(value is not None for value in measured.values())
    parents_complete = all(measured[counter] is not None for counter in PARENT)
    if not usable:
        state = "UNAVAILABLE"
        limitations.append("%s has no usable cumulative usage snapshot" % label)
    elif (
        parents_complete
        and not spec.issues
        and not event_errors
        and not reset
        and not ordering_uncertain
        and model_state == "CERTAIN"
    ):
        state = "COMPLETE"
    elif delta_known or raw_known:
        state = "PARTIAL"
    else:
        state = "UNAVAILABLE"
    if run_complete is not True:
        state = "PARTIAL" if state == "COMPLETE" else state
        limitations.append("run_complete is false" if run_complete is False else "run_complete is missing or null")
    if includes_final_response is not True:
        state = "PARTIAL" if state == "COMPLETE" else state
        limitations.append(
            "includes_final_response is false; a prefinal snapshot is not a full final-answer total"
            if includes_final_response is False
            else "includes_final_response is missing or null; final-answer coverage is unknown"
        )
    if model_state != "CERTAIN":
        state = "PARTIAL" if state == "COMPLETE" else state
    models_seen: List[str] = []
    for sample in usable:
        if sample.model is not None and sample.model not in models_seen:
            models_seen.append(sample.model)
    return {
        "thread_id": spec.thread_id,
        "role": spec.role,
        "model": model,
        "model_attribution": model_state,
        "models_seen": models_seen,
        "input_tokens": measured["input_tokens"],
        "output_tokens": measured["output_tokens"],
        "cached_input_tokens": measured["cached_input_tokens"],
        "reasoning_output_tokens": measured["reasoning_output_tokens"],
        "total_tokens": measured["total_tokens"],
        "measurement_state": state,
        "limitations": _unique(limitations),
    }


def _stage_context(
    spec: Participant, samples: Sequence[Sample]
) -> Dict[str, Any]:
    limitations: List[str] = []
    errors: List[str] = []
    usable = [sample for sample in samples if sample.usable]
    ordered, ordering_uncertain = _order_samples(
        list(usable), limitations, "participant %s" % (spec.thread_id or "<missing>")
    )
    ordered = _deduplicate(
        ordered,
        errors,
        limitations,
        "participant %s" % (spec.thread_id or "<missing>"),
    )
    if len(ordered) > 1 and all(
        sample.sequence is None and sample.timestamp is None for sample in ordered
    ):
        ordering_uncertain = True
    reset = False
    previous: Dict[str, int] = {}
    for sample in ordered:
        for counter in COUNTERS:
            value = sample.counters[counter]
            if value is not None:
                if counter in previous and value < previous[counter]:
                    reset = True
                previous[counter] = value
    return {
        "samples": ordered,
        "ordering_uncertain": ordering_uncertain,
        "reset": reset,
        "baseline": spec.baseline,
        "limitations": limitations,
        "errors": errors,
    }


def _stage_boundary_position(
    boundary: Mapping[str, Optional[int]],
    context: Mapping[str, Any],
    prefer_baseline: bool,
) -> Tuple[Optional[int], Optional[str]]:
    if any(boundary[counter] is None for counter in PARENT):
        return None, "stage boundary input/output counters are missing or null"
    baseline = context["baseline"]
    if all(boundary[counter] == baseline[counter] for counter in PARENT):
        if prefer_baseline:
            return -1, None
    matches = [
        index
        for index, sample in enumerate(context["samples"])
        if all(sample.counters[counter] == boundary[counter] for counter in PARENT)
    ]
    if not matches:
        return None, "stage boundary is outside observed cumulative coverage"
    if len(matches) > 1:
        return None, "stage boundary matches multiple snapshots; attribution is ambiguous"
    return matches[0], None


def _stage_interval_amount(
    interval: StageInterval, issues: List[str]
) -> Dict[str, Optional[int]]:
    amount = {counter: None for counter in COUNTERS}
    for counter in COUNTERS:
        start = interval.start[counter]
        end = interval.end[counter]
        if start is not None and end is not None:
            delta = end - start
            if delta < 0:
                issues.append("%s boundary is reversed for %s" % (interval.interval_id or "<missing>", counter))
            else:
                amount[counter] = delta
    if amount["input_tokens"] is not None and amount["output_tokens"] is not None:
        computed_total = amount["input_tokens"] + amount["output_tokens"]
        if amount["total_tokens"] is not None and amount["total_tokens"] != computed_total:
            issues.append("stage interval total_tokens must equal input_tokens + output_tokens")
        amount["total_tokens"] = computed_total
    if (
        amount["cached_input_tokens"] is not None
        and amount["input_tokens"] is not None
        and amount["cached_input_tokens"] > amount["input_tokens"]
    ):
        issues.append("stage interval cached_input_tokens exceeds input_tokens")
        amount["cached_input_tokens"] = None
    if (
        amount["reasoning_output_tokens"] is not None
        and amount["output_tokens"] is not None
        and amount["reasoning_output_tokens"] > amount["output_tokens"]
    ):
        issues.append("stage interval reasoning_output_tokens exceeds output_tokens")
        amount["reasoning_output_tokens"] = None
    return amount


def _stage_accounting(
    manifest_data: Manifest,
    reports: Sequence[Mapping[str, Any]],
    samples: Mapping[str, Sequence[Sample]],
) -> Dict[str, Any]:
    """Attribute explicit manifest intervals without changing participant totals."""

    specs = {
        spec.thread_id: spec
        for spec in manifest_data.participants
        if spec.thread_id is not None
    }
    report_by_thread: Dict[str, Mapping[str, Any]] = {}
    for report in reports:
        thread_id = report.get("thread_id")
        if isinstance(thread_id, str) and thread_id not in report_by_thread:
            report_by_thread[thread_id] = report
    contexts = {
        thread_id: _stage_context(spec, samples.get(thread_id, []))
        for thread_id, spec in specs.items()
    }

    records: List[Dict[str, Any]] = []
    for interval in manifest_data.stage_intervals:
        issues = list(interval.issues)
        amount = {counter: None for counter in COUNTERS}
        start_position: Optional[int] = None
        end_position: Optional[int] = None
        math_usable = False
        if interval.coverage == STAGE_NOT_APPLICABLE:
            coverage = STAGE_NOT_APPLICABLE if interval.valid and not issues else "UNAVAILABLE"
        else:
            context = contexts.get(interval.thread_id or "")
            if context is None:
                issues.append("stage interval thread has no participant context")
            elif context["reset"]:
                issues.append("stage interval crosses a counter reset/regression")
            elif context["ordering_uncertain"] or context["errors"]:
                issues.append("stage interval ordering or snapshot identity is ambiguous")
            else:
                epochs = {
                    item.counter_epoch
                    for item in manifest_data.stage_intervals
                    if item.thread_id == interval.thread_id
                    and item.coverage == STAGE_MEASURED
                    and item.counter_epoch is not None
                }
                if len(epochs) > 1:
                    issues.append("stage intervals for one thread use different counter epochs")
                if interval.valid and not issues and context is not None:
                    start_position, start_error = _stage_boundary_position(
                        interval.start, context, prefer_baseline=True
                    )
                    end_position, end_error = _stage_boundary_position(
                        interval.end, context, prefer_baseline=False
                    )
                    if start_error:
                        issues.append("start: " + start_error)
                    if end_error:
                        issues.append("end: " + end_error)
                    if (
                        start_position is not None
                        and end_position is not None
                        and end_position <= start_position
                    ):
                        issues.append("stage interval boundaries are reversed or empty")
                    if not issues:
                        amount = _stage_interval_amount(interval, issues)
                        math_usable = amount["input_tokens"] is not None and amount["output_tokens"] is not None
            if interval.model is None:
                issues.append("stage interval model is missing; attribution is PARTIAL")
            if interval.effort is None:
                issues.append("stage interval effort is missing; attribution is PARTIAL")
            if math_usable:
                coverage = "EXACT" if not issues else "PARTIAL"
            else:
                coverage = "UNAVAILABLE"

        records.append(
            {
                "id": interval.interval_id,
                "stage": interval.stage,
                "attempt": interval.attempt,
                "thread_id": interval.thread_id,
                "agent_id": interval.agent_id,
                "model": interval.model,
                "effort": interval.effort,
                "counter_epoch": interval.counter_epoch,
                "start": interval.start,
                "end": interval.end,
                "input_tokens": amount["input_tokens"],
                "output_tokens": amount["output_tokens"],
                "cached_input_tokens": amount["cached_input_tokens"],
                "reasoning_output_tokens": amount["reasoning_output_tokens"],
                "total_tokens": amount["total_tokens"],
                "coverage": coverage,
                "limitations": _unique(issues),
                "_amount": amount,
                "_start_position": start_position,
                "_end_position": end_position,
                "_math_usable": math_usable,
            }
        )

    measured_by_thread: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        if record["coverage"] != STAGE_NOT_APPLICABLE and record["thread_id"] is not None:
            measured_by_thread.setdefault(record["thread_id"], []).append(record)
    for thread_id, thread_records in measured_by_thread.items():
        epochs = {
            record["counter_epoch"]
            for record in thread_records
            if record["counter_epoch"] is not None
        }
        if len(epochs) > 1:
            for record in thread_records:
                record["limitations"].append("stage intervals for one thread use different counter epochs")
                record["coverage"] = "UNAVAILABLE"
                record["_math_usable"] = False
                record["_amount"] = {counter: None for counter in COUNTERS}
        usable_records = [
            record
            for record in thread_records
            if record["_start_position"] is not None
            and record["_end_position"] is not None
            and record["coverage"] in {"EXACT", "PARTIAL"}
        ]
        for index, left in enumerate(usable_records):
            for right in usable_records[index + 1 :]:
                if (
                    left["_start_position"] < right["_end_position"]
                    and right["_start_position"] < left["_end_position"]
                ):
                    left_id = left["id"] or "<missing>"
                    right_id = right["id"] or "<missing>"
                    left["limitations"].append("overlaps stage interval %r" % right_id)
                    right["limitations"].append("overlaps stage interval %r" % left_id)
                    for record in (left, right):
                        record["coverage"] = "UNAVAILABLE"
                        record["_math_usable"] = False
                        record["_amount"] = {counter: None for counter in COUNTERS}
                        for counter in COUNTERS:
                            record[counter] = None

    stage_groups: Dict[str, Dict[str, Any]] = {}
    for record in records:
        stage = record["stage"]
        if stage is None:
            continue
        group = stage_groups.setdefault(
            stage,
            {
                "stage": stage,
                "interval_ids": [],
                "attempts": [],
                "thread_ids": [],
                "agent_ids": [],
                "models": [],
                "efforts": [],
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
                "reasoning_output_tokens": 0,
                "total_tokens": 0,
                "known": {counter: False for counter in COUNTERS},
                "unknown": {counter: False for counter in COUNTERS},
                "nonexact": False,
                "not_applicable": True,
                "limitations": [],
            },
        )
        for field_name, value in (
            ("interval_ids", record["id"]),
            ("attempts", record["attempt"]),
            ("thread_ids", record["thread_id"]),
            ("agent_ids", record["agent_id"]),
            ("models", record["model"]),
            ("efforts", record["effort"]),
        ):
            if value is not None and value not in group[field_name]:
                group[field_name].append(value)
        group["limitations"].extend(record["limitations"])
        if record["coverage"] != STAGE_NOT_APPLICABLE:
            group["not_applicable"] = False
            if record["coverage"] != "EXACT":
                group["nonexact"] = True
            for counter in COUNTERS:
                value = record["_amount"][counter]
                if value is None:
                    group["unknown"][counter] = True
                else:
                    group[counter] += value
                    group["known"][counter] = True

    stages: Dict[str, Dict[str, Any]] = {}
    for stage, group in stage_groups.items():
        values: Dict[str, Optional[int]] = {}
        for counter in COUNTERS:
            if group["unknown"][counter]:
                values[counter] = None
            elif group["known"][counter]:
                values[counter] = group[counter]
            else:
                values[counter] = None
        if values["input_tokens"] is not None and values["output_tokens"] is not None:
            values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
        if group["not_applicable"]:
            coverage = STAGE_NOT_APPLICABLE
            state = "UNAVAILABLE"
        elif not any(group["known"].values()):
            coverage = "UNAVAILABLE"
            state = "UNAVAILABLE"
        elif group["nonexact"] or any(group["unknown"].values()):
            coverage = "PARTIAL"
            state = "PARTIAL"
        else:
            coverage = "EXACT"
            state = "COMPLETE"
        stages[stage] = {
            "stage": stage,
            "interval_ids": group["interval_ids"],
            "attempts": group["attempts"],
            "participant_count": len(group["thread_ids"]),
            "thread_ids": group["thread_ids"],
            "agent_ids": group["agent_ids"],
            "models": group["models"],
            "efforts": group["efforts"],
            **values,
            "coverage": coverage,
            "measurement_state": state,
            "limitations": _unique(group["limitations"]),
        }

    residual: List[Dict[str, Any]] = []
    participant_reconciliation: Dict[str, Optional[bool]] = {counter: None for counter in COUNTERS}
    for report in reports:
        thread_id = report.get("thread_id")
        thread_records = measured_by_thread.get(thread_id or "", [])
        invalid_records = [
            record
            for record in thread_records
            if record["coverage"] == "UNAVAILABLE"
        ]
        values: Dict[str, Optional[int]] = {}
        limitations: List[str] = []
        if not thread_records:
            limitations.append("participant has no stage interval; usage is residual")
        if invalid_records:
            limitations.append("invalid or ambiguous stage interval prevents exact residual attribution")
        for counter in COUNTERS:
            known_value = report.get(counter)
            if known_value is None:
                values[counter] = None
                continue
            if invalid_records:
                values[counter] = None
                continue
            amounts = [record["_amount"][counter] for record in thread_records]
            if any(value is None for value in amounts):
                values[counter] = None
                limitations.append("residual %s is UNKNOWN because interval coverage is incomplete" % counter)
                continue
            values[counter] = known_value - sum(amounts)
            if values[counter] < 0:
                values[counter] = None
                limitations.append("residual %s is UNKNOWN because stage totals exceed participant total" % counter)
        if values["input_tokens"] is not None and values["output_tokens"] is not None:
            values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
        known_values = [value for value in values.values() if value is not None]
        unknown_residual = any(
            report.get(counter) is not None and values[counter] is None
            for counter in COUNTERS
        )
        if not known_values:
            coverage = "UNAVAILABLE"
        elif invalid_records or unknown_residual:
            coverage = "PARTIAL"
        elif any(value > 0 for value in values.values() if value is not None):
            coverage = "RESIDUAL"
        else:
            coverage = "EXACT"
        for counter in COUNTERS:
            known_value = report.get(counter)
            if known_value is None or values[counter] is None:
                continue
            total = sum(record["_amount"][counter] for record in thread_records)
            reconciled = total + values[counter] == known_value
            participant_reconciliation[counter] = (
                reconciled
                if participant_reconciliation[counter] is None
                else participant_reconciliation[counter] and reconciled
            )
        residual.append(
            {
                "thread_id": thread_id,
                "role": report.get("role"),
                "model": report.get("model"),
                **values,
                "coverage": coverage,
                "limitations": _unique(limitations),
            }
        )

    output_intervals = []
    for record in records:
        output = dict(record)
        for key in ("_amount", "_start_position", "_end_position", "_math_usable"):
            output.pop(key, None)
        output_intervals.append(output)
    measured_records = [record for record in records if record["coverage"] != STAGE_NOT_APPLICABLE]
    all_known_participants = all(
        report.get(counter) is not None
        for report in reports
        for counter in PARENT
    )
    all_exact_intervals = bool(measured_records) and all(
        record["coverage"] == "EXACT" for record in measured_records
    )
    all_reconciled = all(
        value is True
        for counter, value in participant_reconciliation.items()
        if counter in PARENT and value is not None
    ) and all(value is not None for counter, value in participant_reconciliation.items() if counter in PARENT)
    zero_residual = bool(residual) and all(
        row[counter] == 0 for row in residual for counter in PARENT
    )
    if all_exact_intervals and all_known_participants and all_reconciled and zero_residual:
        state = "COMPLETE"
    elif any(
        value is not None
        for record in records
        for value in (record["input_tokens"], record["output_tokens"], record["total_tokens"])
    ) or any(row["coverage"] in {"RESIDUAL", "PARTIAL"} for row in residual):
        state = "PARTIAL"
    else:
        state = "UNAVAILABLE"
    return {
        "intervals": output_intervals,
        "stages": stages,
        "residual": residual,
        "reconciliation": participant_reconciliation,
        "measurement_state": state,
        "limitations": _unique(
            list(manifest_data.limitations)
            + [
                "stage attribution is based only on explicit manifest intervals"
            ]
        ),
    }


def _sum_known(reports: Sequence[Mapping[str, Any]], key: str) -> Optional[int]:
    values = [report[key] for report in reports if report.get(key) is not None]
    return sum(values) if values else None


def _roles(reports: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for role in ROLES:
        selected = [report for report in reports if report.get("role") == role]
        result[role] = {
            "participant_count": len(selected),
            "thread_ids": [report.get("thread_id") for report in selected],
            "input_tokens": _sum_known(selected, "input_tokens"),
            "output_tokens": _sum_known(selected, "output_tokens"),
            "cached_input_tokens": _sum_known(selected, "cached_input_tokens"),
            "reasoning_output_tokens": _sum_known(selected, "reasoning_output_tokens"),
            "total_tokens": _sum_known(selected, "total_tokens"),
        }
    return result


def _empty_report(
    run_id: Optional[str],
    errors: Sequence[str],
    limitations: Sequence[str],
    final_response_included: Optional[bool] = None,
) -> Dict[str, Any]:
    empty_roles = {
        role: {
            "participant_count": 0,
            "thread_ids": [],
            "input_tokens": None,
            "output_tokens": None,
            "cached_input_tokens": None,
            "reasoning_output_tokens": None,
            "total_tokens": None,
        }
        for role in ROLES
    }
    return {
        "run_id": run_id,
        "participants": [],
        "roles": empty_roles,
        "known": {"input_tokens": None, "output_tokens": None, "total_tokens": None},
        "complete_total": None,
        "final_response_included": final_response_included,
        "measurement_state": "UNAVAILABLE",
        "limitations": _unique(list(errors) + list(limitations)),
        "errors": _unique(errors),
    }


def summarize_usage(
    manifest: Any,
    events: Iterable[Any],
    parse_errors: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Return a report for the explicit manifest participant selection."""

    manifest_data = _manifest(manifest)
    errors = list(manifest_data.errors)
    limitations = list(manifest_data.limitations)
    errors.extend(parse_errors or [])
    if isinstance(events, str):
        records, stream_errors = parse_event_stream(events)
        errors.extend(stream_errors)
    else:
        records = []
        for ordinal, event in enumerate(events):
            if isinstance(event, EventRecord):
                records.append(event)
            elif isinstance(event, Mapping):
                records.append(EventRecord(event, ordinal))
            else:
                errors.append("event %d is not a JSON object" % (ordinal + 1))

    if not manifest_data.participants:
        limitations.append("no manifest-selected participants are available to measure")
        report = _empty_report(
            manifest_data.run_id,
            errors,
            limitations,
            manifest_data.includes_final_response,
        )
        if manifest_data.stage_metadata_present:
            report["stage_accounting"] = _stage_accounting(manifest_data, [], {})
        return report

    selected = {
        spec.thread_id: spec
        for spec in manifest_data.participants
        if spec.valid and spec.thread_id is not None
    }
    samples: Dict[str, List[Sample]] = {}
    event_errors: Dict[str, List[str]] = {}
    recognized = 0
    for record in records:
        sample, sample_errors = _sample(record)
        if sample is None:
            errors.extend(sample_errors)
            continue
        recognized += 1
        if sample.thread_id not in selected:
            errors.append(_location(record, "usage event thread_id %r is not listed in manifest; event ignored" % sample.thread_id))
            continue
        errors.extend(sample_errors)
        if sample.role is not None and sample.role != selected[sample.thread_id].role:
            sample.usable = False
            message = _location(
                record,
                "event role %r conflicts with manifest role %r"
                % (sample.role, selected[sample.thread_id].role),
            )
            sample.problems.append(message)
            errors.append(message)
            event_errors.setdefault(sample.thread_id, []).append(message)
        samples.setdefault(sample.thread_id, []).append(sample)
        event_errors.setdefault(sample.thread_id, []).extend(sample_errors)
    if recognized == 0:
        limitations.append("no recognized usage measurements were provided")

    reports: List[Dict[str, Any]] = []
    for spec in manifest_data.participants:
        report = _participant_report(
            spec,
            samples.get(spec.thread_id or "", []),
            event_errors.get(spec.thread_id or "", []),
            errors,
            manifest_data.run_complete,
            manifest_data.includes_final_response,
        )
        reports.append(report)
        limitations.extend(report["limitations"])

    known = {
        "input_tokens": _sum_known(reports, "input_tokens"),
        "output_tokens": _sum_known(reports, "output_tokens"),
        "total_tokens": _sum_known(reports, "total_tokens"),
    }
    full = all(
        report["measurement_state"] == "COMPLETE"
        and report["input_tokens"] is not None
        and report["output_tokens"] is not None
        and report["total_tokens"] is not None
        for report in reports
    )
    final_complete = manifest_data.run_complete is True and manifest_data.includes_final_response is True
    complete = bool(reports) and full and final_complete and not errors
    if not final_complete:
        if manifest_data.run_complete is False:
            limitations.append("run_complete is false; complete_total is withheld")
        elif manifest_data.run_complete is None:
            limitations.append("run_complete is missing or null; complete_total is withheld")
        if manifest_data.includes_final_response is False:
            limitations.append("includes_final_response is false; complete_total is withheld")
        elif manifest_data.includes_final_response is None:
            limitations.append("includes_final_response is missing or null; complete_total is withheld")
    has_known = any(value is not None for value in known.values())
    state = "COMPLETE" if complete else ("PARTIAL" if has_known or any(report["measurement_state"] == "PARTIAL" for report in reports) else "UNAVAILABLE")
    result = {
        "run_id": manifest_data.run_id,
        "participants": reports,
        "roles": _roles(reports),
        "known": known,
        "complete_total": known["total_tokens"] if complete else None,
        "final_response_included": manifest_data.includes_final_response,
        "measurement_state": state,
        "limitations": _unique(limitations),
        "errors": _unique(errors),
    }
    if manifest_data.stage_metadata_present:
        result["stage_accounting"] = _stage_accounting(manifest_data, reports, samples)
    return result


def _read_json_file(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageInputError("cannot read %s: %s" % (path, exc))
    try:
        return _loads_strict(text)
    except (ValueError, TypeError) as exc:
        raise UsageInputError("manifest is malformed JSON: %s" % exc)


def _failure_report(message: str) -> Dict[str, Any]:
    return _empty_report(None, [message], ["usage could not be summarized safely"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize offline cumulative LinkedAI token usage.")
    parser.add_argument("--manifest", required=True, metavar="MANIFEST", help="JSON manifest")
    parser.add_argument("events", nargs="?", metavar="EVENTS", help="NDJSON event file; defaults to stdin")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = _read_json_file(Path(args.manifest))
    except UsageInputError as exc:
        print(json.dumps(_failure_report(str(exc)), ensure_ascii=False, indent=2))
        return 2
    if args.events is None or args.events == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(args.events).read_text(encoding="utf-8")
        except OSError as exc:
            print(json.dumps(_failure_report("cannot read events: %s" % exc), ensure_ascii=False, indent=2))
            return 2
    records, parse_errors = parse_event_stream(text)
    report = summarize_usage(manifest, records, parse_errors=parse_errors)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
