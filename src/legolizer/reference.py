"""Optional reference photo for specific real-world subjects: the free lead image of the
subject's Wikipedia article, with Wikimedia Commons attribution."""

from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://en.wikipedia.org/w/api.php"
# Wikimedia's API policy rejects requests without a descriptive User-Agent.
HEADERS = {"User-Agent": "Legolizer/0.1 (https://github.com/LunarSphere/legolizer)"}
PAGE_PREFIXES = ("https://commons.wikimedia.org/", "https://en.wikipedia.org/")
SUFFIXES = {"image/jpeg": ".jpg", "image/png": ".png"}
MIN_WIDTH = 400
MAX_BYTES = 4 * 1024 * 1024


def reference_images_enabled() -> bool:
    return (os.getenv("REFERENCE_IMAGES") or "wikimedia").strip().lower() == "wikimedia"


def _get(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=10) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Reference download is too large")
    return data


def _query(**params: object) -> dict:
    url = f"{API}?{urllib.parse.urlencode({'action': 'query', 'format': 'json', **params})}"
    return json.loads(_get(url, 1024 * 1024)).get("query", {})


def _plain(value: object) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def _wikimedia_image(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and (parts.hostname or "").endswith(".wikimedia.org")


def search_reference(query: str) -> dict | None:
    """Return the free lead image of the best-matching Wikipedia article, or None."""
    pages = _query(
        generator="search",
        gsrsearch=query,
        gsrlimit=1,
        prop="pageimages",
        piprop="name",
        pilicense="free",
    ).get("pages", {})
    name = next((page.get("pageimage") for page in pages.values()), None)
    if not name:
        return None
    files = _query(
        titles=f"File:{name}",
        prop="imageinfo",
        iiprop="url|mime|size|extmetadata",
        iiurlwidth=1024,
        iiextmetadatafilter="LicenseShortName|Artist",
    ).get("pages", {})
    info = next(((page.get("imageinfo") or [{}])[0] for page in files.values()), {})
    image = info.get("thumburl") or info.get("url") or ""
    if (
        info.get("mime") not in SUFFIXES
        or info.get("width", 0) < MIN_WIDTH
        or not _wikimedia_image(image)
    ):
        return None
    meta = info.get("extmetadata", {})
    page_url = info.get("descriptionurl", "")
    return {
        "title": name.replace("_", " "),
        "page": page_url if page_url.startswith(PAGE_PREFIXES) else "",
        "image": image,
        "suffix": SUFFIXES[info["mime"]],
        "license": _plain(meta.get("LicenseShortName", {}).get("value")),
        "artist": _plain(meta.get("Artist", {}).get("value")),
    }


def find_reference(query: str, output_dir: Path) -> Path | None:
    """Download a reference photo for query into output_dir once; failures return None."""
    record = output_dir / "reference.json"
    if record.is_file():
        saved = json.loads(record.read_text(encoding="utf-8"))
        path = output_dir / saved.get("file", "")
        if saved.get("query") == query and path.is_file():
            return path
    try:
        found = search_reference(query)
        if found is None:
            print(f"No reference photo found for {query!r}")
            return None
        path = output_dir / f"reference{found.pop('suffix')}"
        path.write_bytes(_get(found.pop("image"), MAX_BYTES))
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
    except (OSError, ValueError, KeyError) as exc:
        print(f"Reference photo lookup failed: {type(exc).__name__}: {exc}")
        return None
    record.write_text(
        json.dumps({"query": query, "file": path.name, **found}, indent=2) + "\n", encoding="utf-8"
    )
    return path
