import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
USAGE = ROOT / "scripts" / "usage.py"
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "scripts"))

from usage import parse_event_stream, summarize_usage  # noqa: E402


def manifest(*participants, run_complete=True, includes_final_response=True):
    return {
        "run_id": "test-run",
        "participants": list(participants),
        "run_complete": run_complete,
        "includes_final_response": includes_final_response,
    }


_MISSING = object()


def participant(thread_id="t1", role="ASTRA", model="model-a", baseline=_MISSING, include_baseline=True):
    value = {"thread_id": thread_id, "role": role, "model": model}
    if include_baseline:
        value["baseline"] = {
            "input_tokens": 0,
            "output_tokens": 0,
        } if baseline is _MISSING else baseline
    return value


def normalized(
    thread_id="t1",
    sequence=None,
    timestamp=None,
    input_tokens=0,
    output_tokens=0,
    model=None,
    role=None,
    **extra
):
    event = {"type": "usage", "thread_id": thread_id, "cumulative": {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }}
    if sequence is not None:
        event["sequence"] = sequence
    if timestamp is not None:
        event["timestamp"] = timestamp
    if model is not None:
        event["model"] = model
    if role is not None:
        event["role"] = role
    event["cumulative"].update(extra)
    return event


def codex(thread_id="t1", input_tokens=0, output_tokens=0, **extra):
    total = {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
    }
    total.update(extra)
    return {
        "method": "thread/tokenUsage/updated",
        "params": {"threadId": thread_id, "tokenUsage": {"total": total}},
    }


def stage_interval(
    interval_id,
    stage,
    thread_id,
    start,
    end,
    attempt=1,
    model="model-a",
    effort="max",
    counter_epoch="epoch-1",
    coverage="MEASURED",
    **extra
):
    value = {
        "id": interval_id,
        "stage": stage,
        "attempt": attempt,
        "thread_id": thread_id,
        "model": model,
        "effort": effort,
        "counter_epoch": counter_epoch,
        "coverage": coverage,
    }
    if start is not None:
        value["start"] = start
    if end is not None:
        value["end"] = end
    value.update(extra)
    return value


def stage_manifest(*participants, intervals=None, **flags):
    value = manifest(*participants, **flags)
    value["stage_intervals"] = list(intervals or [])
    return value


