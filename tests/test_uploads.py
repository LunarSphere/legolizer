"""Validation of browser-supplied reference images."""

import base64
import io
import unittest

from PIL import Image

from legolizer.uploads import validate_upload


def _encode(image, fmt, **kwargs):
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return base64.b64encode(buffer.getvalue()).decode()


def _upload(fmt="PNG", media_type="image/png", size=(64, 48), **kwargs):
    return {"mediaType": media_type, "data": _encode(Image.new("RGB", size, "red"), fmt, **kwargs)}


class UploadTests(unittest.TestCase):
    def test_accepts_png_jpeg_and_webp(self):
        for fmt, media_type, suffix in (
            ("PNG", "image/png", ".png"),
            ("JPEG", "image/jpeg", ".jpg"),
            ("WEBP", "image/webp", ".webp"),
        ):
            with self.subTest(fmt=fmt):
                upload = _upload(fmt, media_type)
                data, detected = validate_upload(upload)
                self.assertEqual(detected, suffix)
                self.assertEqual(data, base64.b64decode(upload["data"]))

    def test_rejects_malformed_payloads(self):
        valid = _upload()
        cases = [
            (None, "Upload a PNG"),
            ({"data": valid["data"]}, "Upload a PNG"),
            ({**valid, "name": "x.png"}, "Upload a PNG"),
            ({**valid, "data": 5}, "4 MB or smaller"),
            ({**valid, "data": "A" * (4 * ((4 * 1024 * 1024 + 2) // 3) + 4)}, "4 MB or smaller"),
            ({**valid, "data": "not base64!"}, "not valid base64"),
            ({**valid, "data": ""}, "nonempty"),
        ]
        for value, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_upload(value)

    def test_rejects_images_that_do_not_match_or_fit(self):
        cases = [
            (_upload("PNG", "image/jpeg"), "do not match"),
            (_upload(size=(16, 64)), "between 32 and 4096"),
            (_upload(size=(4097, 32)), "between 32 and 4096"),
            (
                _upload(save_all=True, append_images=[Image.new("RGB", (64, 64), "blue")]),
                "still image",
            ),
        ]
        for value, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_upload(value)

    def test_rejects_undecodable_images(self):
        png = base64.b64decode(_upload()["data"])
        gif = _upload("GIF", "image/gif")
        for data in (b"not an image", png[: len(png) // 2]):
            with self.subTest(size=len(data)), self.assertRaisesRegex(ValueError, "could not be"):
                validate_upload({"mediaType": "image/png", "data": base64.b64encode(data).decode()})
        with self.assertRaisesRegex(ValueError, "could not be decoded"):
            validate_upload(gif)


if __name__ == "__main__":
    unittest.main()
