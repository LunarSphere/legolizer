"""Concept image and design provider selection and request shapes, with the SDK mocked."""

import base64
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from legolizer import providers


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


class DesignProviderTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
