import json
import os
import site
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import contracts


class RepositoryTests(unittest.TestCase):
    def test_active_json_schemas_parse_and_meta_validate(self):
        for name in contracts.ACTIVE_SCHEMAS:
            with self.subTest(name=name):
                path = contracts.ACTIVE_SCHEMAS[name]
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")).get("type"), "object")
                self.assertEqual(contracts.validate_schema(name), [])

    def test_active_structure_and_checked_in_fixtures_validate(self):
        self.assertEqual(contracts.validate_repository(ROOT), [])

    def test_repository_validation_reads_schemas_from_supplied_root(self):
        with tempfile.TemporaryDirectory() as directory:
            alternate = Path(directory) / "linkedai"
            shutil.copytree(ROOT, alternate, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            schema = alternate / "schemas" / "routing-decision.schema.json"
            schema.write_text("{\"type\": [\"not-a-schema\"]}\n", encoding="utf-8")
            errors = contracts.validate_repository(alternate)
            self.assertTrue(any("routing-decision" in error for error in errors))

    def test_ui_validation_requires_interface_nesting(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            flat = temp / "flat.yaml"
            flat.write_text(
                "display_name: LinkedAI\nshort_description: x\ndefault_prompt: y\n",
                encoding="utf-8",
            )
            self.assertTrue(contracts.validate_ui_metadata(flat))
            wrong = temp / "wrong.yaml"
            wrong.write_text(
                "ui:\n  display_name: LinkedAI\n  short_description: x\n  default_prompt: y\n",
                encoding="utf-8",
            )
            self.assertTrue(contracts.validate_ui_metadata(wrong))
            valid = temp / "valid.yaml"
            valid.write_text(
                "interface:\n  display_name: LinkedAI\n  short_description: x\n  default_prompt: y\n",
                encoding="utf-8",
            )
            self.assertEqual(contracts.validate_ui_metadata(valid), [])

    def test_helper_exposes_contract_commands_and_v8_banner(self):
        result = subprocess.run(
            [str(ROOT / "scripts" / "linkedai"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LinkedAI V8 helper", result.stdout)
        for command in ("check", "check-run", "check-plan", "fingerprint", "dispatch-mode", "next-stage", "usage"):
            with self.subTest(command=command):
                self.assertIn(command, result.stdout)
        self.assertNotIn("ag-preplan", result.stdout)

    def test_helper_forwards_install_target_into_isolated_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            target = temp / "linkedai"
            environment = os.environ.copy()
            environment["HOME"] = str(temp / "home")
            environment["CODEX_HOME"] = str(temp / "codex")
            dependency_paths = [site.getusersitepackages()]
            dependency_paths.extend(
                path for path in sys.path if path and Path(path).is_dir()
            )
            existing_pythonpath = environment.get("PYTHONPATH")
            if existing_pythonpath:
                dependency_paths.insert(0, existing_pythonpath)
            environment["PYTHONPATH"] = os.pathsep.join(
                dict.fromkeys(str(path) for path in dependency_paths)
            )
            result = subprocess.run(
                [str(ROOT / "scripts" / "linkedai"), "install", "--target", str(target)],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target.is_dir())
            self.assertIn(str(target), result.stdout)
            self.assertFalse((temp / "codex" / "skills" / "linkedai").exists())


if __name__ == "__main__":
    unittest.main()
