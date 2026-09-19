import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ag_evidence


class AGEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "module.py").write_text("before\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def stream(self, response="verified"):
        return "\n".join(
            [
                json.dumps(
                    {"event": "init", "init": {"model": "gemini-3.8-flash-high"}}
                ),
                json.dumps(
                    {"event": "result", "status": "SUCCESS", "response": response}
                ),
            ]
        )

    def validate(
        self,
        before,
        after,
        stdout=None,
        stderr="",
        returncode=0,
        allowed=None,
        isolation_proven=False,
    ):
        return ag_evidence.validate_ag_evidence(
            self.root,
            allowed or [],
            before,
            after,
            returncode,
            self.stream() if stdout is None else stdout,
            stderr,
            isolation_proven=isolation_proven,
        )

    def test_valid_stream_and_declared_modification_pass(self):
        before = ag_evidence.snapshot_tree(self.root)
        (self.root / "module.py").write_text("after\n", encoding="utf-8")
        after = ag_evidence.snapshot_tree(self.root)
        result = self.validate(
            before, after, allowed=["module.py"], isolation_proven=True
        )
        self.assertEqual(result["status"], "AG_PASS", result)
        self.assertEqual(result["changed_paths"], ["module.py"])
        self.assertEqual(result["result"]["model"], "gemini-3.8-flash-high")

    def test_empty_success_is_unavailable(self):
        before = ag_evidence.snapshot_tree(self.root)
        result = self.validate(
            before,
            before,
            stdout=json.dumps({"status": "SUCCESS", "response": ""}),
        )
        self.assertEqual(result["status"], "AG_UNAVAILABLE", result)
        self.assertTrue(any("empty response" in error for error in result["errors"]))

    def test_unproven_isolation_cannot_pass(self):
        before = ag_evidence.snapshot_tree(self.root)
        result = self.validate(before, before)
        self.assertEqual(result["status"], "AG_UNAVAILABLE", result)
        self.assertTrue(any("isolation" in error for error in result["errors"]))

    def test_denied_actions_override_success(self):
        before = ag_evidence.snapshot_tree(self.root)
        stdout = json.dumps(
            {
                "event": "result",
                "status": "SUCCESS",
                "response": "done",
                "denied_actions": [{"action": "read_file"}],
            }
        )
        result = self.validate(before, before, stdout=stdout)
        self.assertEqual(result["status"], "AG_UNAVAILABLE", result)
        self.assertTrue(any("denied_actions" in error for error in result["errors"]))

    def test_malformed_output_and_nonzero_exit_fail_closed(self):
        before = ag_evidence.snapshot_tree(self.root)
        result = self.validate(
            before,
            before,
            stdout="not-json",
            stderr="permission denied",
            returncode=124,
        )
        self.assertEqual(result["status"], "AG_UNAVAILABLE", result)
        self.assertGreaterEqual(len(result["errors"]), 2)

    def test_undeclared_changes_are_rejected(self):
        before = ag_evidence.snapshot_tree(self.root)
        (self.root / "other.txt").write_text("unexpected\n", encoding="utf-8")
        after = ag_evidence.snapshot_tree(self.root)
        result = self.validate(
            before, after, allowed=["module.py"], isolation_proven=True
        )
        self.assertEqual(result["status"], "AG_FAILED", result)
        self.assertTrue(any("undeclared" in error for error in result["errors"]))

    def test_unsafe_paths_and_symlink_escape_are_rejected(self):
        for raw in ("../outside", "/tmp/outside", "C:\\outside"):
            with self.subTest(raw=raw):
                with self.assertRaises(ag_evidence.EvidenceError):
                    ag_evidence.safe_relative_path(self.root, raw)

        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        link = self.root / "escape"
        link.symlink_to(outside, target_is_directory=True)
        snapshot = ag_evidence.snapshot_tree(self.root)
        self.assertTrue(snapshot["escape"]["outside_root"])
        result = self.validate(
            snapshot,
            snapshot,
            allowed=["escape/file.txt"],
            isolation_proven=True,
        )
        self.assertEqual(result["status"], "AG_FAILED", result)
        self.assertTrue(
            any("outside project root" in error for error in result["errors"])
        )

    def test_cli_validates_captured_evidence_without_invoking_ag(self):
        before = ag_evidence.snapshot_tree(self.root)
        payload = {
            "root": str(self.root),
            "allowed_paths": [],
            "before": before,
            "after": before,
            "returncode": 0,
            "stdout": self.stream(),
            "stderr": "",
            "isolation_proven": True,
        }
        evidence = Path(self.temp.name) / "evidence.json"
        evidence.write_text(json.dumps(payload), encoding="utf-8")
        result = subprocess.run(
            [str(ROOT / "scripts" / "linkedai"), "ag", "evidence", str(evidence)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "AG_PASS")


if __name__ == "__main__":
    unittest.main()
