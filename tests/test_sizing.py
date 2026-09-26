"""Grid size estimation and clamping."""

import os
import unittest
from unittest import mock

from legolizer import providers
from legolizer.catalog import MAX_STUDS, MIN_STUDS


class SizeEstimateTests(unittest.TestCase):
    def test_parse_max_size_clamps_and_rejects_bad_values(self):
        self.assertEqual(providers.parse_max_size(12), 12)
        self.assertEqual(providers.parse_max_size(MIN_STUDS), MIN_STUDS)
        self.assertEqual(providers.parse_max_size(MAX_STUDS), MAX_STUDS)
        for bad in (5, 33, 12.5, True, "12", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                providers.parse_max_size(bad)

    def test_estimate_size_uses_the_schema_and_clamps(self):
        asked = []

        def fake_ask(content, schema=None, name="shape_program"):
            asked.append((content, schema, name))
            return {"size": 40, "reason": "a city block"}

        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True),
            mock.patch.object(providers, "_ask_json", fake_ask),
        ):
            result = providers.estimate_size("a sprawling castle")
        self.assertEqual(result, {"size": MAX_STUDS, "reason": "a city block"})
        self.assertEqual(asked[0][2], "size_estimate")
        self.assertIs(asked[0][1], providers.SIZE_SCHEMA)
        self.assertTrue(any("castle" in str(part) for part in asked[0][0]))

    def test_design_program_includes_the_target_size(self):
        asked = []
        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True),
            mock.patch.object(
                providers,
                "_ask_json",
                lambda content, schema=None, name="shape_program": (
                    asked.append(content) or {"assessment": "", "satisfied": False, "program": {}}
                ),
            ),
        ):
            providers.design_program("a tiny frog", None, 8)
        joined = "\n".join(map(str, asked[0]))
        self.assertIn("about 8 studs", joined)
        self.assertIn("tiny frog", joined)

    def test_hard_cap_rose_to_thirty_two(self):
        self.assertEqual((MIN_STUDS, MAX_STUDS), (6, 32))


if __name__ == "__main__":
    unittest.main()
