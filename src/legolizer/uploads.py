"""Bounded validation of browser-supplied images; filenames are never trusted."""
import base64
import binascii
from io import BytesIO
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 4 * 1024 * 1024
FORMATS = {'PNG': ('image/png', '.png'), 'JPEG': ('image/jpeg', '.jpg'), 'WEBP': ('image/webp', '.webp')}


def validate_upload(value):
    if not isinstance(value, dict) or set(value) != {'mediaType', 'data'}:
        raise ValueError('Upload a PNG, JPEG, or WebP image.')
    encoded = value['data']
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError('Images must be 4 MB or smaller.')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('The uploaded image is not valid base64.') from None
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError('Images must be nonempty and 4 MB or smaller.')
    try:
        with Image.open(BytesIO(data), formats=list(FORMATS)) as image:
            detected = FORMATS.get(image.format)
            if detected is None or detected[0] != value['mediaType']:
                raise ValueError('The image contents do not match its PNG, JPEG, or WebP type.')
            if max(image.size) > 4096 or min(image.size) < 32:
                raise ValueError('Each image dimension must be between 32 and 4096 pixels.')
            if getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Upload a still image rather than an animation.')
            image.verify()
        with Image.open(BytesIO(data), formats=list(FORMATS)) as image:
            image.load()  # Fully decode before accepting a job or making paid calls.
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ValueError('This image could not be decoded. Try exporting it as PNG or JPEG.') from None
    return data, detected[1]
