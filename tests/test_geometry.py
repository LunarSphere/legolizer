"""Regression checks for shape loss and the native LDraw coordinate mismatch."""

import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from legolizer.catalog import DESIGN_COLORS, PART_BY_CODE, PARTS, SPECIAL_PARTS, orientations
from legolizer.ldraw import write_mpd, write_parts_list
from legolizer.model import parse_model, parse_pieces
from legolizer.preview import render_preview
from legolizer.shape import _contains, voxel_document, voxelize_program
from legolizer.solver import Placement, _greedy, disconnected_placements, pack, solve


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
    def test_wide_plate_base_is_bonded_across_course_seams(self):
        voxels = voxelize_program(_program(_part("base", [8, 4, 0.6], [16, 8, 1.2], 27)))
        model = parse_model(voxel_document(voxels.cells))
        self.assertTrue(disconnected_placements(_greedy(voxels.cells, model, None, 27)))
        placed, loose = pack(model, attempts=1)
        self.assertEqual(loose, [])
        cells = [cell for piece in placed for cell in piece.envelope()]
        self.assertEqual(len(cells), len(set(cells)))
        self.assertEqual(set(cells), set(voxels.cells))

    def test_decimal_faces_remain_half_open_on_every_axis(self):
        for shape in ("box", "cylinder"):
            for axis, index in zip("xyz", range(3), strict=True):
                with self.subTest(shape=shape, axis=axis):
                    part = _part("decimal boundary", [1, 1, 1], [2, 2, 2], 4)
                    part.update(
                        shape=shape, axis=axis if shape == "cylinder" else "xyz"[(index + 1) % 3]
                    )
                    part["center"][index] = 19.8
                    part["size"][index] = 1.6
                    point = [1, 1, 1]
                    point[index] = 19.0
                    self.assertTrue(_contains(part, point))
                    point[index] = 20.6
                    self.assertFalse(_contains(part, point))
                    point[index] = 19.0 - 1e-7
                    self.assertFalse(_contains(part, point))
                    point[index] = 20.6 - 1e-7
                    self.assertTrue(_contains(part, point))

    def test_dome_repairs_staggered_courses_without_changing_voxels(self):
        dome = _part("dome", [5, 5, 5], [9, 9, 6], 1)
        dome["shape"] = "ellipsoid"
        result = voxelize_program(_program(_part("base", [5, 5, 1.2], [10, 10, 2.4], 19), dome))
        model = parse_model(voxel_document(result.cells))
        initial = _greedy(result.cells, model, None, 19)
        self.assertTrue(disconnected_placements(initial))
        placed, loose = pack(model, attempts=1, recolor_hidden=False)
        self.assertEqual(loose, [])
        covered = {}
        for piece in placed:
            for cell in piece.envelope():
                self.assertNotIn(cell, covered)
                covered[cell] = piece.color
        self.assertEqual(covered, result.cells)

    def test_symmetric_voxels_prefer_mirrored_placement(self):
        model = parse_model(
            dict(
                width=6,
                depth=2,
                height=1,
                voxels=[
                    dict(x=x, y=y, z=z, color=4)
                    for x in range(6)
                    for y in range(2)
                    for z in range(3)
                ],
            )
        )
        with mock.patch("legolizer.solver._greedy", wraps=_greedy) as greedy:
            placements, loose = pack(model, attempts=4)
        self.assertEqual(loose, [])
        self.assertLessEqual(greedy.call_count, 2)
        reflected = sorted(
            (model.width - p.x - p.width, p.y, p.z, p.part.code, p.width, p.depth, p.color)
            for p in placements
        )
        actual = sorted((p.x, p.y, p.z, p.part.code, p.width, p.depth, p.color) for p in placements)
        self.assertEqual(actual, reflected)

    def test_asymmetric_voxels_remain_packable(self):
        model = parse_model(
            dict(
                width=4,
                depth=1,
                height=1,
                voxels=[
                    dict(x=x, y=0, z=z, color=1 if x == 2 else 4)
                    for x in range(4)
                    for z in range(3)
                ],
            )
        )
        placements, _ = pack(model, attempts=2)
        covered = {
            (x, y, z, placement.color)
            for placement in placements
            for x in range(placement.x, placement.x + placement.width)
            for y in range(placement.y, placement.y + placement.depth)
            for z in range(placement.z, placement.z + placement.part.height)
        }
        self.assertEqual(
            covered,
            {(voxel.x, voxel.y, voxel.z, voxel.color) for voxel in model.voxels},
        )

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

    def test_specialty_program_roundtrips_and_preserves_all_rotations(self):
        for part in SPECIAL_PARTS:
            for rotation in (0, 90, 180, 270):
                with self.subTest(part=part.code, rotation=rotation):
                    program = _program(_part("base", [3, 3, 0.2], [6, 6, 0.4], 71))
                    program["pieces"] = [
                        dict(part=part.code, x=1, y=1, z=1, color=4, rotation=rotation)
                    ]
                    result = voxelize_program(program)
                    document = voxel_document(result.cells, result.pieces)
                    model = parse_model(document)
                    placed = solve(model)
                    self.assertEqual(model.pieces, result.pieces)
                    self.assertTrue(all(piece in placed for piece in model.pieces))
                    reserved = set(model.pieces[0].envelope())
                    self.assertFalse(reserved & {(v.x, v.y, v.z) for v in model.voxels})

    def test_specialty_connections_require_actual_studs_and_sockets(self):
        base = Placement(PART_BY_CODE["3031"], 0, 0, 0, 71, 4, 4)
        for code, contacts in (("98138", set()), ("3040b", {(0, 1)}), ("3063b", {(0, 0), (1, 1)})):
            part = PART_BY_CODE[code]
            for rotation in (0, 90, 180, 270):
                piece = parse_pieces([dict(part=code, x=0, y=0, z=1, color=4, rotation=rotation)])[
                    0
                ]
                expected = set()
                for x, y in contacts:
                    w, d = part.width, part.depth
                    for _ in range(rotation // 90):
                        x, y, w, d = y, w - 1 - x, d, w
                    expected.add((x, y))
                for x in range(piece.width):
                    for y in range(piece.depth):
                        cap = Placement(PART_BY_CODE["3024"], x, y, 1 + part.height, 15, 1, 1)
                        with self.subTest(code=code, rotation=rotation, x=x, y=y):
                            loose = disconnected_placements([base, piece, cap])
                            self.assertEqual(loose, [] if (x, y) in expected else [cap])

    def test_arch_cannot_attach_through_its_opening(self):
        for rotation in (0, 90, 180, 270):
            arch = parse_pieces([dict(part="3659", x=0, y=0, z=1, color=19, rotation=rotation)])[0]
            for index in range(4):
                x, y = (index, 0) if rotation % 180 == 0 else (0, index)
                support = Placement(PART_BY_CODE["3024"], x, y, 0, 71, 1, 1)
                with self.subTest(rotation=rotation, index=index):
                    self.assertEqual(
                        disconnected_placements([support, arch]), [] if index in (0, 3) else [arch]
                    )

    def test_invalid_or_overlapping_explicit_pieces_are_rejected(self):
        valid = dict(part="3659", x=0, y=0, z=0, color=19, rotation=0)
        for change in (
            {"part": "fake"},
            {"rotation": 45},
            {"x": True},
            {"z": -1},
            {"x": 18},
            {"color": 999},
            {"color": False},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_pieces([valid | change])
        with self.assertRaisesRegex(ValueError, "overlaps"):
            parse_pieces([valid, valid | {"part": "98138", "x": 1}])
        with self.assertRaisesRegex(ValueError, "overlaps"):
            parse_model(
                dict(
                    width=4,
                    depth=1,
                    height=1,
                    pieces=[valid],
                    voxels=[dict(x=1, y=0, z=0, color=4)],
                )
            )
        with self.assertRaisesRegex(ValueError, "declared dimensions"):
            parse_model(dict(width=3, depth=1, height=1, pieces=[valid], voxels=[]))

    def test_piece_only_program_is_grounded_and_can_be_reloaded(self):
        program = dict(
            name="round detail",
            size=[1, 1, 2],
            parts=[],
            pieces=[
                dict(part="6141", x=0, y=0, z=3, color=4, rotation=0),
                dict(part="98138", x=0, y=0, z=4, color=15, rotation=0),
            ],
        )
        result = voxelize_program(program)
        self.assertEqual([p.z for p in result.pieces], [0, 1])
        model = parse_model(voxel_document(result.cells, result.pieces))
        self.assertEqual(model.voxels, ())
        self.assertEqual(solve(model), list(result.pieces))

    def test_specialty_export_offsets_and_rotations(self):
        bounds = {
            "6141": (-10, 10, -10, 10),
            "98138": (-10, 10, -10, 10),
            "3040b": (-10, 10, -30, 10),
            "3659": (-40, 40, -10, 10),
            "3063b": (-10, 30, -30, 10),
        }
        for code, (xmin, xmax, zmin, zmax) in bounds.items():
            for rotation in (0, 90, 180, 270):
                piece = parse_pieces([dict(part=code, x=2, y=3, z=5, color=4, rotation=rotation)])[
                    0
                ]
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "model.mpd"
                    write_mpd(None, [piece], path)
                    fields = next(
                        line.split()
                        for line in path.read_text().splitlines()
                        if line.startswith("1 ")
                    )
                translation, matrix = list(map(int, fields[2:5])), list(map(int, fields[5:14]))
                vertices = [
                    [
                        translation[row] + sum(matrix[row * 3 + col] * v[col] for col in range(3))
                        for row in range(3)
                    ]
                    for v in itertools.product(
                        (xmin, xmax), (0, piece.part.height * 8), (zmin, zmax)
                    )
                ]
                with self.subTest(code=code, rotation=rotation):
                    self.assertEqual(
                        [min(v[i] for v in vertices) for i in range(3)],
                        [40, -(5 + piece.part.height) * 8, 60],
                    )
                    self.assertEqual(
                        [max(v[i] for v in vertices) for i in range(3)],
                        [(2 + piece.width) * 20, -40, (3 + piece.depth) * 20],
                    )

    def test_packer_preserves_loose_specialty_pieces(self):
        program = _program(_part("base", [2, 2, 0.2], [4, 4, 0.4], 71))
        program["pieces"] = [dict(part="6141", x=4, y=0, z=0, color=4, rotation=0)]
        result = voxelize_program(program)
        model = parse_model(voxel_document(result.cells, result.pieces))
        placed, loose = pack(model, attempts=2)
        self.assertEqual(loose, list(result.pieces))
        self.assertTrue(all(piece in placed for piece in result.pieces))
        with self.assertRaisesRegex(ValueError, "floating/disconnected"):
            solve(model)

    def test_palette_and_bricklink_aliases(self):
        self.assertEqual(len(DESIGN_COLORS), 15)
        self.assertEqual(len(set(DESIGN_COLORS)), 15)
        pieces = parse_pieces(
            [
                dict(part="6141", x=0, y=0, z=0, color=73, rotation=0),
                dict(part="3040b", x=2, y=0, z=0, color=8, rotation=0),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parts.json"
            write_parts_list(list(pieces), path)
            parts = {p["part_id"]: p for p in json.loads(path.read_text())["parts"]}
        self.assertTrue(parts["6141"]["bricklink_url"].endswith("P=4073"))
        self.assertTrue(parts["3040b"]["bricklink_url"].endswith("P=3040"))
        self.assertEqual(parts["6141"]["color_id"], 73)

    @unittest.skipUnless(os.getenv("LDRAW_LIBRARY_PATH"), "Needs official LDraw library")
    def test_whitelist_dimensions_match_official_geometry(self):
        from ldraw.parts import Parts

        catalog = Parts(Path(os.environ["LDRAW_LIBRARY_PATH"]) / "parts.lst")
        for part in PARTS:
            box = catalog.geometry(part.code).bounds
            self.assertEqual(box.max.x - box.min.x, part.width * 20, part.code)
            self.assertEqual(box.max.z - box.min.z, part.depth * 20, part.code)
            self.assertEqual(box.max.y, part.height * 8, part.code)
            self.assertEqual(
                ((box.min.x + box.max.x) / 2, (box.min.z + box.max.z) / 2),
                part.native_center,
                part.code,
            )


if __name__ == "__main__":
    unittest.main()
