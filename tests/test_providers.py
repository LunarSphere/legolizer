"""Concept image and design provider selection and request shapes, with the SDK mocked."""

import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from legolizer import providers
from legolizer.catalog import DESIGN_COLORS, PARTS, SPECIAL_PARTS
from legolizer.shape import voxelize_program


def _image_b64(fmt):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buffer, format=fmt)
    return base64.b64encode(buffer.getvalue()).decode()


def _client(fmt="PNG"):
    client = mock.MagicMock()
    client.images.generate.return_value = SimpleNamespace(
        data=[SimpleNamespace(b64_json=_image_b64(fmt))]
    )
    return client


class ImageProviderTests(unittest.TestCase):
    def test_invalid_design_review_includes_the_program_and_validator_error(self):
        program = {"parts": [], "pieces": [{"part": "6141"}]}
        with mock.patch.object(providers, "_ask_json", return_value={"program": program}) as ask:
            result = providers.revise_invalid_program(
                "truck", program, "pieces[4] overlaps", Path("concept.png")
            )
        self.assertEqual(result, {"program": program})
        content = ask.call_args.args[0]
        self.assertIn(Path("concept.png"), content)
        self.assertTrue(
            any(isinstance(item, str) and "pieces[4] overlaps" in item for item in content)
        )
        self.assertTrue(any(isinstance(item, str) and '"part": "6141"' in item for item in content))

    def test_design_prompt_covers_the_official_catalog_and_buildability(self):
        for part in PARTS:
            with self.subTest(part=part.code):
                self.assertIn(part.code, providers.DESIGN_SYSTEM_PROMPT)
        self.assertIn(
            "do not try to force every code into one model", providers.DESIGN_SYSTEM_PROMPT
        )
        self.assertIn("Only these LDraw color codes", providers.DESIGN_SYSTEM_PROMPT)
        self.assertIn("Every piece must overlap vertically", providers.DESIGN_SYSTEM_PROMPT)

    def test_provider_defaults_to_openai_and_rejects_unknown_values(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(providers.image_provider(), "openai")
        with mock.patch.dict(os.environ, {"IMAGE_PROVIDER": " Grok "}, clear=True):
            self.assertEqual(providers.image_provider(), "grok")
        with mock.patch.dict(os.environ, {"IMAGE_PROVIDER": "midjourney"}, clear=True):
            with self.assertRaises(ValueError):
                providers.image_provider()
            self.assertIn("IMAGE_PROVIDER", providers.image_setup_problem())

    def test_setup_problem_checks_the_selected_providers_key(self):
        with mock.patch.dict(os.environ, {"GROK_API_KEY": "g"}, clear=True):
            self.assertIn("OPENAI_API_KEY", providers.image_setup_problem())
        with mock.patch.dict(
            os.environ, {"IMAGE_PROVIDER": "grok", "OPENAI_API_KEY": "o"}, clear=True
        ):
            self.assertIn("GROK_API_KEY", providers.image_setup_problem())
        with mock.patch.dict(
            os.environ, {"IMAGE_PROVIDER": "grok", "GROK_API_KEY": "g"}, clear=True
        ):
            self.assertIsNone(providers.image_setup_problem())
        with mock.patch.dict(
            os.environ, {"IMAGE_PROVIDER": "grok", "XAI_API_KEY": "x"}, clear=True
        ):
            self.assertIsNone(providers.image_setup_problem())

    def test_grok_concept_uses_xai_endpoint_and_saves_png(self):
        client = _client("JPEG")
        env = {"IMAGE_PROVIDER": "grok", "GROK_API_KEY": "grok-key"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch("openai.OpenAI", return_value=client) as cls,
            tempfile.TemporaryDirectory() as directory,
        ):
            output = Path(directory) / "concept.png"
            providers.generate_concept("a red mushroom", output)
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
        cls.assert_called_once_with(api_key="grok-key", base_url="https://api.x.ai/v1")
        kwargs = client.images.generate.call_args.kwargs
        self.assertEqual(kwargs["model"], "grok-imagine-image")
        self.assertEqual(kwargs["response_format"], "b64_json")
        self.assertEqual(kwargs["extra_body"], {"aspect_ratio": "1:1"})
        self.assertNotIn("size", kwargs)
        self.assertIn("a red mushroom", kwargs["prompt"])

    def test_reference_photo_goes_through_each_providers_edit_endpoint(self):
        response = SimpleNamespace(data=[SimpleNamespace(b64_json=_image_b64("PNG"))])
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.jpg"
            Image.new("RGB", (8, 8)).save(reference, format="JPEG")
            output = Path(directory) / "concept.png"

            client = mock.MagicMock()
            client.images.edit.return_value = response
            with (
                mock.patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True),
                mock.patch("openai.OpenAI", return_value=client),
            ):
                providers.generate_concept("the Eiffel Tower", output, reference)
            kwargs = client.images.edit.call_args.kwargs
            self.assertEqual(kwargs["image"].name, str(reference))
            self.assertIn("attached photo shows the real subject", kwargs["prompt"])
            client.images.generate.assert_not_called()

            client = mock.MagicMock()
            client.post.return_value = response
            env = {"IMAGE_PROVIDER": "grok", "GROK_API_KEY": "g"}
            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch("openai.OpenAI", return_value=client),
            ):
                providers.generate_concept("the Eiffel Tower", output, reference)
            path, kwargs = client.post.call_args.args[0], client.post.call_args.kwargs
            self.assertEqual(path, "/images/edits")
            body = kwargs["body"]
            self.assertEqual(body["model"], "grok-imagine-image")
            self.assertEqual(body["image"]["type"], "image_url")
            self.assertTrue(body["image"]["url"].startswith("data:image/jpeg;base64,"))
            self.assertIn("attached photo", body["prompt"])
            client.images.generate.assert_not_called()
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")

    def test_openai_concept_is_unchanged_by_default(self):
        client = _client()
        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True),
            mock.patch("openai.OpenAI", return_value=client) as cls,
            tempfile.TemporaryDirectory() as directory,
        ):
            providers.generate_concept("a red mushroom", Path(directory) / "concept.png")
        cls.assert_called_once_with()
        kwargs = client.images.generate.call_args.kwargs
        self.assertEqual(
            (kwargs["model"], kwargs["size"], kwargs["quality"]),
            ("gpt-image-1", "1024x1024", "medium"),
        )

    def test_missing_key_fails_before_any_request(self):
        with (
            mock.patch.dict(os.environ, {"IMAGE_PROVIDER": "grok"}, clear=True),
            mock.patch("openai.OpenAI") as cls,
            tempfile.TemporaryDirectory() as directory,
        ):
            with self.assertRaisesRegex(RuntimeError, "GROK_API_KEY"):
                providers.generate_concept("a red mushroom", Path(directory) / "concept.png")
        cls.assert_not_called()

    def test_empty_image_response_is_an_error(self):
        client = mock.MagicMock()
        client.images.generate.return_value = SimpleNamespace(data=[])
        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True),
            mock.patch("openai.OpenAI", return_value=client),
            tempfile.TemporaryDirectory() as directory,
        ):
            with self.assertRaisesRegex(RuntimeError, "OpenAI image response"):
                providers.generate_concept("a red mushroom", Path(directory) / "concept.png")


