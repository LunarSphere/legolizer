"""Prompt stylizer: one fast call that adds detail, a palette and a size to short prompts."""

import os
import unittest
from unittest import mock

from legolizer import providers


class StylizePromptTests(unittest.TestCase):
    def ask(self, response):
        asked = []

        def fake_ask(content, **kwargs):
            asked.append((content, kwargs))
            return response

        with mock.patch.object(providers, "_ask_json", fake_ask):
            result = providers.stylize_prompt("human")
        return result, asked[0]

    def test_uses_the_fast_model_with_its_own_prompt_and_schema(self):
        result, (content, kwargs) = self.ask(
            {
                "brief": "A cheerful hiker waving, red jacket, blue jeans, brown boots.",
                "palette": [4, 1, 70],
                "size": 21,
                "reason": "A figure reads at 20 studs.",
            }
        )
        self.assertEqual(content, ["Request: human"])
        self.assertIs(kwargs["schema"], providers.BRIEF_SCHEMA)
        self.assertTrue(kwargs["fast"])
        self.assertIs(kwargs["system"], providers.STYLIZE_SYSTEM_PROMPT)
        self.assertEqual(result["palette"], [4, 1, 70])
        self.assertEqual(result["size"], 20)
        self.assertEqual(
            result["expanded"],
            "A cheerful hiker waving, red jacket, blue jeans, brown boots. "
            "Palette, most used first: red, blue, reddish brown.",
        )

    def test_bad_answers_fall_back_to_the_original_prompt(self):
        result, _ = self.ask({"brief": "  ", "palette": [4, 4, 999], "size": None, "reason": ""})
        self.assertEqual(result["brief"], "human")
        self.assertEqual(result["palette"], [4])
        self.assertEqual(result["size"], 24)
        self.assertIn("24", result["reason"])
        result, _ = self.ask({"brief": "A robot.", "palette": [], "size": 40, "reason": "big"})
        self.assertEqual((result["expanded"], result["size"]), ("A robot.", 32))

    def test_schema_limits_the_palette_to_design_colors(self):
        items = providers.BRIEF_SCHEMA["properties"]["palette"]["items"]
        self.assertEqual(items["enum"], list(providers.DESIGN_COLORS))
        for phrase in (
            "defaulting to grey",
            "rather than scattering",
            f"steps of {providers.SIZE_STEP}",
        ):
            self.assertIn(phrase, " ".join(providers.STYLIZE_SYSTEM_PROMPT.split()))

    def test_system_prompt_reaches_the_openai_request(self):
        client = mock.MagicMock()
        client.chat.completions.create.return_value = mock.MagicMock(
            choices=[
                mock.MagicMock(
                    finish_reason="stop",
                    message=mock.MagicMock(
                        content='{"brief": "b", "palette": [], "size": 16, "reason": "r"}',
                        refusal=None,
                    ),
                )
            ]
        )
        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True),
            mock.patch("openai.OpenAI", return_value=client),
        ):
            providers.stylize_prompt("a cat")
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5-mini")
        self.assertEqual(kwargs["messages"][0]["content"], providers.STYLIZE_SYSTEM_PROMPT)
        self.assertEqual(kwargs["response_format"]["json_schema"]["name"], "design_brief")

    def test_design_prompt_asks_for_a_deliberate_palette(self):
        prompt = " ".join(providers.DESIGN_SYSTEM_PROMPT.split())
        self.assertIn("instead of defaulting to grey", prompt)
        self.assertIn("never scatter isolated accent bricks", prompt)


if __name__ == "__main__":
    unittest.main()
