"""Browser packaging of official LDraw geometry against a stub parts library."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from legolizer.catalog import PART_BY_CODE, SPECIAL_PARTS
from legolizer.ldraw import write_mpd, write_parts_list
from legolizer.model import parse_model
from legolizer.render import _ldraw_dir
from legolizer.shape import voxel_document, voxelize_program
from legolizer.solver import Placement, pack
from legolizer.web_assets import package_build, web_name, web_text

LIBRARY = {
    "parts/3001.dat": "\ufeff0 Brick 2 x 4\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 S\\3001S01.DAT\n"
    "1 16 10 0 10 1 0 0 0 1 0 0 0 1 stud.dat\n",
    "parts/s/3001s01.dat": "0 Brick 2 x 4 body\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 48\\4-4edge.dat\n"
    "1 16 0 0 0 1 0 0 0 1 0 0 0 1 stud.dat\n",
    "p/stud.dat": "0 Stud\n2 24 6 0 0 -6 0 0\n",
    "p/48/4-4edge.dat": "0 Hi-res circle\n2 24 1 0 0 0 0 1\n",
    "LDConfig.ldr": "0 LDraw.org Configuration File\n",
    "readme.txt": "library readme\n",
}


class WebAssetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.library = self.root / "ldraw"
        for name, text in LIBRARY.items():
            path = self.library / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.source = self.root / "build"
        self.source.mkdir()
        brick = PART_BY_CODE["3001"]
        placements = [Placement(brick, 0, 0, 0, 4, 4, 2), Placement(brick, 0, 0, 3, 1, 4, 2)]
        write_mpd(None, placements, self.source / "model.mpd")
        write_parts_list(placements, self.source / "parts.json")
        (self.source / "build-guide.pdf").write_bytes(b"%PDF")
        (self.source / "render.png").write_bytes(b"png")

    def test_web_names_follow_ldraw_loader_paths(self):
        self.assertEqual(web_name("s/3001s01.dat"), "parts/s/3001s01.dat")
        self.assertEqual(web_name("48/4-4edge.dat"), "p/48/4-4edge.dat")
        self.assertEqual(web_name("stud.dat"), "stud.dat")
        text = "0 comment S\\X.DAT\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 S\\3001S01.DAT"
        self.assertEqual(
            web_text(text).splitlines(),
            ["0 comment S\\X.DAT", "1 16 0 0 0 1 0 0 0 1 0 0 0 1 parts/s/3001s01.dat"],
        )

    def test_package_embeds_each_dependency_once_and_describes_the_build(self):
        out = self.root / "web"
        metadata = package_build(
            self.source, out, self.library, "b1", "Tower", "two bricks", "/api/v1/assets/b1"
        )
        packed = (out / "packed.mpd").read_text(encoding="utf-8")
        files = [line.removeprefix("0 FILE ") for line in packed.splitlines() if "0 FILE" in line]
        self.assertEqual(
            files,
            ["model.mpd", "3001.dat", "parts/s/3001s01.dat", "p/48/4-4edge.dat", "stud.dat"],
        )
        self.assertNotIn("\ufeff", packed)
        self.assertIn("1 16 0 0 0 1 0 0 0 1 0 0 0 1 parts/s/3001s01.dat", packed)
        for name in ("model.mpd", "parts.json", "build-guide.pdf", "render.png", "readme.txt"):
            self.assertTrue((out / name).is_file(), name)
        self.assertEqual(
            (out / "LDConfig.ldr").read_text(encoding="utf-8"), LIBRARY["LDConfig.ldr"]
        )
        self.assertFalse((out / "calicense.txt").exists())
        self.assertEqual(
            {k: metadata[k] for k in ("id", "name", "description", "status")},
            {"id": "b1", "name": "Tower", "description": "two bricks", "status": "ready"},
        )
        self.assertEqual(
            (metadata["partCount"], metadata["colorCount"], metadata["stepCount"]), (2, 2, 2)
        )
        self.assertEqual(metadata["assets"]["model"], "/api/v1/assets/b1/packed.mpd")
        self.assertEqual(metadata["assets"]["preview"], "/api/v1/assets/b1/render.png")
        json.dumps(metadata)

    def test_package_in_place_keeps_the_originals(self):
        original = (self.source / "model.mpd").read_text(encoding="utf-8")
        package_build(self.source, self.source, self.library, "b1", "Tower", "", "/x")
        self.assertEqual((self.source / "model.mpd").read_text(encoding="utf-8"), original)
        self.assertTrue((self.source / "packed.mpd").is_file())

    @unittest.skipUnless(os.getenv("LDRAW_LIBRARY_PATH"), "Needs official LDraw library")
    def test_official_library_embeds_specialty_parts(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        program = json.loads((examples / "garden-gate.json").read_text(encoding="utf-8"))
        voxelized = voxelize_program(program)
        model = parse_model(voxel_document(voxelized.cells, voxelized.pieces))
        write_mpd(model, pack(model)[0], self.source / "model.mpd")
        library = Path(_ldraw_dir())
        package_build(self.source, self.source, library, "gate", "Gate", "", "/x")
        packed = (self.source / "packed.mpd").read_text(encoding="utf-8").splitlines()
        for part in SPECIAL_PARTS:
            self.assertIn(f"0 FILE {part.code}.dat", packed)

    def test_missing_official_dependency_fails(self):
        (self.library / "p" / "stud.dat").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "stud.dat"):
            package_build(self.source, self.root / "web", self.library, "b1", "T", "", "/x")


if __name__ == "__main__":
    unittest.main()
