import copy
import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import contracts


class V8WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        (self.project / "module.py").write_text("before\n", encoding="utf-8")
        self.baseline = contracts.fingerprint_paths(["module.py"], self.project)
        (self.project / "module.py").write_text("after\n", encoding="utf-8")
        self.final = contracts.fingerprint_paths(["module.py"], self.project)

    def tearDown(self):
        self.temp.cleanup()

    def packet(self):
        return {
            "run_id": "v8-run-1",
            "plan_id": "v8-plan-1",
            "intent": "change",
            "goal": "Apply the bounded V8 workflow change.",
            "decision_objective": "Choose and verify the requested implementation.",
            "observed_state": ["The fixture is available."],
            "key_code": ["module.py"],
            "constraints": ["Keep the public contract unchanged."],
            "attempted": ["Recorded the initial state."],
            "evidence": ["The verification command is reproducible."],
            "risk_flags": [],
            "execution_scope": ["module.py"],
            "acceptance_criteria": [
                {"id": "AC-1", "criterion": "The verification command passes."}
            ],
            "verification_plan": ["python -c pass"],
            "output_contract": "Return a checked V8 run bundle.",
        }

    def plan(self):
        return {
            "run_id": "v8-run-1",
            "plan_id": "v8-plan-1",
            "agent_id": "astra-v8-1",
            "intent": "change",
            "decision": "IMPLEMENT",
            "decision_objective": "Choose and verify the requested implementation.",
            "root_cause_status": "ESTABLISHED",
            "root_cause": "The fixture has a known bounded cause.",
            "facts_used": ["The fixture is available."],
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
            "reasons": ["ordinary bounded change"],
            "risk_flags": [],
            "changed_paths": ["module.py"],
            "source_mutation": True,
            "approval_policy": "AUTO",
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

    def result(self):
        return {
            "run_id": "v8-run-1",
            "plan_id": "v8-plan-1",
            "agent_id": "luna-v8-exec-1",
            "status": "IMPLEMENTATION_COMPLETE",
            "changes": ["Applied the bounded implementation."],
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
            "snapshot": self.final,
        }

    def verification(self, authority):
        if authority == "SOL":
            attempts = {"sol_verifications": 1, "luna_attempts": 1, "astra_plans": 1}
            limits = {"max_sol_verifications": 2, "max_luna_attempts": 2, "max_astra_plans": 2}
            agent_id = "sol-v8-verify-1"
        else:
            attempts = {"luna_verifications": 1, "luna_attempts": 1, "astra_plans": 1}
            limits = {"max_luna_verifications": 2, "max_luna_attempts": 2, "max_astra_plans": 2}
            agent_id = "luna-v8-verify-1"
        return {
            "run_id": "v8-run-1",
            "plan_id": "v8-plan-1",
            "agent_id": agent_id,
            "authority": authority,
            "state": "DONE",
            "criteria": [
                {"id": "AC-1", "status": "PASS", "evidence": "The command passed."}
            ],
            "decisive_evidence": ["The final snapshot is fresh and the check passed."],
            "remaining_problem": "",
            "next_open_question": "",
            "next_scope": [],
            "evidence_requests": [],
            "attempts": attempts,
            "limits": limits,
            "snapshot": self.final,
        }

    def bundle(self, variant, authority):
        verification = self.verification(authority)
        verification_receipt = {
            "agent_id": verification["agent_id"],
            "role": "SOL_VERIFICATION" if authority == "SOL" else "LUNA_VERIFICATION",
            "model": "gpt-5.6-sol" if authority == "SOL" else "gpt-5.6-luna",
            "reasoning_effort": "high" if authority == "SOL" else "max",
            "source": "host",
            "confirmed": True,
        }
        return {
            "run_id": "v8-run-1",
            "intent": "change",
            "source_mutation": True,
            "dispatch_mode": "STANDARD",
            "workflow_variant": variant,
            "routing_decision": self.routing(),
            "task_packet": self.packet(),
            "plan": self.plan(),
            "result": self.result(),
            "verification": verification,
            "dispatch": {
                "plan": {
                    "agent_id": "astra-v8-1",
                    "role": "ASTRA_PLAN",
                    "model": "gpt-6-astra",
                    "reasoning_effort": "high",
                    "source": "host",
                    "confirmed": True,
                },
                "execution": {
                    "agent_id": "luna-v8-exec-1",
                    "role": "LUNA_EXECUTION",
                    "model": "gpt-5.6-luna",
                    "reasoning_effort": "max",
                    "source": "host",
                    "confirmed": True,
                },
                "verification": verification_receipt,
            },
            "snapshot": self.final,
            "baseline_snapshot": self.baseline,
        }

    def test_main_v8_bundle_accepts_astra_high_and_sol_high(self):
        bundle = self.bundle(contracts.ASTRA_HIGH_LUNA_SOL_VARIANT, "SOL")
        valid, errors, summary = contracts.check_run(bundle, self.project)
        self.assertTrue(valid, errors)
        self.assertEqual(summary["state"], "DONE")

    def test_echo_bundle_accepts_luna_max_verification(self):
        bundle = self.bundle(contracts.ASTRA_HIGH_LUNA_ECHO_VARIANT, "LUNA")
        valid, errors, summary = contracts.check_run(bundle, self.project)
        self.assertTrue(valid, errors)
        self.assertEqual(summary["state"], "DONE")

    def test_active_main_bundle_rejects_medium_astra_receipt(self):
        bundle = self.bundle(contracts.ASTRA_HIGH_LUNA_SOL_VARIANT, "SOL")
        bundle["dispatch"]["plan"]["reasoning_effort"] = "medium"
        valid, errors, _ = contracts.check_run(bundle, self.project)
        self.assertFalse(valid)
        self.assertTrue(any("reasoning_effort high" in error for error in errors))

    def test_echo_replan_returns_to_astra_plan(self):
        bundle = self.bundle(contracts.ASTRA_HIGH_LUNA_ECHO_VARIANT, "LUNA")
        bundle["verification"] = copy.deepcopy(bundle["verification"])
        bundle["verification"].update(
            {
                "state": "REPLAN",
                "remaining_problem": "The implementation strategy is invalid.",
                "next_open_question": "Which replacement strategy satisfies the plan?",
                "next_scope": ["module.py"],
            }
        )
        result = contracts.next_stage(bundle, intent="change")
        self.assertEqual(result["next_stage"], "ASTRA_PLAN")
        self.assertTrue(result["allowed"])


if __name__ == "__main__":
    unittest.main()
