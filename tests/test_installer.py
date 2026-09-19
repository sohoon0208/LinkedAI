from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import shutil
import site
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("linkedai_install_test", INSTALLER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load installer module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InstallerTests(unittest.TestCase):
    def copy_source(self, directory: Path, name: str = "source") -> Path:
        source = directory / name
        shutil.copytree(
            ROOT,
            source,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.profraw"),
        )
        return source

    def safe_environment(self, directory: Path) -> dict[str, str]:
        environment = os.environ.copy()
        environment["HOME"] = str(directory / "home")
        environment["CODEX_HOME"] = str(directory / "codex")
        # Keep the fixture isolated from real HOME/CODEX_HOME destinations
        # without hiding the dependencies already available to this test
        # interpreter. The installer itself never downloads packages.
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
        return environment

    def run_install(
        self,
        source: Path,
        target: Path,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = environment or self.safe_environment(source.parent)
        return subprocess.run(
            [str(source / "scripts" / "install.sh"), "--target", str(target)],
            cwd=str(source),
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )

    def run_helper_install(
        self,
        source: Path,
        target: Path,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(source / "scripts" / "linkedai"), "install", "--target", str(target)],
            cwd=str(source),
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fresh_install_copies_explicit_runtime_package(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            target = temp / "fresh" / "linkedai"

            result = self.run_install(source, target)

            self.assert_success(result)
            for relative in (
                "SKILL.md",
                "requirements.txt",
                "references/runtime-contracts.md",
                "references/usage-and-evaluation.md",
                "scripts/contracts.py",
                "scripts/usage.py",
            ):
                with self.subTest(relative=relative):
                    self.assertTrue((target / relative).is_file())
            self.assertFalse((target / "archive").exists())
            self.assertFalse((target / "default.profraw").exists())
            self.assertFalse((target / "echo-mode").exists())
            self.assertFalse((target / "scripts" / "linkedai-broker.py").exists())
            self.assertFalse((target / "prompts" / "ag-preplanner.md").exists())
            self.assertFalse((target / "tests" / "test_broker.py").exists())
            self.assertIn("backup preserved: none", result.stdout)

    def test_update_preserves_unrelated_data_and_prints_recoverable_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            target = temp / "codex" / "skills" / "linkedai"
            self.assert_success(self.run_install(source, target))

            old_skill = (target / "SKILL.md").read_text(encoding="utf-8")
            (target / "keep-me.txt").write_text("unrelated\n", encoding="utf-8")
            (target / "archive").mkdir()
            (target / "archive" / "old-ag.txt").write_text("recover\n", encoding="utf-8")
            (target / "caches").mkdir()
            (target / "caches" / "old.cache").write_text("recover\n", encoding="utf-8")
            (target / "scripts" / "linkedai-broker.py").write_text("old ag\n", encoding="utf-8")
            (target / "prompts" / "ag-preplanner.md").write_text("old ag\n", encoding="utf-8")
            (target / "schemas" / "ag-preplan-old.schema.json").write_text("{}\n", encoding="utf-8")
            (target / "echo-mode").mkdir()
            (target / "echo-mode" / "SKILL.md").write_text("duplicate\n", encoding="utf-8")
            (source / "SKILL.md").write_text(old_skill + "\nupdated\n", encoding="utf-8")

            result = self.run_install(source, target)

            self.assert_success(result)
            match = re.search(r"^backup preserved: (.+)$", result.stdout, re.MULTILINE)
            self.assertIsNotNone(match, result.stdout)
            backup = Path(match.group(1).strip())
            self.assertTrue(backup.is_dir())
            self.assertEqual(backup.parent.name, "skill-backups")
            self.assertEqual(backup.parent.parent, target.parent.parent.resolve())
            self.assertEqual((backup / "SKILL.md").read_text(encoding="utf-8"), old_skill)
            self.assertTrue((backup / "keep-me.txt").is_file())
            self.assertTrue((backup / "archive" / "old-ag.txt").is_file())
            self.assertTrue((backup / "caches" / "old.cache").is_file())
            self.assertTrue((backup / "echo-mode" / "SKILL.md").is_file())
            self.assertEqual((target / "keep-me.txt").read_text(encoding="utf-8"), "unrelated\n")
            self.assertIn("updated", (target / "SKILL.md").read_text(encoding="utf-8"))
            for relative in (
                "archive",
                "caches",
                "echo-mode",
                "scripts/linkedai-broker.py",
                "prompts/ag-preplanner.md",
                "schemas/ag-preplan-old.schema.json",
            ):
                with self.subTest(relative=relative):
                    self.assertFalse((target / relative).exists())

            (source / "SKILL.md").write_text(
                (source / "SKILL.md").read_text(encoding="utf-8") + "\nsecond update\n",
                encoding="utf-8",
            )
            second_result = self.run_install(source, target)
            self.assert_success(second_result)
            second_match = re.search(
                r"^backup preserved: (.+)$", second_result.stdout, re.MULTILINE
            )
            self.assertIsNotNone(second_match, second_result.stdout)
            second_backup = Path(second_match.group(1).strip())
            self.assertNotEqual(second_backup, backup)
            self.assertTrue(backup.is_dir())
            self.assertTrue(second_backup.is_dir())

    def test_same_source_target_is_a_validated_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            marker = source / "user-data.txt"
            marker.write_text("keep\n", encoding="utf-8")

            result = self.run_install(source, source)

            self.assert_success(result)
            self.assertIn("no-op", result.stdout)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")
            self.assertFalse((temp / "skill-backups").exists())
            self.assertEqual(list(temp.glob(".linkedai.stage-*")), [])

    def test_symlink_alias_to_source_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            alias = temp / "source-alias"
            alias.symlink_to(source, target_is_directory=True)

            result = self.run_install(source, alias)

            self.assert_success(result)
            self.assertIn("no-op", result.stdout)
            self.assertTrue(alias.is_symlink())

    def test_installed_helper_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            target = temp / "installed" / "linkedai"
            self.assert_success(self.run_install(source, target))
            marker = target / "user-data.txt"
            marker.write_text("preserve\n", encoding="utf-8")

            environment = self.safe_environment(temp)
            result = self.run_helper_install(target, target, environment)

            self.assert_success(result)
            self.assertIn("no-op", result.stdout)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")
            self.assertFalse((Path(environment["CODEX_HOME"]) / "skills" / "linkedai").exists())

    def test_source_script_symlink_alias_uses_physical_source(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            source_alias = temp / "source-alias"
            source_alias.symlink_to(source, target_is_directory=True)
            target = temp / "alias-install" / "linkedai"

            result = subprocess.run(
                [str(source_alias / "scripts" / "install.sh"), "--target", str(target)],
                cwd=str(source_alias),
                capture_output=True,
                text=True,
                check=False,
                env=self.safe_environment(temp),
            )

            self.assert_success(result)
            self.assertTrue((target / "SKILL.md").is_file())

    def test_rejects_broad_ancestor_and_symlink_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            broad = temp / "not-a-linkedai-target"
            result = self.run_install(source, broad)
            self.assertNotEqual(result.returncode, 0)

            container = temp / "container"
            container.mkdir()
            nested_root = container / "linkedai"
            nested_source = self.copy_source(container, "linkedai-package")
            # Move the fixture below a directory named linkedai so that the
            # requested target is an ancestor of source while still satisfying
            # the target suffix rule.
            nested_root.mkdir(parents=True)
            moved_source = nested_root / "package"
            shutil.move(str(nested_source), str(moved_source))
            result = self.run_install(moved_source, nested_root)
            self.assertNotEqual(result.returncode, 0)

            real_target = temp / "real-target"
            real_target.mkdir()
            symlink_target = temp / "linkedai"
            symlink_target.symlink_to(real_target, target_is_directory=True)
            result = self.run_install(source, symlink_target)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(real_target.iterdir()), [])

    def test_source_validation_failure_preserves_current_target(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            target = temp / "validation" / "linkedai"
            target.mkdir(parents=True)
            marker = target / "current.txt"
            marker.write_text("current\n", encoding="utf-8")
            (source / "SKILL.md").unlink()

            result = self.run_install(source, target)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(encoding="utf-8"), "current\n")
            self.assertFalse((target.parent / "skill-backups").exists())

    def test_source_symlink_escape_is_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            target = temp / "symlink-validation" / "linkedai"
            target.mkdir(parents=True)
            marker = target / "current.txt"
            marker.write_text("current\n", encoding="utf-8")
            outside = temp / "outside-secret.txt"
            outside.write_text("secret\n", encoding="utf-8")
            (source / "scripts" / "escape.txt").symlink_to(outside)

            result = self.run_install(source, target)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("escapes", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "current\n")
            self.assertFalse((target.parent / "skill-backups").exists())

    def test_stage_validation_failure_preserves_current_target(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            target = temp / "stage-validation" / "linkedai"
            target.mkdir(parents=True)
            marker = target / "current.txt"
            marker.write_text("current\n", encoding="utf-8")
            (source / "scripts" / "validate.py").write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "if Path(__file__).resolve().parents[1].name.startswith('.linkedai.stage-'):\n"
                "    print('intentional stage validation failure')\n"
                "    raise SystemExit(9)\n",
                encoding="utf-8",
            )

            result = self.run_install(source, target)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("package validation failed", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "current\n")
            self.assertFalse((target.parent / "skill-backups").exists())
            self.assertEqual(list(target.parent.glob(".linkedai.stage-*")), [])

    def test_rename_failure_rolls_back_without_losing_current_target(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            target = temp / "rollback" / "linkedai"
            self.assert_success(self.run_install(source, target))
            old_skill = (target / "SKILL.md").read_text(encoding="utf-8")
            (source / "SKILL.md").write_text(old_skill + "\nnew\n", encoding="utf-8")
            installer = load_installer()
            real_rename = installer.os.rename
            canonical_target = target.resolve()

            def fail_activation(src, dst):
                if Path(src).name.startswith(".linkedai.stage-") and Path(dst) == canonical_target:
                    raise OSError("simulated activation rename failure")
                return real_rename(src, dst)

            with mock.patch.object(installer.os, "rename", side_effect=fail_activation):
                with self.assertRaises(installer.InstallError):
                    installer.install(source=source, target=target)

            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), old_skill)
            self.assertFalse((target.parent / "skill-backups").exists())
            self.assertEqual(list(target.parent.glob(".linkedai.stage-*")), [])

    def test_excluded_source_runtime_data_and_unknown_files_are_not_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = self.copy_source(temp)
            target = temp / "excluded" / "linkedai"
            (source / "unrelated.txt").write_text("not package\n", encoding="utf-8")
            for name in ("caches", "profiles", "environments", "session", "log", "output"):
                path = source / "scripts" / name
                path.mkdir()
                (path / "secret.txt").write_text("secret\n", encoding="utf-8")
            (source / ".git").mkdir()
            (source / ".git" / "secret").write_text("secret\n", encoding="utf-8")

            result = self.run_install(source, target)

            self.assert_success(result)
            self.assertFalse((target / "unrelated.txt").exists())
            self.assertFalse((target / ".git").exists())
            self.assertFalse((target / "archive").exists())
            for name in ("caches", "profiles", "environments", "session", "log", "output"):
                with self.subTest(name=name):
                    self.assertFalse((target / "scripts" / name).exists())


if __name__ == "__main__":
    unittest.main()
