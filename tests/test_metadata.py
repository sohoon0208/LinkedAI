import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class MetadataTests(unittest.TestCase):
    def test_ui_metadata_is_nested_and_quoted_with_concise_prompt(self):
        path = ROOT / "agents" / "openai.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertEqual(set(raw), {"interface"})
        interface = raw["interface"]
        self.assertEqual(
            set(interface), {"display_name", "short_description", "default_prompt"}
        )
        for key, value in interface.items():
            with self.subTest(key=key):
                self.assertIsInstance(value, str)
                self.assertTrue(value.strip())
        self.assertGreaterEqual(len(interface["short_description"]), 25)
        self.assertLessEqual(len(interface["short_description"]), 64)
        prompt = interface["default_prompt"]
        self.assertIn("$linkedai", prompt)
        self.assertIn("ASTRA", prompt)
        self.assertIn("LUNA", prompt)
        self.assertIn("SOL", prompt)
        self.assertNotIn("invocation_policy", raw)


if __name__ == "__main__":
    unittest.main()
