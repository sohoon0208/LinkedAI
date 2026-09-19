import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import contracts


class RoutingPolicyTests(unittest.TestCase):
    def fast_decision(self, **eligibility):
        return {
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
                **eligibility,
            },
        }

    def test_intent_vocabulary_is_explicit(self):
        self.assertEqual(contracts.INTENTS, {"change", "investigate", "review", "explain"})

    def test_fast_requires_explicit_strict_eligibility(self):
        result = contracts.select_dispatch_mode(self.fast_decision())
        self.assertEqual(result["dispatch_mode"], "FAST")
        self.assertEqual(result["proposed_mode"], "FAST")
        self.assertTrue(result["input_valid"])
        self.assertEqual(result["workflow_variant"], contracts.ASTRA_HIGH_LUNA_SOL_VARIANT)
        self.assertEqual(result["workflow_stages"], list(contracts.ASTRA_HIGH_LUNA_SOL_WORKFLOW_STAGES))
        self.assertEqual(result["verification_profile"], "BALANCED")
        self.assertEqual(result["approval_policy"], "AUTO")
        self.assertFalse(result["approval_required"])

    def test_standard_and_deep_use_the_same_astra_high_pipeline_without_pause(self):
        standard = self.fast_decision()
        standard["tier"] = 1
        result = contracts.select_dispatch_mode(standard)
        self.assertEqual(result["workflow_variant"], contracts.ASTRA_HIGH_LUNA_SOL_VARIANT)
        self.assertEqual(result["workflow_stages"], list(contracts.ASTRA_HIGH_LUNA_SOL_WORKFLOW_STAGES))
        self.assertEqual(result["verification_profile"], "BALANCED")
        self.assertEqual(result["approval_policy"], "AUTO")
        self.assertFalse(result["approval_required"])
        self.assertIsNone(result["post_approval_variant"])
        self.assertEqual(result["post_approval_stages"], [])

        deep = self.fast_decision()
        deep["tier"] = 3
        result = contracts.select_dispatch_mode(deep)
        self.assertEqual(result["workflow_variant"], contracts.ASTRA_HIGH_LUNA_SOL_VARIANT)
        self.assertEqual(result["workflow_stages"], list(contracts.ASTRA_HIGH_LUNA_SOL_WORKFLOW_STAGES))
        self.assertEqual(result["verification_profile"], "FULL")
        self.assertEqual(result["approval_policy"], "AUTO")
        self.assertFalse(result["approval_required"])

    def test_explicit_approval_does_not_reintroduce_a_gate(self):
        decision = self.fast_decision()
        decision["approval_policy"] = "REQUIRED"
        result = contracts.select_dispatch_mode(decision)
        self.assertEqual(result["dispatch_mode"], "FAST")
        self.assertEqual(result["workflow_variant"], contracts.ASTRA_HIGH_LUNA_SOL_VARIANT)
        self.assertEqual(result["verification_profile"], "BALANCED")
        self.assertEqual(result["approval_policy"], "AUTO")
        self.assertFalse(result["approval_required"])

    def test_fast_is_reserved_for_source_mutating_changes(self):
        decision = self.fast_decision()
        decision["intent"] = "review"
        decision["changed_paths"] = []
        decision["source_mutation"] = False
        result = contracts.select_dispatch_mode(decision)
        self.assertEqual(result["dispatch_mode"], "STANDARD")
        self.assertEqual(result["workflow_variant"], contracts.ASTRA_HIGH_LUNA_SOL_VARIANT)
        self.assertEqual(result["verification_profile"], "BALANCED")

    def test_missing_or_malformed_fast_inputs_fall_back_to_standard(self):
        missing = self.fast_decision()
        del missing["eligibility"]["known_dependencies"]
        result = contracts.select_dispatch_mode(missing)
        self.assertEqual(result["dispatch_mode"], "STANDARD")
        self.assertFalse(result["input_valid"])
        malformed = self.fast_decision(direct_verification="yes")
        malformed_result = contracts.select_dispatch_mode(malformed)
        self.assertEqual(malformed_result["dispatch_mode"], "STANDARD")
        self.assertFalse(malformed_result["input_valid"])

    def test_deep_is_selected_for_tier_three_and_explicit_deep_signals(self):
        tier_three = self.fast_decision()
        tier_three["tier"] = 3
        self.assertEqual(contracts.select_dispatch_mode(tier_three)["dispatch_mode"], "DEEP")
        conflicting = self.fast_decision(conflicting_evidence=True)
        self.assertEqual(contracts.select_dispatch_mode(conflicting)["dispatch_mode"], "DEEP")

    def test_boundary_escalation_and_no_automatic_downgrade(self):
        standard = self.fast_decision()
        standard["tier"] = 1
        escalated = contracts.select_dispatch_mode(standard, current_mode="FAST")
        self.assertEqual(escalated["dispatch_mode"], "STANDARD")
        self.assertTrue(escalated["escalated"])

        deep = self.fast_decision()
        deep["tier"] = 3
        self.assertEqual(
            contracts.select_dispatch_mode(deep, current_mode="STANDARD")["dispatch_mode"],
            "DEEP",
        )
        retained = contracts.select_dispatch_mode(self.fast_decision(), current_mode="DEEP")
        self.assertEqual(retained["dispatch_mode"], "DEEP")
        self.assertFalse(retained["escalated"])
        self.assertIn("no automatic in-run downgrade", retained["dispatch_reason"])

    def test_routing_schema_keeps_mode_metadata_optional_but_paired(self):
        legacy = self.fast_decision()
        legacy.pop("eligibility")
        self.assertEqual(contracts.validate_instance("routing-decision", legacy), [])
        current = self.fast_decision()
        current.update({"dispatch_mode": "FAST", "dispatch_reason": "eligible"})
        self.assertEqual(contracts.validate_instance("routing-decision", current), [])
        incomplete = self.fast_decision()
        incomplete["dispatch_mode"] = "FAST"
        self.assertTrue(contracts.validate_instance("routing-decision", incomplete))

    def test_state_mapping_is_complete_for_runtime_outcomes(self):
        expected = {
            "RETRY": "LUNA_EXECUTION",
            "REPLAN": "ASTRA_PLAN",
            "EVIDENCE": "LUNA_EVIDENCE",
            "DONE": "STOP",
            "BLOCKED": "STOP_BLOCKED",
        }
        for state, stage in expected.items():
            self.assertEqual(
                contracts.next_stage({"authority": "SOL", "state": state}, intent="change")["next_stage"],
                stage,
            )

    def test_non_change_rejects_mutation(self):
        with self.assertRaises(contracts.ContractError):
            contracts.next_stage(
                {"state": "RETRY", "result": {"changed_paths": ["src/file.py"]}},
                intent="review",
            )

    def test_cap_allows_terminal_done_but_blocks_unresolved_outcomes(self):
        done = contracts.next_stage({"authority": "SOL", "state": "DONE"}, intent="change", handoff_count=5)
        self.assertEqual(done["next_stage"], "STOP")
        retry = contracts.next_stage({"authority": "SOL", "state": "RETRY"}, intent="change", handoff_count=5)
        self.assertEqual(retry["next_stage"], "STOP_BLOCKED")

    def test_legacy_astra_adjudication_cannot_authorize_done(self):
        result = contracts.next_stage(
            {"adjudication": {"state": "DONE"}}, intent="change", handoff_count=0
        )
        self.assertEqual(result["next_stage"], "STOP_BLOCKED")
        self.assertFalse(result["allowed"])
        self.assertTrue(result["legacy_artifact"])


if __name__ == "__main__":
    unittest.main()
