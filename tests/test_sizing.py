"""Grid size estimation and clamping."""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from legolizer import providers
from legolizer.catalog import MAX_STUDS, MIN_STUDS, SIZE_STEP


class SizeEstimateTests(unittest.TestCase):
    def test_parse_max_size_accepts_only_the_slider_steps(self):
        self.assertEqual(providers.parse_max_size(MIN_STUDS), MIN_STUDS)
        self.assertEqual(providers.parse_max_size(28), 28)
        self.assertEqual(providers.parse_max_size(MAX_STUDS), MAX_STUDS)
        for bad in (12, 18, 30, 36, 24.0, True, "24", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                providers.parse_max_size(bad)

    def test_snap_size_rounds_to_the_nearest_step_inside_the_range(self):
        cases = [(3, 16), (17.9, 16), (18.1, 20), (25.9, 24), (26.1, 28), (31, 32), (90, 32)]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(providers.snap_size(raw), expected)

    def test_estimate_size_uses_the_fast_model_schema_and_snaps(self):
        asked = []

        def fake_ask(content, schema=None, name="shape_program", fast=False):
            asked.append((content, schema, name, fast))
            return {"size": 23, "reason": "a city block"}

        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True),
            mock.patch.object(providers, "_ask_json", fake_ask),
        ):
            result = providers.estimate_size("a sprawling castle")
        self.assertEqual(result, {"size": 24, "reason": "a city block"})
        content, schema, name, fast = asked[0]
        self.assertEqual(name, "size_estimate")
        self.assertIs(schema, providers.SIZE_SCHEMA)
        self.assertTrue(fast)
        self.assertTrue(any("castle" in str(part) for part in content))

    def test_estimate_size_falls_back_without_a_number(self):
        with mock.patch.object(
            providers, "_ask_json", lambda *a, **k: {"size": "big", "reason": ""}
        ):
            result = providers.estimate_size("a boat")
        self.assertEqual(result["size"], MIN_STUDS + 2 * SIZE_STEP)
        self.assertIn(str(result["size"]), result["reason"])

    def test_estimate_size_sends_the_reference_image(self):
        asked = []
        image = providers.Path("ref.png")

        def fake_ask(content, **kwargs):
            asked.append(content)
            return {"size": 32, "reason": "tall"}

        with mock.patch.object(providers, "_ask_json", fake_ask):
            result = providers.estimate_size("", image)
        self.assertEqual(result["size"], 32)
        self.assertIs(asked[0][-1], image)
        self.assertIn("the main subject of the reference image", asked[0][1])

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
            providers.design_program("a tiny frog", None, 20)
        joined = "\n".join(map(str, asked[0]))
        self.assertIn("about 20 studs", joined)
        self.assertIn("tiny frog", joined)

    def test_size_range_is_sixteen_to_thirty_two_in_fours(self):
        self.assertEqual((MIN_STUDS, MAX_STUDS, SIZE_STEP), (16, 32, 4))


def _chat(content):
    client = mock.MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=content, refusal=None)
            )
        ]
    )
    return client


class FastModelTests(unittest.TestCase):
    answer = '{"size": 24, "reason": "fits"}'

    def estimate_with(self, env):
        client = _chat(self.answer)
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch("openai.OpenAI", return_value=client),
        ):
            providers.estimate_size("a mug")
        return client.chat.completions.create.call_args.kwargs["model"]

    def test_size_estimate_uses_each_providers_small_model(self):
        self.assertEqual(self.estimate_with({"OPENAI_API_KEY": "o"}), "gpt-5-mini")
        self.assertEqual(self.estimate_with({"GROK_API_KEY": "g"}), "grok-4.20-0309-non-reasoning")
        self.assertEqual(
            self.estimate_with({"OPENAI_API_KEY": "o", "OPENAI_FAST_MODEL": "gpt-5-nano"}),
            "gpt-5-nano",
        )

    def test_fast_calls_prefer_grok_when_its_key_is_set(self):
        both = {"OPENAI_API_KEY": "o", "GROK_API_KEY": "g"}
        self.assertEqual(self.estimate_with(both), "grok-4.20-0309-non-reasoning")
        self.assertEqual(
            self.estimate_with({**both, "SCENE_PROVIDER": "openai"}),
            "grok-4.20-0309-non-reasoning",
        )
        self.assertEqual(self.estimate_with({**both, "FAST_PROVIDER": "openai"}), "gpt-5-mini")
        self.assertEqual(
            self.estimate_with({**both, "GROK_FAST_MODEL": "grok-4-1-fast-non-reasoning"}),
            "grok-4-1-fast-non-reasoning",
        )

    def test_unknown_fast_provider_is_rejected(self):
        with mock.patch.dict(os.environ, {"FAST_PROVIDER": "gemini"}, clear=True):
            with self.assertRaisesRegex(ValueError, "FAST_PROVIDER"):
                providers.estimate_size("a mug")

    def test_design_keeps_the_full_scene_model(self):
        client = _chat('{"assessment": "", "satisfied": false, "program": {}}')
        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True),
            mock.patch("openai.OpenAI", return_value=client),
        ):
            providers.design_program("a mug", None, 16)
        self.assertEqual(client.chat.completions.create.call_args.kwargs["model"], "gpt-6-sol")

    def test_claude_size_estimate_uses_haiku(self):
        message = SimpleNamespace(
            stop_reason="tool_use",
            content=[SimpleNamespace(type="tool_use", input={"size": 20, "reason": "fits"})],
        )
        client = mock.MagicMock()
        client.messages.create.return_value = message
        with (
            mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "a"}, clear=True),
            mock.patch("anthropic.Anthropic", return_value=client),
        ):
            self.assertEqual(providers.estimate_size("a mug")["size"], 20)
        self.assertEqual(client.messages.create.call_args.kwargs["model"], "claude-haiku-4-5")


if __name__ == "__main__":
    unittest.main()
