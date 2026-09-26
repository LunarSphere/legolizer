"""Guard studio UI sources against UTF-8 mojibake regressions."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = ROOT / "src" / "frontend" / "src"

# Classic UTF-8-as-CP1252 mojibake for common punctuation used in the studio UI.
MOJIBAKE_MARKERS = (
    "\u00e2\u2020\u2019",  # â†’  (was →)
    "\u00c2\u00b7",  # Â·   (was ·)
    "\u00e2\u20ac\u00a6",  # â€¦  (was …)
    "\u00e2\u20ac\u201c",  # â€“  (was –)
)


class FrontendEncodingTests(unittest.TestCase):
    def test_studio_sources_have_no_utf8_mojibake(self):
        offenders: list[str] = []
        for path in sorted(FRONTEND_SRC.rglob("*")):
            if path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx", ".css", ".html"}:
                continue
            text = path.read_text(encoding="utf-8")
            hits = [marker for marker in MOJIBAKE_MARKERS if marker in text]
            if hits:
                offenders.append(f"{path.relative_to(ROOT)}: {hits!r}")
        self.assertEqual(
            offenders,
            [],
            "Studio UI text was re-saved with UTF-8 bytes misread as Windows-1252",
        )


if __name__ == "__main__":
    unittest.main()