class UsageSummarizerTests(unittest.TestCase):
    def test_sol_role_is_accounted_separately(self):
        result = summarize_usage(
            manifest(participant(role="SOL", model="gpt-5.6-sol")),
            [normalized(sequence=1, input_tokens=12, output_tokens=3, role="SOL", model="gpt-5.6-sol")],
        )
        self.assertEqual(result["roles"]["SOL"]["total_tokens"], 15)
        self.assertEqual(result["participants"][0]["role"], "SOL")

    def test_fixture_cli_reports_two_formats_baselines_roles_and_duplicate_once(self):
        result = subprocess.run(
            [sys.executable, str(USAGE), "--manifest", str(FIXTURES / "usage-manifest.json"), str(FIXTURES / "usage-cumulative.ndjson")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["measurement_state"], "COMPLETE")
        self.assertEqual(report["known"], {"input_tokens": 100, "output_tokens": 19, "total_tokens": 119})
        self.assertEqual(report["complete_total"], 119)
        self.assertEqual(report["roles"]["ASTRA"]["total_tokens"], 85)
        self.assertEqual(report["roles"]["LUNA"]["total_tokens"], 34)
        self.assertEqual(report["participants"][0]["cached_input_tokens"], 60)
        self.assertEqual(report["participants"][1]["output_tokens"], 4)

    def test_cumulative_updates_are_not_summed(self):
        result = summarize_usage(
            manifest(participant()),
            [
                normalized(sequence=1, input_tokens=110, output_tokens=12, model="model-a"),
                normalized(sequence=2, input_tokens=130, output_tokens=15, model="model-a"),
            ],
        )
        row = result["participants"][0]
        self.assertEqual(row["input_tokens"], 130)
        self.assertEqual(row["output_tokens"], 15)
        self.assertEqual(row["total_tokens"], 145)
        self.assertEqual(result["complete_total"], 145)

    def test_explicit_zero_baseline_can_report_real_zero(self):
        result = summarize_usage(
            manifest(participant(baseline={"input_tokens": 0, "output_tokens": 0})),
            [normalized(sequence=1, input_tokens=0, output_tokens=0, model="model-a")],
        )
        self.assertEqual(result["measurement_state"], "COMPLETE")
        self.assertEqual(result["known"], {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
        self.assertEqual(result["complete_total"], 0)

    def test_missing_or_null_baseline_is_unknown_not_zero(self):
        missing = summarize_usage(
            manifest(participant(include_baseline=False)),
            [normalized(sequence=1, input_tokens=0, output_tokens=0)],
        )
        self.assertIsNone(missing["participants"][0]["input_tokens"])
        self.assertIsNone(missing["participants"][0]["output_tokens"])
        self.assertEqual(missing["measurement_state"], "PARTIAL")
        self.assertIsNone(missing["complete_total"])

        null_baseline = summarize_usage(
            manifest(participant(baseline=None)),
            [normalized(sequence=1, input_tokens=20, output_tokens=3)],
        )
        self.assertIsNone(null_baseline["known"]["input_tokens"])
        self.assertIn("baseline", " ".join(null_baseline["limitations"]))

    def test_mixed_known_and_unknown_fields_are_partial(self):
        result = summarize_usage(
            manifest(participant(baseline={"input_tokens": 10, "output_tokens": None})),
            [normalized(sequence=1, input_tokens=20, output_tokens=4)],
        )
        row = result["participants"][0]
        self.assertEqual(row["input_tokens"], 10)
        self.assertIsNone(row["output_tokens"])
        self.assertIsNone(row["total_tokens"])
        self.assertEqual(result["known"]["input_tokens"], 10)
        self.assertIsNone(result["known"]["total_tokens"])
        self.assertEqual(result["measurement_state"], "PARTIAL")

    def test_all_unknown_snapshot_is_unavailable_and_not_zero(self):
        result = summarize_usage(
            manifest(participant()),
            [normalized(sequence=1, input_tokens=None, output_tokens=None)],
        )
        self.assertEqual(result["measurement_state"], "UNAVAILABLE")
        self.assertIsNone(result["known"]["input_tokens"])
        self.assertIsNone(result["known"]["output_tokens"])
        self.assertIsNone(result["complete_total"])
        self.assertTrue(any("UNKNOWN" in item for item in result["limitations"]))

    def test_subsets_are_reported_but_not_added_to_total(self):
        result = summarize_usage(
            manifest(participant(baseline={
                "input_tokens": 100,
                "output_tokens": 10,
                "cached_input_tokens": 80,
                "reasoning_output_tokens": 2,
            })),
            [normalized(
                sequence=1,
                input_tokens=120,
                output_tokens=15,
                cached_input_tokens=100,
                reasoning_output_tokens=5,
                total_tokens=135,
            )],
        )
        row = result["participants"][0]
        self.assertEqual(row["input_tokens"], 20)
        self.assertEqual(row["output_tokens"], 5)
        self.assertEqual(row["cached_input_tokens"], 20)
        self.assertEqual(row["reasoning_output_tokens"], 3)
        self.assertEqual(row["total_tokens"], 25)
        self.assertEqual(result["complete_total"], 25)

    def test_reordered_sequence_uses_latest_sequence_not_arrival_order(self):
        result = summarize_usage(
            manifest(participant()),
            [
                normalized(sequence=2, input_tokens=30, output_tokens=4),
                normalized(sequence=1, input_tokens=20, output_tokens=2),
            ],
        )
        self.assertEqual(result["participants"][0]["input_tokens"], 30)
        self.assertEqual(result["participants"][0]["output_tokens"], 4)
        self.assertEqual(result["measurement_state"], "COMPLETE")

    def test_reordered_timestamp_uses_latest_timestamp(self):
        result = summarize_usage(
            manifest(participant()),
            [
                normalized(timestamp="2026-01-02T00:00:00Z", input_tokens=30, output_tokens=4),
                normalized(timestamp="2026-01-01T00:00:00Z", input_tokens=20, output_tokens=2),
            ],
        )
        self.assertEqual(result["participants"][0]["total_tokens"], 34)

    def test_conflicting_sequence_and_timestamp_order_is_partial(self):
        result = summarize_usage(
            manifest(participant()),
            [
                normalized(sequence=1, timestamp=20, input_tokens=10, output_tokens=1),
                normalized(sequence=2, timestamp=10, input_tokens=20, output_tokens=2),
            ],
        )
        self.assertEqual(result["measurement_state"], "PARTIAL")
        self.assertIsNone(result["complete_total"])
        self.assertTrue(any("order disagree" in item for item in result["limitations"]))

    def test_counter_reset_is_not_reported_as_negative_usage(self):
        result = summarize_usage(
            manifest(participant()),
            [
                normalized(sequence=2, input_tokens=15, output_tokens=2),
                normalized(sequence=1, input_tokens=10, output_tokens=1),
                normalized(sequence=3, input_tokens=4, output_tokens=1),
            ],
        )
        row = result["participants"][0]
        self.assertEqual(result["measurement_state"], "PARTIAL")
        self.assertIsNone(row["input_tokens"])
        self.assertIsNone(row["output_tokens"])
        self.assertIsNone(result["complete_total"])
        self.assertTrue(any("reset/regression" in item for item in result["errors"]))

    def test_model_reroute_is_uncertain_and_withholds_complete_total(self):
        result = summarize_usage(
            manifest(participant(model="model-a")),
            [
                normalized(sequence=1, input_tokens=10, output_tokens=1, model="model-a"),
                normalized(sequence=2, input_tokens=20, output_tokens=2, model="model-b"),
            ],
        )
        row = result["participants"][0]
        self.assertEqual(row["model_attribution"], "UNCERTAIN")
        self.assertEqual(row["models_seen"], ["model-a", "model-b"])
        self.assertEqual(row["total_tokens"], 22)
        self.assertEqual(result["measurement_state"], "PARTIAL")
        self.assertIsNone(result["complete_total"])

    def test_prefinal_boundary_keeps_known_subtotal_but_not_complete_total(self):
        result = summarize_usage(
            manifest(participant(), includes_final_response=False),
            [normalized(sequence=1, input_tokens=20, output_tokens=4)],
        )
        self.assertEqual(result["final_response_included"], False)
        self.assertEqual(result["known"]["total_tokens"], 24)
        self.assertIsNone(result["complete_total"])
        self.assertEqual(result["measurement_state"], "PARTIAL")
        self.assertTrue(any("prefinal" in item for item in result["limitations"]))

    def test_incomplete_run_flag_withholds_complete_total(self):
        result = summarize_usage(
            manifest(participant(), run_complete=False),
            [normalized(sequence=1, input_tokens=20, output_tokens=4)],
        )
        self.assertEqual(result["final_response_included"], True)
        self.assertEqual(result["known"]["total_tokens"], 24)
        self.assertIsNone(result["complete_total"])
        self.assertEqual(result["measurement_state"], "PARTIAL")

        unknown_flags = manifest(participant())
        del unknown_flags["run_complete"]
        del unknown_flags["includes_final_response"]
        missing = summarize_usage(
            unknown_flags,
            [normalized(sequence=1, input_tokens=20, output_tokens=4)],
        )
        self.assertIsNone(missing["final_response_included"])
        self.assertIsNone(missing["complete_total"])

    def test_invalid_numbers_subsets_and_malformed_json_are_errors(self):
        result = subprocess.run(
            [sys.executable, str(USAGE), "--manifest", str(FIXTURES / "usage-manifest.json"), str(FIXTURES / "usage-invalid.ndjson")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertEqual(report["measurement_state"], "UNAVAILABLE")
        self.assertIsNone(report["complete_total"])
        joined = " ".join(report["errors"])
        self.assertIn("nonnegative integer", joined)
        self.assertIn("invalid subset", joined)
        self.assertIn("malformed JSON", joined)

    def test_unknown_event_shape_and_unselected_thread_are_not_usage(self):
        result = summarize_usage(
            manifest(participant()),
            [
                {"type": "usage_delta", "thread_id": "t1", "cumulative": {"input_tokens": 0, "output_tokens": 0}},
                normalized(thread_id="other", sequence=1, input_tokens=100, output_tokens=1),
            ],
        )
        self.assertEqual(result["measurement_state"], "UNAVAILABLE")
        self.assertIsNone(result["known"]["total_tokens"])
        self.assertTrue(any("unknown event shape" in item for item in result["errors"]))
        self.assertTrue(any("not listed in manifest" in item for item in result["errors"]))

    def test_unrelated_codex_lifecycle_event_is_ignored(self):
        result = summarize_usage(
            manifest(participant()),
            [
                {"method": "turn/started", "params": {"threadId": "t1"}},
                codex(input_tokens=20, output_tokens=3),
            ],
        )
        self.assertEqual(result["measurement_state"], "COMPLETE")
        self.assertEqual(result["complete_total"], 23)
        self.assertEqual(result["errors"], [])

    def test_conflicting_duplicate_is_not_silent(self):
        result = summarize_usage(
            manifest(participant()),
            [
                normalized(sequence=1, input_tokens=10, output_tokens=1),
                normalized(sequence=1, input_tokens=11, output_tokens=1),
            ],
        )
        self.assertEqual(result["measurement_state"], "PARTIAL")
        self.assertIsNone(result["complete_total"])
        self.assertTrue(any("conflicting duplicate" in item for item in result["errors"]))

    def test_event_role_conflict_is_invalid_mapping(self):
        result = summarize_usage(
            manifest(participant(role="ASTRA")),
            [normalized(sequence=1, input_tokens=10, output_tokens=1, role="LUNA")],
        )
        self.assertEqual(result["measurement_state"], "UNAVAILABLE")
        self.assertIsNone(result["complete_total"])
        self.assertTrue(any("conflicts with manifest role" in item for item in result["errors"]))

    def test_duplicate_json_line_is_reported_as_malformed(self):
        records, errors = parse_event_stream(
            '{"type":"usage","thread_id":"t1","cumulative":{"input_tokens":0,"output_tokens":0,"input_tokens":1}}\n'
        )
        self.assertEqual(records, [])
        self.assertTrue(any("malformed JSON" in item for item in errors))

    def test_manifest_duplicate_thread_mapping_is_invalid(self):
        result = summarize_usage(
            manifest(participant("t1"), participant("t1", role="LUNA", model="model-b")),
            [normalized(thread_id="t1", sequence=1, input_tokens=10, output_tokens=1)],
        )
        self.assertEqual(result["measurement_state"], "UNAVAILABLE")
        self.assertIsNone(result["complete_total"])
        self.assertTrue(any("multiple participants" in item for item in result["errors"]))

    def test_codex_event_requires_official_total_envelope(self):
        result = summarize_usage(
            manifest(participant()),
            [codex(input_tokens=20, output_tokens=3)],
        )
        self.assertEqual(result["known"], {"input_tokens": 20, "output_tokens": 3, "total_tokens": 23})
        self.assertEqual(result["measurement_state"], "COMPLETE")

        malformed = summarize_usage(
            manifest(participant()),
            [{"method": "thread/tokenUsage/updated", "params": {"threadId": "t1", "tokenUsage": {}}}],
        )
        self.assertEqual(malformed["measurement_state"], "UNAVAILABLE")
        self.assertTrue(any("tokenUsage.total" in item for item in malformed["errors"]))

    def test_legacy_report_shape_is_unchanged_without_stage_metadata(self):
        result = summarize_usage(
            manifest(participant()),
            [normalized(sequence=1, input_tokens=20, output_tokens=4, model="model-a")],
        )
        self.assertNotIn("stage_accounting", result)
        self.assertNotIn("stage", result["participants"][0])
        self.assertEqual(result["known"], {"input_tokens": 20, "output_tokens": 4, "total_tokens": 24})

    def test_disjoint_reused_thread_intervals_reconcile_exactly(self):
        result = summarize_usage(
            stage_manifest(
                participant(model="model-a"),
                intervals=[
                    stage_interval(
                        "i-recon",
                        "LUNA_RECON",
                        "t1",
                        {"input_tokens": 0, "output_tokens": 0},
                        {"input_tokens": 10, "output_tokens": 1},
                    ),
                    stage_interval(
                        "i-exec",
                        "LUNA_EXECUTION",
                        "t1",
                        {"input_tokens": 10, "output_tokens": 1},
                        {"input_tokens": 20, "output_tokens": 3},
                    ),
                ],
            ),
            [
                normalized(sequence=1, input_tokens=10, output_tokens=1, model="model-a"),
                normalized(sequence=2, input_tokens=20, output_tokens=3, model="model-a"),
            ],
        )
        accounting = result["stage_accounting"]
        self.assertEqual(result["participants"][0]["total_tokens"], 23)
        self.assertEqual(accounting["stages"]["LUNA_RECON"]["total_tokens"], 11)
        self.assertEqual(accounting["stages"]["LUNA_EXECUTION"]["total_tokens"], 12)
        self.assertEqual(accounting["residual"][0]["total_tokens"], 0)
        self.assertEqual(accounting["reconciliation"]["total_tokens"], True)
        self.assertEqual(accounting["measurement_state"], "COMPLETE")

    def test_stage_accounting_accepts_both_documented_event_envelopes(self):
        result = summarize_usage(
            stage_manifest(
                participant("t1", role="ASTRA", model="model-a"),
                participant("t2", role="LUNA", model="model-b"),
                intervals=[
                    stage_interval(
                        "i-astra",
                        "ASTRA_PLAN",
                        "t1",
                        {"input_tokens": 0, "output_tokens": 0},
                        {"input_tokens": 10, "output_tokens": 2},
                    ),
                    stage_interval(
                        "i-luna",
                        "LUNA_EXECUTION",
                        "t2",
                        {"input_tokens": 0, "output_tokens": 0},
                        {"input_tokens": 20, "output_tokens": 3},
                        model="model-b",
                    ),
                ],
            ),
            [
                normalized(thread_id="t1", sequence=1, input_tokens=10, output_tokens=2, model="model-a"),
                codex(thread_id="t2", input_tokens=20, output_tokens=3),
            ],
        )
        self.assertEqual(result["stage_accounting"]["stages"]["ASTRA_PLAN"]["total_tokens"], 12)
        self.assertEqual(result["stage_accounting"]["stages"]["LUNA_EXECUTION"]["total_tokens"], 23)
        self.assertEqual(result["known"]["total_tokens"], 35)

    def test_stage_repeated_cumulative_updates_are_not_summed(self):
        result = summarize_usage(
            stage_manifest(
                participant(),
                intervals=[stage_interval(
                    "i1",
                    "LUNA_RECON",
                    "t1",
                    {"input_tokens": 0, "output_tokens": 0},
                    {"input_tokens": 14, "output_tokens": 3},
                )],
            ),
            [
                normalized(sequence=1, input_tokens=10, output_tokens=2),
                normalized(sequence=2, input_tokens=14, output_tokens=3),
            ],
        )
        self.assertEqual(result["participants"][0]["total_tokens"], 17)
        self.assertEqual(result["stage_accounting"]["stages"]["LUNA_RECON"]["total_tokens"], 17)

    def test_invalid_stage_boundaries_never_report_exact_or_double_count(self):
        result = summarize_usage(
            stage_manifest(
                participant(),
                intervals=[
                    stage_interval(
                        "i-overlap-a",
                        "LUNA_RECON",
                        "t1",
                        {"input_tokens": 0, "output_tokens": 0},
                        {"input_tokens": 20, "output_tokens": 3},
                    ),
                    stage_interval(
                        "i-overlap-b",
                        "LUNA_EXECUTION",
                        "t1",
                        {"input_tokens": 10, "output_tokens": 1},
                        {"input_tokens": 20, "output_tokens": 3},
                    ),
                ],
            ),
            [
                normalized(sequence=1, input_tokens=10, output_tokens=1),
                normalized(sequence=2, input_tokens=20, output_tokens=3),
            ],
        )
        accounting = result["stage_accounting"]
        self.assertNotEqual(accounting["measurement_state"], "COMPLETE")
        self.assertTrue(all(interval["coverage"] != "EXACT" for interval in accounting["intervals"]))
        self.assertEqual(result["participants"][0]["total_tokens"], 23)

    def test_duplicate_missing_and_ambiguous_intervals_are_not_exact(self):
        duplicate = summarize_usage(
            stage_manifest(
                participant(),
                intervals=[
                    stage_interval(
                        "same-id",
                        "LUNA_RECON",
                        "t1",
                        {"input_tokens": 0, "output_tokens": 0},
                        {"input_tokens": 10, "output_tokens": 1},
                    ),
                    stage_interval(
                        "same-id",
                        "LUNA_EXECUTION",
                        "t1",
                        {"input_tokens": 10, "output_tokens": 1},
                        {"input_tokens": 20, "output_tokens": 3},
                    ),
                ],
            ),
            [normalized(sequence=1, input_tokens=10, output_tokens=1), normalized(sequence=2, input_tokens=20, output_tokens=3)],
        )
        self.assertTrue(all(item["coverage"] == "UNAVAILABLE" for item in duplicate["stage_accounting"]["intervals"]))

        missing_boundary = summarize_usage(
            stage_manifest(
                participant(),
                intervals=[stage_interval(
                    "missing-start",
                    "LUNA_RECON",
                    "t1",
                    None,
                    {"input_tokens": 20, "output_tokens": 3},
                )],
            ),
            [normalized(sequence=1, input_tokens=20, output_tokens=3)],
        )
        self.assertEqual(missing_boundary["stage_accounting"]["intervals"][0]["coverage"], "UNAVAILABLE")

        ambiguous = summarize_usage(
            stage_manifest(
                participant(),
                intervals=[stage_interval(
                    "ambiguous-end",
                    "LUNA_RECON",
                    "t1",
                    {"input_tokens": 0, "output_tokens": 0},
                    {"input_tokens": 10, "output_tokens": 1},
                )],
            ),
            [
                normalized(sequence=1, input_tokens=10, output_tokens=1),
                normalized(sequence=2, input_tokens=10, output_tokens=1),
            ],
        )
        self.assertEqual(ambiguous["stage_accounting"]["intervals"][0]["coverage"], "UNAVAILABLE")

    def test_missing_event_order_and_stage_metadata_are_conservative(self):
        result = summarize_usage(
            stage_manifest(
                participant(),
                intervals=[stage_interval(
                    "unsequenced",
                    "LUNA_RECON",
                    "t1",
                    {"input_tokens": 0, "output_tokens": 0},
                    {"input_tokens": 20, "output_tokens": 4},
                )],
            ),
            [
                normalized(input_tokens=10, output_tokens=2),
                normalized(input_tokens=20, output_tokens=4),
            ],
        )
        self.assertNotEqual(result["stage_accounting"]["measurement_state"], "COMPLETE")
        self.assertEqual(result["participants"][0]["total_tokens"], 24)

        partial = summarize_usage(
            stage_manifest(
                participant(),
                intervals=[stage_interval(
                    "missing-effort",
                    "LUNA_RECON",
                    "t1",
                    {"input_tokens": 0, "output_tokens": 0},
                    {"input_tokens": 20, "output_tokens": 4},
                    effort=None,
                )],
            ),
            [normalized(sequence=1, input_tokens=20, output_tokens=4)],
        )
        self.assertEqual(partial["stage_accounting"]["stages"]["LUNA_RECON"]["coverage"], "PARTIAL")
        self.assertEqual(partial["complete_total"], 24)

    def test_out_of_coverage_reversed_and_reset_intervals_are_unavailable(self):
        out_of_coverage = summarize_usage(
            stage_manifest(
                participant(),
                intervals=[stage_interval(
                    "i-gap",
                    "LUNA_RECON",
                    "t1",
                    {"input_tokens": 5, "output_tokens": 1},
                    {"input_tokens": 20, "output_tokens": 3},
                )],
            ),
            [normalized(sequence=1, input_tokens=10, output_tokens=1), normalized(sequence=2, input_tokens=20, output_tokens=3)],
        )
        self.assertEqual(out_of_coverage["stage_accounting"]["intervals"][0]["coverage"], "UNAVAILABLE")

        reversed_result = summarize_usage(
            stage_manifest(
                participant(),
                intervals=[stage_interval(
                    "i-reversed",
                    "LUNA_RECON",
                    "t1",
                    {"input_tokens": 20, "output_tokens": 3},
                    {"input_tokens": 10, "output_tokens": 1},
                )],
            ),
            [normalized(sequence=1, input_tokens=10, output_tokens=1), normalized(sequence=2, input_tokens=20, output_tokens=3)],
        )
        self.assertEqual(reversed_result["stage_accounting"]["intervals"][0]["coverage"], "UNAVAILABLE")

        reset_result = summarize_usage(
            stage_manifest(
                participant(),
                intervals=[stage_interval(
                    "i-reset",
                    "LUNA_RECON",
                    "t1",
                    {"input_tokens": 0, "output_tokens": 0},
                    {"input_tokens": 4, "output_tokens": 1},
                )],
            ),
            [normalized(sequence=1, input_tokens=10, output_tokens=1), normalized(sequence=2, input_tokens=4, output_tokens=1)],
        )
        self.assertEqual(reset_result["stage_accounting"]["intervals"][0]["coverage"], "UNAVAILABLE")

    def test_not_applicable_local_stage_does_not_add_tokens(self):
        result = summarize_usage(
            stage_manifest(
                participant(),
                intervals=[stage_interval(
                    "i-packet",
                    "PACKET",
                    None,
                    None,
                    None,
                    coverage="NOT_APPLICABLE",
                    model=None,
                    effort=None,
                    counter_epoch=None,
                )],
            ),
            [normalized(sequence=1, input_tokens=20, output_tokens=4)],
        )
        packet = result["stage_accounting"]["stages"]["PACKET"]
        self.assertEqual(packet["coverage"], "NOT_APPLICABLE")
        self.assertIsNone(packet["total_tokens"])
        self.assertEqual(result["participants"][0]["total_tokens"], 24)


if __name__ == "__main__":
    unittest.main()
