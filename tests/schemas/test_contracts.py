import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import contracts


class ContractTests(unittest.TestCase):
    def load(self, name):
        return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))

    def test_active_schemas_are_draft_2020_12_meta_valid(self):
        for name in contracts.ACTIVE_SCHEMAS:
            with self.subTest(name=name):
                self.assertEqual(contracts.validate_schema(name), [])

    def test_checked_in_packet_and_current_run_fixture_validate(self):
        packet = contracts.load_json(ROOT / "tests/fixtures/example-task-packet.json")
        self.assertEqual(contracts.validate_instance("task-packet", packet), [])
        bundle = contracts.load_json(ROOT / "tests/fixtures/current-run/complete-run.json")
        self.assertEqual(contracts.validate_instance("run-bundle", bundle), [])

    def test_luna_cannot_declare_done(self):
        schema = self.load("luna-result.schema.json")
        self.assertNotIn("DONE", schema["properties"]["status"]["enum"])

    def test_task_packet_has_one_objective_without_one_question_limit(self):
        schema = self.load("task-packet.schema.json")
        self.assertIn("decision_objective", schema["required"])
        self.assertNotIn("open_question", schema["required"])
        self.assertIn("open_questions", schema["properties"])

    def test_request_evidence_and_blocked_plans_cannot_fabricate_steps_or_criteria(self):
        plan = {
            "run_id": "run-1",
            "plan_id": "plan-1",
            "agent_id": "astra-1",
            "intent": "change",
            "decision": "REQUEST_EVIDENCE",
            "decision_objective": "Determine whether implementation is safe.",
            "root_cause_status": "UNKNOWN",
            "root_cause": "The available packet does not establish a cause.",
            "facts_used": ["The packet is incomplete."],
            "architecture_decisions": [],
            "change_scope": [],
            "implementation_steps": [],
            "constraints": [],
            "acceptance_criteria": [],
            "verification_plan": [],
            "evidence_requests": [{"id": "ER-1", "targets": ["src/module.py"], "reason": "Need the missing trace."}],
            "escalation_condition": "Remain blocked until the trace is supplied.",
        }
        self.assertEqual(contracts.validate_instance("astra-plan", plan), [])
        plan["implementation_steps"] = ["Invent a fix"]
        self.assertTrue(contracts.validate_instance("astra-plan", plan))

    def test_approved_plan_accepts_commands_without_optional_observation_plan(self):
        fixture = contracts.load_json(ROOT / "tests/fixtures/current-run/complete-run.json")
        plan = fixture["plan"]
        self.assertNotIn("observation_plan", plan)
        self.assertEqual(contracts.validate_instance("astra-plan", plan), [])

    def test_done_schema_rejects_empty_criteria_evidence_and_unresolved_fields(self):
        fixture = contracts.load_json(ROOT / "tests/fixtures/current-run/complete-run.json")
        verification = fixture["verification"]
        for mutation in (
            {"criteria": []},
            {"criteria": [{"id": "AC-1", "status": "FAIL", "evidence": "failed"}]},
            {"criteria": [{"id": "AC-1", "status": "PASS", "evidence": "   "}]},
            {"remaining_problem": "still open"},
            {"next_open_question": "still open"},
            {"next_scope": ["module.py"]},
            {"evidence_requests": [{"id": "ER-1", "targets": ["module.py"], "reason": "need more"}]},
        ):
            candidate = copy.deepcopy(verification)
            candidate.update(mutation)
            self.assertTrue(contracts.validate_instance("sol-verification", candidate), mutation)

    def test_sol_is_the_only_completion_authority(self):
        fixture = contracts.load_json(ROOT / "tests/fixtures/current-run/complete-run.json")
        verification = fixture["verification"]
        self.assertEqual(verification["authority"], "SOL")
        self.assertNotIn("DONE", contracts.load_json(ROOT / "schemas/astra-plan.schema.json").get("properties", {}).get("decision", {}).get("enum", []))
        candidate = copy.deepcopy(verification)
        candidate["authority"] = "ASTRA"
        self.assertTrue(contracts.validate_instance("sol-verification", candidate))


if __name__ == "__main__":
    unittest.main()
