"""Refresh the local robot demo with exact official LDraw geometry."""

import argparse
import json
from pathlib import Path

from legolizer.render import _ldraw_dir
from legolizer.web_assets import package_build

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--build", type=Path, default=Path("builds/robot-corrected"))
parser.add_argument("--library", type=Path)
args = parser.parse_args()
library = args.library or Path(_ldraw_dir() or "")
if not (library / "parts").is_dir():
    parser.error("Set LDRAW_LIBRARY_PATH or --library to the official ldraw directory")
out = Path(__file__).resolve().parents[1] / "public" / "demo"
metadata = package_build(
    args.build,
    out,
    library,
    "robot-corrected",
    "Little Bot",
    "A little character. A real-world build.",
    "/demo",
)
(out / "build.json").write_text(json.dumps(metadata, indent=2) + "\n")
print(f"Prepared {metadata['partCount']} parts in {out}")
