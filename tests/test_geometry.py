"""Regression checks for shape loss and the native LDraw coordinate mismatch."""

import itertools
import os
import tempfile
import unittest
from pathlib import Path

from legolizer.catalog import PARTS, orientations
from legolizer.ldraw import write_mpd
from legolizer.model import parse_model
from legolizer.preview import render_preview
from legolizer.shape import voxel_document, voxelize_program
from legolizer.solver import Placement, pack, solve


def _part(name, center, size, color, mode="solid", mirror=False):
    return {
        "name": name,
        "shape": "box",
        "mode": mode,
        "center": center,
        "size": size,
        "axis": "z",
        "taper": 1,
        "color": color,
        "mirror": mirror,
    }


def _program(*parts):
    width = max(p["center"][0] + p["size"][0] / 2 for p in parts)
    return {"name": "test", "size": [round(width), 20, 20], "parts": list(parts)}


class GeometryRegressionTests(unittest.TestCase):
    def test_program_preserves_leg_gap_and_inset_colors(self):
        document = voxel_document(
            voxelize_program(
                _program(
                    _part("left leg", [1, 1, 0.6], [2, 2, 1.2], 1, mirror=True),
                    _part("hip bridge", [3, 1, 1.8], [6, 2, 1.2], 4),
                    _part("inset detail", [2.5, 0.5, 1.8], [1, 1, 0.4], 15, mode="paint"),
                )
            ).cells
        )
        model = parse_model(document)
        cells = {(v.x, v.y, v.z): v.color for v in model.voxels}
        self.assertNotIn((2, 0, 0), cells)
        self.assertEqual(cells[5, 1, 0], 1)
        self.assertEqual(cells[2, 0, 4], 15)
        self.assertEqual(cells[2, 1, 4], 4)
        placed = solve(model)
        reconstructed = {}
        for p in placed:
            for coord in itertools.product(
                range(p.x, p.x + p.width),
                range(p.y, p.y + p.depth),
                range(p.z, p.z + p.part.height),
            ):
                self.assertNotIn(coord, reconstructed)
                reconstructed[coord] = p.color
        self.assertEqual(cells, reconstructed)

    def test_program_units_mirror_carve_and_ground(self):
        result = voxelize_program(
            _program(
                # A 1.2-unit box is exactly one brick (three plates) tall.
                _part("block", [3, 2, 2.0], [6, 4, 1.2], 4),
                _part("left post", [0.5, 0.5, 2.0], [1, 1, 1.2], 1, mirror=True),
                _part("notch", [3, 0.5, 2.0], [2, 1, 1.2], 0, mode="carve"),
                _part("stray paint", [3, 10, 10], [1, 1, 1], 15, mode="paint"),
            )
        )
        cells = result.cells
        # Floating input is lowered to the ground and the heights are true plates.
        self.assertEqual({z for _, _, z in cells}, {0, 1, 2})
        self.assertEqual(cells[0, 0, 0], 1)
        self.assertEqual(cells[5, 0, 0], 1)
        self.assertNotIn((2, 0, 1), cells)
        self.assertNotIn((3, 0, 1), cells)
        self.assertEqual(len(cells), 6 * 4 * 3 - 2 * 3)
        self.assertTrue(any("stray paint" in note for note in result.notes))
        self.assertTrue(any("lowered" in note for note in result.notes))

    def test_packer_reports_parts_that_only_touch_sideways(self):
        sideways = voxelize_program(
            _program(
                _part("tower", [1, 1, 1.2], [2, 2, 2.4], 4),
                _part("side block", [3, 1, 1.8], [2, 2, 1.2], 1),
            )
        )
        _, loose = pack(parse_model(voxel_document(sideways.cells)))
        self.assertTrue(loose)
        self.assertTrue(all(p.color == 1 for p in loose))
        bridged = voxelize_program(
            _program(
                _part("left tower", [1, 1, 0.6], [2, 2, 1.2], 4, mirror=True),
                _part("lintel", [3, 1, 1.8], [6, 2, 1.2], 1),
            )
        )
        _, loose = pack(parse_model(voxel_document(bridged.cells)))
        self.assertEqual(loose, [])

    def test_hidden_cells_may_take_any_color(self):
        result = voxelize_program(
            _program(
                _part("cube", [2, 2, 1.8], [4, 4, 3.6], 4),
                _part("hidden core", [2, 2, 1.8], [2, 2, 1.2], 1, mode="paint"),
            )
        )
        placed, loose = pack(parse_model(voxel_document(result.cells)))
        self.assertEqual(loose, [])
        self.assertEqual({p.color for p in placed}, {4})

    def test_preview_renders_all_views(self):
        cells = voxelize_program(_program(_part("block", [2, 1, 0.6], [4, 2, 1.2], 14))).cells
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.png"
            render_preview(cells, path, title="block")
            from PIL import Image

            with Image.open(path) as image:
                self.assertGreater(image.width, 300)

    def test_exported_native_bodies_match_solved_footprints(self):
        # Authoritative native body extents (studs excluded) for a 2x4 brick
        # and 1x2 plate, including rotated and mixed-height placements.
        for code, half_x, half_z, body_height in (("3001", 40, 20, 24), ("3023", 20, 10, 8)):
            part = next(p for p in PARTS if p.code == code)
            for width, depth in orientations(part):
                placement = Placement(part, 2, 3, 5, 4, width, depth)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "model.mpd"
                    write_mpd(None, [placement], path)
                    line = next(
                        line for line in path.read_text().splitlines() if line.startswith("1 ")
                    )
                fields = line.split()
                translation = list(map(float, fields[2:5]))
                matrix = list(map(float, fields[5:14]))
                vertices = []
                for v in itertools.product((-half_x, half_x), (0, body_height), (-half_z, half_z)):
                    vertices.append(
                        [
                            translation[row]
                            + sum(matrix[row * 3 + col] * v[col] for col in range(3))
                            for row in range(3)
                        ]
                    )
                self.assertEqual(
                    [min(v[i] for v in vertices) for i in range(3)],
                    [40, -(5 + part.height) * 8, 60],
                )
                self.assertEqual(
                    [max(v[i] for v in vertices) for i in range(3)],
                    [(2 + width) * 20, -40, (3 + depth) * 20],
                )

    @unittest.skipUnless(os.getenv("LDRAW_LIBRARY_PATH"), "Needs official LDraw library")
    def test_whitelist_dimensions_match_official_geometry(self):
        from ldraw.parts import Parts

        catalog = Parts(Path(os.environ["LDRAW_LIBRARY_PATH"]) / "parts.lst")
        for part in PARTS:
            box = catalog.geometry(part.code).bounds
            self.assertEqual(box.max.x - box.min.x, part.width * 20, part.code)
            self.assertEqual(box.max.z - box.min.z, part.depth * 20, part.code)
            self.assertEqual(box.max.y, part.height * 8, part.code)


if __name__ == "__main__":
    unittest.main()