DESIGN = {"assessment": "ok", "satisfied": False, "program": {"name": "x"}}


def _openai_response(finish_reason="stop", refusal=None):
    message = SimpleNamespace(content=json.dumps(DESIGN), refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason, message=message)])


class DesignProviderTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.image = Path(directory.name) / "concept.png"
        self.image.write_bytes(base64.b64decode(_image_b64("PNG")))

    def test_provider_selection(self):
        cases = [
            ({"ANTHROPIC_API_KEY": "a"}, "anthropic"),
            ({"CLAUDE_API_KEY": "a", "OPENAI_API_KEY": "o"}, "anthropic"),
            ({"OPENAI_API_KEY": "o"}, "openai"),
            (
                {"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "o", "SCENE_PROVIDER": "OpenAI"},
                "openai",
            ),
        ]
        for env, expected in cases:
            with self.subTest(env=env), mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(providers._provider(), expected)
        failures = [
            ({}, RuntimeError, "OPENAI_API_KEY, ANTHROPIC_API_KEY or GROK_API_KEY"),
            ({"SCENE_PROVIDER": "anthropic", "OPENAI_API_KEY": "o"}, RuntimeError, "ANTHROPIC"),
            ({"SCENE_PROVIDER": "grok"}, RuntimeError, "GROK_API_KEY"),
            ({"SCENE_PROVIDER": "gemini"}, RuntimeError, "SCENE_PROVIDER"),
        ]
        for env, error, message in failures:
            with self.subTest(env=env), mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(error, message):
                    providers._provider()

    def test_image_parts_are_typed_by_suffix(self):
        mime, data = providers._image_part(self.image)
        self.assertEqual(mime, "image/png")
        self.assertEqual(base64.b64decode(data), self.image.read_bytes())
        with self.assertRaisesRegex(ValueError, "Unsupported image format"):
            providers._image_part(self.image.with_suffix(".bmp"))

    def test_openai_request_shape_and_parsing(self):
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _openai_response()
        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True),
            mock.patch("openai.OpenAI", return_value=client),
        ):
            self.assertEqual(providers._ask_json(["hello", self.image]), DESIGN)
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5")
        self.assertTrue(kwargs["response_format"]["json_schema"]["strict"])
        self.assertIs(kwargs["response_format"]["json_schema"]["schema"], providers.RESPONSE_SCHEMA)
        system, user = kwargs["messages"]
        self.assertEqual(system, {"role": "system", "content": providers.DESIGN_SYSTEM_PROMPT})
        text, image = user["content"]
        self.assertEqual(text, {"type": "text", "text": "hello"})
        self.assertTrue(image["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_openai_truncation_and_refusal_are_errors(self):
        client = mock.MagicMock()
        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True),
            mock.patch("openai.OpenAI", return_value=client),
        ):
            client.chat.completions.create.return_value = _openai_response(finish_reason="length")
            with self.assertRaisesRegex(ValueError, "truncated"):
                providers._ask_json(["hello"])
            client.chat.completions.create.return_value = _openai_response(refusal="no")
            with self.assertRaisesRegex(ValueError, "declined: no"):
                providers._ask_json(["hello"])

    def test_claude_forces_the_design_tool(self):
        client = mock.MagicMock()
        client.messages.create.return_value = SimpleNamespace(
            stop_reason="tool_use",
            content=[
                SimpleNamespace(type="text", text="thinking"),
                SimpleNamespace(type="tool_use", input=DESIGN),
            ],
        )
        with (
            mock.patch.dict(os.environ, {"CLAUDE_API_KEY": "c"}, clear=True),
            mock.patch("anthropic.Anthropic", return_value=client) as cls,
        ):
            self.assertEqual(providers._ask_json(["hello", self.image]), DESIGN)
        cls.assert_called_once_with(api_key="c")
        kwargs = client.messages.create.call_args.kwargs
        self.assertEqual(kwargs["system"], providers.DESIGN_SYSTEM_PROMPT)
        self.assertEqual(kwargs["tool_choice"], {"type": "tool", "name": "submit_design"})
        self.assertIs(kwargs["tools"][0]["input_schema"], providers.RESPONSE_SCHEMA)
        text, image = kwargs["messages"][0]["content"]
        self.assertEqual(text, {"type": "text", "text": "hello"})
        self.assertEqual(image["source"]["media_type"], "image/png")

    def test_claude_truncation_and_missing_tool_call_are_errors(self):
        client = mock.MagicMock()
        with (
            mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "a"}, clear=True),
            mock.patch("anthropic.Anthropic", return_value=client),
        ):
            client.messages.create.return_value = SimpleNamespace(
                stop_reason="max_tokens", content=[]
            )
            with self.assertRaisesRegex(ValueError, "truncated"):
                providers._ask_json(["hello"])
            client.messages.create.return_value = SimpleNamespace(
                stop_reason="end_turn", content=[SimpleNamespace(type="text", text="hi")]
            )
            with self.assertRaisesRegex(ValueError, "did not return a design"):
                providers._ask_json(["hello"])

    def test_design_and_revise_prompts(self):
        asked = []
        with mock.patch.object(providers, "_ask_json", lambda content: asked.append(content)):
            providers.design_program("a robot", None)
            providers.design_program("a robot", self.image)
            providers.revise_program(
                "a robot", {"parts": []}, self.image, None, "UNATTACHED: 1 piece"
            )
            providers.revise_program("a robot", {"parts": []}, self.image, self.image, "ok")
        plain, with_concept, revise, revise_with_concept = asked
        self.assertEqual(plain[0], "Object: a robot")
        self.assertNotIn(self.image, plain)
        self.assertIn(self.image, with_concept)
        self.assertIn('Current shape program:\n{"parts": []}', revise)
        self.assertIn("Build report:\nUNATTACHED: 1 piece", revise)
        self.assertEqual(revise.count(self.image), 1)
        self.assertEqual(revise_with_concept.count(self.image), 2)


