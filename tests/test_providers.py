"""Concept image provider selection and request shapes, with the SDK mocked."""

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
from legolizer.catalog import PARTS


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


if __name__ == "__main__":
    unittest.main()
