import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import contracts


class ApprovalGatedFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        (self.project / "module.py").write_text("before\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def packet(self):
        return {
            "run_id": "approval-run-1",
            "plan_id": "approval-plan-1",
            "intent": "change",
            "goal": "Make the approved bounded change.",
            "decision_objective": "Choose and verify the requested implementation.",
            "observed_state": ["The project is available."],
            "key_code": ["module.py"],
            "constraints": ["Keep the public contract unchanged."],
            "attempted": ["The initial reproduction was recorded."],
            "evidence": ["The relevant command is reproducible."],
            "risk_flags": [],
            "execution_scope": ["module.py"],
            "acceptance_criteria": [
                {"id": "AC-1", "criterion": "The verification command passes."}
            ],
            "verification_plan": ["python -c pass"],
            "output_contract": "Return a structured run bundle.",
        }

    def plan(self):
        return {
            "run_id": "approval-run-1",
            "plan_id": "approval-plan-1",
            "agent_id": "astra-plan-approval-1",
            "intent": "change",
            "decision": "IMPLEMENT",
            "decision_objective": "Choose and verify the requested implementation.",
            "root_cause_status": "ESTABLISHED",
            "root_cause": "The bounded fixture has a known cause.",
            "facts_used": ["The project is available."],
            "architecture_decisions": ["Keep the public contract unchanged."],
            "change_scope": ["module.py"],
            "implementation_steps": ["Apply the bounded implementation."],
            "constraints": ["Keep the public contract unchanged."],
            "acceptance_criteria": [
                {"id": "AC-1", "criterion": "The verification command passes."}
            ],
            "verification_plan": ["python -c pass"],
            "evidence_requests": [],
            "escalation_condition": "Request evidence if verification cannot run.",
        }

    def routing(self):
        return {
            "tier": 1,
            "intent": "change",
            "reasons": ["ordinary bounded bug fix"],
            "risk_flags": [],
            "changed_paths": ["module.py"],
            "source_mutation": True,
            "approval_policy": "REQUIRED",
            "eligibility": {
                "bounded_scope": False,
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
        }

    def receipt(self, slot):
        if slot == "plan":
            return {
                "agent_id": "astra-plan-approval-1",
                "role": "ASTRA_PLAN",
                "model": "gpt-6-astra",
                "reasoning_effort": "medium",
                "source": "host",
                "confirmed": True,
            }
        if slot == "execution":
            return {
                "agent_id": "luna-execution-approval-1",
                "role": "LUNA_EXECUTION",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "max",
                "source": "host",
                "confirmed": True,
            }
        return {
            "agent_id": "sol-verification-approval-1",
            "role": "SOL_VERIFICATION",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "source": "host",
            "confirmed": True,
        }

    def gate(self):
        packet = self.packet()
        plan = self.plan()
        routing = self.routing()
        baseline = contracts.fingerprint_paths(["module.py"], self.project)
        approval = {
            "approval_id": "approval-event-1",
            "state": "WAITING_FOR_APPROVAL",
            "decision": "PENDING",
            "run_id": "approval-run-1",
            "plan_generation": 1,
            "plan_id": "approval-plan-1",
            **contracts.approval_bindings(plan, packet, baseline),
        }
        return {
            "run_id": "approval-run-1",
            "intent": "change",
            "dispatch_mode": "STANDARD",
            "workflow_variant": "plan_approval_gate",
            "routing_decision": routing,
            "task_packet": packet,
            "plan": plan,
            "dispatch": {"plan": self.receipt("plan")},
            "baseline_snapshot": baseline,
            "approval": approval,
        }

    def approved_bundle(self):
        gate = self.gate()
        (self.project / "module.py").write_text("after\n", encoding="utf-8")
        final = contracts.fingerprint_paths(["module.py"], self.project)
        plan = gate["plan"]
        result = {
            "run_id": "approval-run-1",
            "plan_id": "approval-plan-1",
            "agent_id": "luna-execution-approval-1",
            "status": "IMPLEMENTATION_COMPLETE",
            "changes": ["Updated the bounded module."],
            "local_decisions": [],
            "criteria_evidence": [
                {"id": "AC-1", "status": "PASS", "evidence": "python -c pass exited 0."}
            ],
            "commands": [
                {
                    "id": "verify-1",
                    "phase": "verification",
                    "command": "python -c pass",
                    "exit_code": 0,
                    "result": "passed",
                }
            ],
            "failures_or_unknowns": [],
            "changed_paths": ["module.py"],
            "snapshot": final,
        }
        verification = {
            "run_id": "approval-run-1",
            "plan_id": "approval-plan-1",
            "agent_id": "sol-verification-approval-1",
            "authority": "SOL",
            "state": "DONE",
            "criteria": [
                {"id": "AC-1", "status": "PASS", "evidence": "The verification passed."}
            ],
            "decisive_evidence": ["The verification passed."],
            "remaining_problem": "",
            "next_open_question": "",
            "next_scope": [],
            "evidence_requests": [],
            "attempts": {"sol_verifications": 1, "luna_attempts": 1, "astra_plans": 1},
            "limits": {"max_sol_verifications": 2, "max_luna_attempts": 2, "max_astra_plans": 1},
            "snapshot": final,
        }
        approval = copy.deepcopy(gate["approval"])
        approval.update(
            {
                "state": "APPROVED",
                "decision": "APPROVE_IMPLEMENTATION",
                "actor": "USER",
                "approved_at": "2026-09-08T00:00:00Z",
            }
        )
        gate.update(
            {
                "workflow_variant": "approved_plan_fast_luna_sol",
                "task_packet": gate["task_packet"],
                "approval": approval,
                "result": result,
                "verification": verification,
                "dispatch": {
                    "plan": self.receipt("plan"),
                    "execution": self.receipt("execution"),
                    "verification": self.receipt("verification"),
                },
                "snapshot": final,
            }
        )
        return gate

    def test_plan_gate_pauses_and_is_not_completion(self):
        gate = self.gate()
        self.assertEqual(contracts.validate_instance("plan-gate", gate), [])
        valid, errors, summary = contracts.check_plan_gate(gate, self.project)
        self.assertTrue(valid, errors)
        self.assertEqual(summary["state"], "WAITING_FOR_APPROVAL")
        self.assertEqual(summary["next_action"], "USER_APPROVAL")
        self.assertNotEqual(summary["state"], "DONE")

    def test_check_plan_command_reports_waiting_state(self):
        gate = self.gate()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as stream:
            json.dump(gate, stream)
            stream.flush()
            result = subprocess.run(
                [
                    str(ROOT / "scripts" / "linkedai"),
                    "check-plan",
                    stream.name,
                    "--root",
                    str(self.project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"state": "WAITING_FOR_APPROVAL"', result.stdout)

    def test_plan_gate_rejects_repository_drift_before_approval(self):
        gate = self.gate()
        (self.project / "module.py").write_text("drifted\n", encoding="utf-8")
        valid, errors, summary = contracts.check_plan_gate(gate, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("stale" in error for error in errors))
        self.assertEqual(summary["next_action"], "REPLAN")

    def test_approved_plan_fast_preserves_astra_and_accepts_sol_done(self):
        bundle = self.approved_bundle()
        self.assertEqual(contracts.validate_instance("run-bundle", bundle), [])
        valid, errors, summary = contracts.check_run(bundle, self.project)
        self.assertTrue(valid, errors)
        self.assertEqual(summary["state"], "DONE")

    def test_approved_plan_fast_rejects_tampered_plan_hash(self):
        bundle = self.approved_bundle()
        bundle["approval"]["plan_hash"] = "f" * 64
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("approval.plan_hash" in error for error in errors))

    def test_execution_before_user_approval_is_rejected(self):
        bundle = self.approved_bundle()
        bundle["approval"] = self.gate()["approval"]
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(errors)

    def test_approved_plan_replan_requires_a_new_approval_gate(self):
        bundle = self.approved_bundle()
        bundle["verification"]["state"] = "REPLAN"
        result = contracts.next_stage(bundle, intent="change")
        self.assertEqual(result["next_stage"], "ASTRA_PLAN_APPROVAL")
        self.assertTrue(result["allowed"])

    def test_canonical_hash_is_independent_of_object_key_order(self):
        self.assertEqual(
            contracts.canonical_sha256({"a": 1, "b": 2}),
            contracts.canonical_sha256({"b": 2, "a": 1}),
        )


if __name__ == "__main__":
    unittest.main()