def _chat(content='{"assessment": "", "satisfied": false, "program": {}}'):
    client = mock.MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=content, refusal=None)
            )
        ]
    )
    return client


class GrokDesignProviderTests(unittest.TestCase):
    def test_provider_choice_and_fallbacks(self):
        cases = [
            ({}, "openai"),
            ({"OPENAI_API_KEY": "o", "GROK_API_KEY": "g"}, "openai"),
            ({"GROK_API_KEY": "g"}, "grok"),
            ({"CLAUDE_API_KEY": "c", "GROK_API_KEY": "g"}, "anthropic"),
            ({"SCENE_PROVIDER": " Grok ", "OPENAI_API_KEY": "o"}, "grok"),
        ]
        for env, expected in cases:
            with self.subTest(env=env), mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(providers.design_provider(), expected)
        with mock.patch.dict(os.environ, {"SCENE_PROVIDER": "llama"}, clear=True):
            self.assertIn("SCENE_PROVIDER", providers.design_setup_problem())

    def test_setup_problem_names_the_missing_key(self):
        cases = [
            ({}, "OPENAI_API_KEY, ANTHROPIC_API_KEY or GROK_API_KEY"),
            ({"SCENE_PROVIDER": "grok", "OPENAI_API_KEY": "o"}, "GROK_API_KEY"),
            ({"SCENE_PROVIDER": "anthropic"}, "ANTHROPIC_API_KEY"),
        ]
        for env, expected in cases:
            with self.subTest(env=env), mock.patch.dict(os.environ, env, clear=True):
                self.assertIn(expected, providers.design_setup_problem())
                with self.assertRaisesRegex(RuntimeError, expected):
                    providers.design_program("a mushroom", None)
        with mock.patch.dict(
            os.environ, {"SCENE_PROVIDER": "grok", "XAI_API_KEY": "x"}, clear=True
        ):
            self.assertIsNone(providers.design_setup_problem())

    def test_grok_design_uses_xai_with_the_strict_schema(self):
        client = _chat()
        with (
            mock.patch.dict(os.environ, {"GROK_API_KEY": "grok-key"}, clear=True),
            mock.patch("openai.OpenAI", return_value=client) as cls,
            tempfile.TemporaryDirectory() as directory,
        ):
            reference = Path(directory) / "source.webp"
            Image.new("RGB", (4, 4), (0, 90, 200)).save(reference, format="WEBP")
            result = providers.design_program("a blue car", reference)
        self.assertEqual(result["assessment"], "")
        cls.assert_called_once_with(api_key="grok-key", base_url="https://api.x.ai/v1")
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "grok-4.20-0309-reasoning")
        self.assertTrue(kwargs["response_format"]["json_schema"]["strict"])
        self.assertEqual(kwargs["messages"][0]["content"], providers.DESIGN_SYSTEM_PROMPT)
        image = next(p for p in kwargs["messages"][1]["content"] if p["type"] == "image_url")
        self.assertTrue(image["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_grok_size_estimate_uses_xai_with_the_size_schema(self):
        client = _chat('{"size": 20, "reason": "a small mug"}')
        with (
            mock.patch.dict(os.environ, {"GROK_API_KEY": "grok-key"}, clear=True),
            mock.patch("openai.OpenAI", return_value=client) as cls,
        ):
            result = providers.estimate_size("a mug")
        self.assertEqual(result["size"], 20)
        cls.assert_called_once_with(api_key="grok-key", base_url="https://api.x.ai/v1")
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["response_format"]["json_schema"]["name"], "size_estimate")
        self.assertEqual(kwargs["max_completion_tokens"], 4000)

    def test_openai_design_keeps_its_model_and_image_format(self):
        client = _chat()
        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True),
            mock.patch("openai.OpenAI", return_value=client) as cls,
            tempfile.TemporaryDirectory() as directory,
        ):
            reference = Path(directory) / "source.webp"
            Image.new("RGB", (4, 4), (0, 90, 200)).save(reference, format="WEBP")
            providers.design_program("a blue car", reference)
        cls.assert_called_once_with()
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5")
        image = next(p for p in kwargs["messages"][1]["content"] if p["type"] == "image_url")
        self.assertTrue(image["image_url"]["url"].startswith("data:image/webp;base64,"))


