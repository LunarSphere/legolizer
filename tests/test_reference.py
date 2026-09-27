"""Wikipedia lead-image reference photos, with every network call mocked."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from legolizer import reference

THUMB = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Tower.jpg/1024px-Tower.jpg"


def _jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (90, 60, 40)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _search(name="Tour_Eiffel.jpg"):
    page = {"pageid": 1, "title": "Eiffel Tower"}
    if name:
        page["pageimage"] = name
    return {"query": {"pages": {"1": page}}}


def _file(**overrides):
    info = {
        "url": THUMB,
        "thumburl": THUMB,
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Tour_Eiffel.jpg",
        "mime": "image/jpeg",
        "width": 2900,
        "extmetadata": {
            "LicenseShortName": {"value": "Public domain"},
            "Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:B">Benh &amp; co</a>'},
        },
        **overrides,
    }
    return {"query": {"pages": {"-1": {"title": "File:Tour_Eiffel.jpg", "imageinfo": [info]}}}}


class FakeWeb:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url, limit):
        self.urls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, bytes) else json.dumps(response).encode()


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.out = Path(self.directory.name)

    def test_toggle_defaults_to_wikimedia(self):
        for value, enabled in ((None, True), ("wikimedia", True), (" Wikimedia ", True)):
            env = {} if value is None else {"REFERENCE_IMAGES": value}
            with self.subTest(value=value), mock.patch.dict(os.environ, env, clear=True):
                self.assertIs(reference.reference_images_enabled(), enabled)
        with mock.patch.dict(os.environ, {"REFERENCE_IMAGES": "off"}):
            self.assertFalse(reference.reference_images_enabled())

    def test_search_returns_the_lead_image_with_attribution(self):
        web = FakeWeb(_search(), _file())
        with mock.patch.object(reference, "_get", web):
            found = reference.search_reference("Eiffel Tower")
        self.assertEqual(
            found,
            {
                "title": "Tour Eiffel.jpg",
                "page": "https://commons.wikimedia.org/wiki/File:Tour_Eiffel.jpg",
                "image": THUMB,
                "suffix": ".jpg",
                "license": "Public domain",
                "artist": "Benh & co",
            },
        )
        self.assertIn("pilicense=free", web.urls[0])
        self.assertIn("gsrsearch=Eiffel+Tower", web.urls[0])
        self.assertIn("titles=File%3ATour_Eiffel.jpg", web.urls[1])

    def test_search_rejects_unusable_images(self):
        for label, file in (
            ("small", _file(width=200)),
            ("svg", _file(mime="image/svg+xml")),
            ("foreign host", _file(thumburl="https://example.com/x.jpg", url="https://e.com")),
            ("plain http", _file(thumburl=THUMB.replace("https", "http"))),
        ):
            with (
                self.subTest(label),
                mock.patch.object(reference, "_get", FakeWeb(_search(), file)),
            ):
                self.assertIsNone(reference.search_reference("Eiffel Tower"))
        with mock.patch.object(reference, "_get", FakeWeb(_search(name=None))):
            self.assertIsNone(reference.search_reference("Millennium Falcon"))
        web = FakeWeb(_search(), _file(descriptionurl="javascript:alert(1)"))
        with mock.patch.object(reference, "_get", web):
            self.assertEqual(reference.search_reference("Eiffel Tower")["page"], "")

    def test_find_reference_downloads_verifies_and_caches(self):
        web = FakeWeb(_search(), _file(), _jpeg())
        with mock.patch.object(reference, "_get", web):
            path = reference.find_reference("Eiffel Tower", self.out)
            self.assertEqual(reference.find_reference("Eiffel Tower", self.out), path)
        self.assertEqual(path, self.out / "reference.jpg")
        self.assertEqual(web.urls[2], THUMB)
        saved = json.loads((self.out / "reference.json").read_text(encoding="utf-8"))
        self.assertEqual(
            (saved["query"], saved["file"], saved["license"]),
            ("Eiffel Tower", "reference.jpg", "Public domain"),
        )
        self.assertNotIn("image", saved)

    def test_find_reference_failures_are_not_fatal(self):
        for label, web in (
            ("offline", FakeWeb(OSError("no network"))),
            ("not found", FakeWeb(_search(name=None))),
            ("bad json", FakeWeb(b"<html>")),
            ("not an image", FakeWeb(_search(), _file(), b"not a jpeg")),
        ):
            with self.subTest(label), mock.patch.object(reference, "_get", web):
                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    self.assertIsNone(reference.find_reference("Eiffel Tower", self.out))
        self.assertFalse((self.out / "reference.json").exists())

    def test_downloads_are_capped_and_identify_the_client(self):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with mock.patch(
            "urllib.request.urlopen", side_effect=lambda *a, **k: Response(b"x" * 11)
        ) as urlopen:
            with self.assertRaises(ValueError):
                reference._get("https://en.wikipedia.org/w/api.php", 10)
            self.assertEqual(reference._get("https://en.wikipedia.org/w/api.php", 11), b"x" * 11)
        request = urlopen.call_args.args[0]
        self.assertIn("Legolizer", request.get_header("User-agent"))
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)


if __name__ == "__main__":
    unittest.main()
