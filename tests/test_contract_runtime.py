import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import contracts


class RuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        (self.project / "module.py").write_text("before\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def packet(self, run_id="run-1", intent="change"):
        return {
            "run_id": run_id,
            "intent": intent,
            "goal": "Make the requested bounded change.",
            "decision_objective": "Choose and verify the requested implementation.",
            "observed_state": ["The project is available."],
            "key_code": ["module.py"],
            "constraints": ["Keep the public contract unchanged."],
            "attempted": ["The initial reproduction was recorded."],
            "evidence": ["The relevant command is reproducible."],
            "risk_flags": [],
            "output_contract": "Return a structured run bundle.",
        }

    def plan(self, run_id="run-1", intent="change", criteria=None, decision="IMPLEMENT"):
        return {
            "run_id": run_id,
            "plan_id": "plan-1",
            "agent_id": "astra-plan-1",
            "intent": intent,
            "decision": decision,
            "decision_objective": "Choose and verify the requested implementation.",
            "root_cause_status": "ESTABLISHED",
            "root_cause": "The bounded fixture has a known cause.",
            "facts_used": ["The project is available."],
            "architecture_decisions": ["Keep the public contract unchanged."],
            "change_scope": ["module.py"],
            "implementation_steps": ["Apply the bounded implementation."],
            "constraints": ["Keep the public contract unchanged."],
            "acceptance_criteria": criteria if criteria is not None else [
                {"id": "AC-1", "criterion": "The verification command passes."}
            ],
            "verification_plan": ["python -c pass"],
            "evidence_requests": [],
            "escalation_condition": "Request evidence if verification cannot run.",
        }

    def result(self, snapshot, status="IMPLEMENTATION_COMPLETE", criteria=None, commands=None):
        return {
            "run_id": "run-1",
            "plan_id": "plan-1",
            "agent_id": "luna-1",
            "status": status,
            "changes": ["Updated the bounded module."] if status == "IMPLEMENTATION_COMPLETE" else [],
            "local_decisions": [],
            "criteria_evidence": criteria if criteria is not None else [
                {"id": "AC-1", "status": "PASS", "evidence": "python -c pass exited 0."}
            ],
            "commands": commands if commands is not None else [
                {"id": "verify-1", "phase": "verification", "command": "python -c pass", "exit_code": 0, "result": "passed"}
            ],
            "failures_or_unknowns": [],
            "changed_paths": ["module.py"] if status == "IMPLEMENTATION_COMPLETE" else [],
            "snapshot": snapshot,
        }

    def verification(self, snapshot, state="DONE", criteria=None):
        return {
            "run_id": "run-1",
            "plan_id": "plan-1",
            "agent_id": "sol-verification-1",
            "authority": "SOL",
            "state": state,
            "criteria": criteria if criteria is not None else [
                {"id": "AC-1", "status": "PASS", "evidence": "The verification passed."}
            ],
            "decisive_evidence": ["The verification passed."],
            "remaining_problem": "" if state == "DONE" else "The run needs another bounded check.",
            "next_open_question": "" if state == "DONE" else "Which check should run next?",
            "next_scope": [] if state == "DONE" else ["module.py"],
            "evidence_requests": [],
            "attempts": {"sol_verifications": 1, "luna_attempts": 1, "astra_plans": 1},
            "limits": {"max_sol_verifications": 5, "max_luna_attempts": 2, "max_astra_plans": 5},
            "snapshot": snapshot,
        }

    def bundle(self, baseline, final, intent="change", plan=None, result=None, verification=None):
        return {
            "run_id": "run-1",
            "intent": intent,
            "task_packet": self.packet(intent=intent),
            "plan": plan or self.plan(intent=intent),
            "result": result or self.result(final),
            "verification": verification or self.verification(final),
            "dispatch": {
                "plan": {"agent_id": "astra-plan-1", "role": "ASTRA_PLAN", "model": "gpt-6-astra", "reasoning_effort": "medium", "source": "host", "confirmed": True},
                "execution": {"agent_id": "luna-1", "role": "LUNA_EXECUTION", "model": "gpt-5.6-luna", "reasoning_effort": "max", "source": "host", "confirmed": True},
                "verification": {"agent_id": "sol-verification-1", "role": "SOL_VERIFICATION", "model": "gpt-5.6-sol", "reasoning_effort": "high", "source": "host", "confirmed": True},
            },
            "snapshot": final,
            "baseline_snapshot": baseline,
        }

    def fast_bundle(self, baseline, final):
        packet = self.packet()
        packet.update(
            {
                "plan_id": "fast-plan-1",
                "execution_scope": ["module.py"],
                "acceptance_criteria": [
                    {"id": "AC-1", "criterion": "The verification command passes."}
                ],
                "verification_plan": ["python -c pass"],
            }
        )
        result = self.result(final)
        result["plan_id"] = "fast-plan-1"
        verification = self.verification(final)
        verification["plan_id"] = "fast-plan-1"
        verification["attempts"]["astra_plans"] = 0
        verification["limits"]["max_sol_verifications"] = 2
        verification["limits"]["max_astra_plans"] = 0
        return {
            "run_id": "run-1",
            "intent": "change",
            "dispatch_mode": "FAST",
            "workflow_variant": "fast_luna_sol",
            "routing_decision": {
                "tier": 0,
                "intent": "change",
                "reasons": ["small bounded change"],
                "risk_flags": [],
                "changed_paths": ["module.py"],
                "source_mutation": True,
                "eligibility": {
                    "bounded_scope": True,
                    "known_behavior": True,
                    "known_dependencies": True,
                    "sufficient_evidence": True,
                    "direct_verification": True,
                    "unresolved_failure": False,
                    "material_risk": False,
                    "material_architectural_uncertainty": False,
                    "conflicting_evidence": False,
                    "repeated_unresolved_failures": False,
                },
            },
            "task_packet": packet,
            "result": result,
            "verification": verification,
            "dispatch": {
                "execution": {
                    "agent_id": "luna-1",
                    "role": "LUNA_EXECUTION",
                    "model": "gpt-5.6-luna",
                    "reasoning_effort": "max",
                    "source": "host",
                    "confirmed": True,
                },
                "verification": {
                    "agent_id": "sol-verification-1",
                    "role": "SOL_VERIFICATION",
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "high",
                    "source": "host",
                    "confirmed": True,
                },
            },
            "snapshot": final,
            "baseline_snapshot": baseline,
        }

    def test_complete_run_accepts_reproduction_failure_and_resolved_verification(self):
        baseline = contracts.fingerprint_paths(["module.py"], self.project)
        (self.project / "module.py").write_text("after\n", encoding="utf-8")
        final = contracts.fingerprint_paths(["module.py"], self.project)
        commands = [
            {"id": "repro-1", "phase": "reproduction", "command": "python -c fail", "exit_code": 1, "result": "known failure"},
            {"id": "verify-1", "phase": "verification", "command": "python -c pass", "exit_code": 1, "result": "first attempt failed"},
            {"id": "verify-2", "phase": "verification", "command": "python -c pass", "exit_code": 0, "result": "rerun passed", "supersedes": "verify-1"},
        ]
        result = self.result(final, commands=commands)
        bundle = self.bundle(baseline, final, result=result)
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertTrue(valid, errors)

    def test_fast_run_accepts_two_role_bundle_with_sol_completion_gate(self):
        baseline = contracts.fingerprint_paths(["module.py"], self.project)
        (self.project / "module.py").write_text("after\n", encoding="utf-8")
        final = contracts.fingerprint_paths(["module.py"], self.project)
        bundle = self.fast_bundle(baseline, final)
        valid, errors, summary = contracts.check_run(bundle, self.project)
        self.assertTrue(valid, errors)
        self.assertEqual(summary["state"], "DONE")

    def test_fast_run_rejects_an_astra_receipt(self):
        baseline = contracts.fingerprint_paths(["module.py"], self.project)
        (self.project / "module.py").write_text("after\n", encoding="utf-8")
        final = contracts.fingerprint_paths(["module.py"], self.project)
        bundle = self.fast_bundle(baseline, final)
        bundle["dispatch"]["plan"] = {
            "agent_id": "astra-plan-1",
            "role": "ASTRA_PLAN",
            "model": "gpt-6-astra",
            "reasoning_effort": "medium",
            "source": "host",
            "confirmed": True,
        }
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(errors)
        self.assertTrue(any("dispatch" in error for error in errors))

    def test_done_rejects_empty_or_failed_criteria_in_schema(self):
        snapshot = {"kind": "scoped", "sha256": "0" * 64, "paths": ["module.py"], "revision": "fixture"}
        base = self.verification(snapshot)
        for mutation in (
            {"criteria": []},
            {"criteria": [{"id": "AC-1", "status": "FAIL", "evidence": "failed"}]},
            {"criteria": [{"id": "AC-1", "status": "PASS", "evidence": "   "}]},
            {"remaining_problem": "still open"},
            {"next_open_question": "still open"},
            {"next_scope": ["module.py"]},
            {"evidence_requests": [{"id": "ER-1", "targets": ["module.py"], "reason": "need more"}]},
        ):
            candidate = copy.deepcopy(base)
            candidate.update(mutation)
            self.assertTrue(contracts.validate_instance("sol-verification", candidate), mutation)

    def test_plan_evidence_request_has_no_fabricated_plan(self):
        candidate = self.plan(decision="REQUEST_EVIDENCE")
        candidate["implementation_steps"] = []
        candidate["acceptance_criteria"] = []
        candidate["verification_plan"] = []
        candidate["evidence_requests"] = [{"id": "ER-1", "targets": ["module.py"], "reason": "Need the reproduction trace."}]
        self.assertFalse(contracts.validate_instance("astra-plan", candidate), candidate)
        candidate["implementation_steps"] = ["Invent a fix"]
        self.assertTrue(contracts.validate_instance("astra-plan", candidate))

    def test_duplicate_and_missing_criteria_are_rejected_by_run_gate(self):
        baseline = contracts.fingerprint_paths(["module.py"], self.project)
        final = baseline
        plan = self.plan(criteria=[
            {"id": "AC-1", "criterion": "One."},
            {"id": "AC-1", "criterion": "Two."},
        ])
        bundle = self.bundle(baseline, final, plan=plan)
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("duplicate" in error for error in errors))

        plan = self.plan(criteria=[
            {"id": "AC-1", "criterion": "One."},
            {"id": "AC-2", "criterion": "Two."},
        ])
        result = self.result(final, criteria=[{"id": "AC-1", "status": "PASS", "evidence": "only one"}])
        bundle = self.bundle(baseline, final, plan=plan, result=result)
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("coverage" in error for error in errors))

    def test_invalid_receipt_and_luna_as_judge_are_rejected(self):
        snapshot = contracts.fingerprint_paths(["module.py"], self.project)
        bundle = self.bundle(snapshot, snapshot)
        bundle["dispatch"]["plan"]["model"] = "gpt-5.6-luna"
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("gpt-6-astra" in error for error in errors))
        bundle = self.bundle(snapshot, snapshot)
        bundle["dispatch"]["verification"]["role"] = "LUNA"
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("wrong role" in error for error in errors))

        bundle = self.bundle(snapshot, snapshot)
        bundle["dispatch"]["execution"]["agent_id"] = "astra-plan-1"
        bundle["result"]["agent_id"] = "astra-plan-1"
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("both ASTRA plan and LUNA execution" in error for error in errors))

    def test_legacy_adjudication_field_cannot_complete_a_run(self):
        snapshot = contracts.fingerprint_paths(["module.py"], self.project)
        bundle = self.bundle(snapshot, snapshot)
        bundle["adjudication"] = bundle.pop("verification")
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("verification" in error for error in errors))

    def test_verification_counter_overflow_is_blocked(self):
        snapshot = contracts.fingerprint_paths(["module.py"], self.project)
        bundle = self.bundle(snapshot, snapshot)
        bundle["verification"]["attempts"]["sol_verifications"] = 6
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("cannot exceed" in error for error in errors))

    def test_done_requires_decision_approved_for_packet_intent(self):
        snapshot = contracts.fingerprint_paths(["module.py"], self.project)
        plan = self.plan(decision="REPLAN")
        bundle = self.bundle(snapshot, snapshot, plan=plan)
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("approved plan decision" in error for error in errors))

    def test_readonly_baseline_catches_false_empty_changed_paths(self):
        baseline = contracts.fingerprint_paths(["module.py"], self.project)
        (self.project / "module.py").write_text("mutated\n", encoding="utf-8")
        current = contracts.fingerprint_paths(["module.py"], self.project)
        result = self.result(current, status="IMPLEMENTATION_BLOCKED")
        result["changed_paths"] = []
        bundle = self.bundle(baseline, current, intent="review", result=result,
                             verification=self.verification(current, state="BLOCKED"))
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("baseline" in error or "read-only" in error for error in errors))

    def test_resolution_links_must_be_later_passing_same_command(self):
        snapshot = contracts.fingerprint_paths(["module.py"], self.project)
        commands = [
            {"id": "verify-0", "phase": "verification", "command": "python -c pass", "exit_code": 0, "result": "passed"},
            {"id": "verify-1", "phase": "verification", "command": "python -c pass", "exit_code": 1, "result": "failed", "resolved_by": "verify-0"},
        ]
        result = self.result(snapshot, commands=commands)
        bundle = self.bundle(snapshot, snapshot, result=result)
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("later" in error for error in errors))
        commands[1]["resolved_by"] = "verify-0"
        commands[0]["command"] = "python -c other"
        result = self.result(snapshot, commands=commands)
        bundle = self.bundle(snapshot, snapshot, result=result)
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("same command" in error for error in errors))

    def test_next_stage_mapping_intent_guard_and_cap(self):
        expected = {
            "RETRY": "LUNA_EXECUTION",
            "REPLAN": "ASTRA_PLAN",
            "EVIDENCE": "LUNA_EVIDENCE",
            "DONE": "STOP",
            "BLOCKED": "STOP_BLOCKED",
        }
        for state, stage in expected.items():
            result = contracts.next_stage({"authority": "SOL", "state": state}, handoff_count=0, intent="change")
            self.assertEqual(result["next_stage"], stage)
        capped = contracts.next_stage({"authority": "SOL", "state": "DONE"}, handoff_count=5, max_handoffs=5, intent="change")
        self.assertEqual(capped["next_stage"], "STOP")
        capped_retry = contracts.next_stage({"authority": "SOL", "state": "RETRY"}, handoff_count=5, max_handoffs=5, intent="change")
        self.assertEqual(capped_retry["next_stage"], "STOP_BLOCKED")
        with self.assertRaises(contracts.ContractError):
            contracts.next_stage({"state": "RETRY"})
        with self.assertRaises(contracts.ContractError):
            contracts.next_stage({"state": "RETRY", "changed_paths": ["module.py"]}, intent="review")

    def test_observation_only_readonly_run_and_missing_observation(self):
        baseline = contracts.fingerprint_paths(["module.py"], self.project)
        plan = self.plan(intent="review", decision="INVESTIGATE_MORE")
        plan["verification_plan"] = []
        plan["observation_plan"] = [{"id": "OBS-1", "criterion": "The module remains unchanged."}]
        result = self.result(baseline, status="IMPLEMENTATION_COMPLETE")
        result["changes"] = []
        result["changed_paths"] = []
        result["commands"] = []
        result["observations"] = [{"id": "OBS-1", "status": "PASS", "evidence": "The file was inspected and remained unchanged."}]
        bundle = self.bundle(baseline, baseline, intent="review", plan=plan, result=result)
        bundle["verification"] = self.verification(baseline, state="DONE")
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertTrue(valid, errors)

        result["observations"][0]["status"] = "UNPROVEN"
        bundle["result"] = result
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("observation" in error for error in errors))

    def test_git_fingerprint_tracks_dirty_and_untracked_state(self):
        git = shutil_which("git")
        if git is None:
            self.skipTest("git is unavailable")
        self.git_run([git, "init", "-q", str(self.project)])
        self.git_run([git, "-C", str(self.project), "config", "user.email", "test@example.invalid"])
        self.git_run([git, "-C", str(self.project), "config", "user.name", "LinkedAI Test"])
        self.git_run([git, "-C", str(self.project), "add", "module.py"])
        self.git_run([git, "-C", str(self.project), "commit", "-q", "-m", "initial"])
        clean = contracts.fingerprint_git(self.project)
        self.assertIn("module.py", clean["paths"])
        (self.project / "module.py").write_text("dirty\n", encoding="utf-8")
        dirty = contracts.fingerprint_git(self.project)
        self.assertNotEqual(clean["sha256"], dirty["sha256"])
        (self.project / "new.py").write_text("new\n", encoding="utf-8")
        untracked = contracts.fingerprint_git(self.project)
        self.assertIn("new.py", untracked["paths"])
        self.assertNotEqual(dirty["sha256"], untracked["sha256"])

    def test_git_fingerprint_represents_tracked_deletion_as_tombstone(self):
        git = shutil_which("git")
        if git is None:
            self.skipTest("git is unavailable")
        self.git_run([git, "init", "-q", str(self.project)])
        self.git_run([git, "-C", str(self.project), "config", "user.email", "test@example.invalid"])
        self.git_run([git, "-C", str(self.project), "config", "user.name", "LinkedAI Test"])
        self.git_run([git, "-C", str(self.project), "add", "module.py"])
        self.git_run([git, "-C", str(self.project), "commit", "-q", "-m", "initial"])

        clean = contracts.fingerprint_git(self.project)
        (self.project / "module.py").unlink()
        deleted = contracts.fingerprint_git(self.project)

        self.assertIn("module.py", deleted["paths"])
        self.assertNotEqual(clean["sha256"], deleted["sha256"])

    def test_git_fingerprint_includes_index_metadata_with_same_worktree_and_status(self):
        git = shutil_which("git")
        if git is None:
            self.skipTest("git is unavailable")
        self.git_run([git, "init", "-q", str(self.project)])
        self.git_run([git, "-C", str(self.project), "config", "user.email", "test@example.invalid"])
        self.git_run([git, "-C", str(self.project), "config", "user.name", "LinkedAI Test"])
        self.git_run([git, "-C", str(self.project), "add", "module.py"])
        self.git_run([git, "-C", str(self.project), "commit", "-q", "-m", "initial"])

        (self.project / "module.py").write_text("staged-one\n", encoding="utf-8")
        self.git_run([git, "-C", str(self.project), "add", "module.py"])
        (self.project / "module.py").write_text("worktree\n", encoding="utf-8")
        first = contracts.fingerprint_git(self.project)
        first_status = self.git_output(
            [git, "-C", str(self.project), "status", "--porcelain=v1", "--untracked-files=all", "-z"]
        )

        (self.project / "module.py").write_text("staged-two\n", encoding="utf-8")
        self.git_run([git, "-C", str(self.project), "add", "module.py"])
        (self.project / "module.py").write_text("worktree\n", encoding="utf-8")
        second = contracts.fingerprint_git(self.project)
        second_status = self.git_output(
            [git, "-C", str(self.project), "status", "--porcelain=v1", "--untracked-files=all", "-z"]
        )

        self.assertEqual(first_status, second_status)
        self.assertEqual((self.project / "module.py").read_text(encoding="utf-8"), "worktree\n")
        self.assertEqual(first["paths"], second["paths"])
        self.assertEqual(first["revision"], second["revision"])
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_check_run_rejects_untracked_file_and_changed_revision_after_git_snapshot(self):
        git = shutil_which("git")
        if git is None:
            self.skipTest("git is unavailable")
        self.git_run([git, "init", "-q", str(self.project)])
        self.git_run([git, "-C", str(self.project), "config", "user.email", "test@example.invalid"])
        self.git_run([git, "-C", str(self.project), "config", "user.name", "LinkedAI Test"])
        self.git_run([git, "-C", str(self.project), "add", "module.py"])
        self.git_run([git, "-C", str(self.project), "commit", "-q", "-m", "initial"])
        baseline = contracts.fingerprint_git(self.project)
        (self.project / "module.py").write_text("after\n", encoding="utf-8")
        final = contracts.fingerprint_git(self.project)
        bundle = self.bundle(baseline, final)
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertTrue(valid, errors)
        (self.project / "new.py").write_text("untracked\n", encoding="utf-8")
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("stale" in error for error in errors))
        self.git_run([git, "-C", str(self.project), "add", "module.py"])
        self.git_run([git, "-C", str(self.project), "commit", "-q", "-m", "changed"])
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("stale" in error for error in errors))

    def git_run(self, command):
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def git_output(self, command):
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return result.stdout


def shutil_which(command):
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / command
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


if __name__ == "__main__":
    unittest.main()