class DesignSchemaTests(unittest.TestCase):
    program = providers.RESPONSE_SCHEMA["properties"]["program"]

    def test_schema_and_prompt_cover_the_palette_and_specialty_parts(self):
        self.assertEqual(self.program["required"], ["name", "size", "parts", "pieces"])
        part = self.program["properties"]["parts"]["items"]["properties"]
        piece = self.program["properties"]["pieces"]["items"]["properties"]
        self.assertEqual(len(DESIGN_COLORS), 15)
        self.assertEqual(part["color"]["enum"], list(DESIGN_COLORS))
        self.assertEqual(piece["color"]["enum"], list(DESIGN_COLORS))
        self.assertEqual(piece["part"]["enum"], [p.code for p in SPECIAL_PARTS])
        for code in piece["part"]["enum"]:
            self.assertIn(f"{code} (", providers.DESIGN_SYSTEM_PROMPT)

    def test_prompt_example_matches_the_schema_and_voxelizes(self):
        example = providers._EXAMPLE
        self.assertEqual(set(example), set(self.program["required"]))
        part_schema = self.program["properties"]["parts"]["items"]
        for part in example["parts"]:
            self.assertEqual(set(part), set(part_schema["required"]), part["name"])
            self.assertIn(part["color"], DESIGN_COLORS)
        self.assertEqual(voxelize_program(example).notes, [])
        self.assertIn(json.dumps(example), providers.DESIGN_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
