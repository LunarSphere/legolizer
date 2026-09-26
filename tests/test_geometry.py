"""Regression checks for shape loss and the native LDraw coordinate mismatch."""

import argparse
import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from legolizer.catalog import DESIGN_COLORS, PART_BY_CODE, PARTS, SPECIAL_PARTS, orientations
from legolizer.ldraw import read_mpd, write_mpd, write_parts_list
from legolizer.model import parse_model, parse_pieces
from legolizer.preview import render_preview
from legolizer.shape import (
    edit_zone,
    in_zone,
    infill,
    parse_region,
    parse_selection,
    region_json,
    voxel_document,
    voxelize_program,
)
from legolizer.solver import (
    Placement,
    disconnected_placements,
    pack,
    placement_cells,
    repack_region,
    solve,
)


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

    def test_mpd_round_trips_placements(self):
        model = parse_model(
            voxel_document(
                voxelize_program(
                    _program(
                        _part("base", [3, 2, 0.6], [6, 4, 1.2], 4),
                        _part("tower", [1, 1, 1.8], [2, 2, 1.2], 1),
                        _part("cap", [1, 1, 2.6], [2, 2, 0.4], 14),
                    )
                ).cells
            )
        )
        placements = solve(model)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.mpd"
            write_mpd(model, placements, path)
            self.assertEqual(sorted(read_mpd(path), key=repr), sorted(placements, key=repr))

    def test_mpd_round_trips_specialty_rotations(self):
        pieces = parse_pieces(
            [
                dict(part=part.code, x=5 * turns, y=0, z=3 * index, color=4, rotation=90 * turns)
                for index, part in enumerate(SPECIAL_PARTS)
                for turns in range(4)
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.mpd"
            write_mpd(None, list(pieces), path)
            self.assertEqual(sorted(read_mpd(path), key=repr), sorted(pieces, key=repr))

    def test_infill_keeps_existing_pieces_and_adds_zone_pieces(self):
        program = _program(_part("base", [3, 3, 0.2], [6, 6, 0.4], 71))
        program["pieces"] = [dict(part="6141", x=0, y=0, z=1, color=4, rotation=0)]
        original = voxelize_program(program)
        zone = [parse_region({"min": [0, 0, 0], "max": [3, 3, 2]})]
        inside = dict(part="98138", x=2, y=2, z=1, color=14, rotation=0)
        patch = {
            "name": "patch",
            "size": [6, 6, 0.8],
            "parts": [_part("cover", [1, 1, 0.6], [2, 2, 0.4], 15)],
            "pieces": [inside, dict(inside, x=5, y=5)],
        }
        edited = infill(original.cells, patch, zone, original.pieces)
        self.assertEqual(edited.pieces, (*original.pieces, *parse_pieces([inside])))
        self.assertEqual(edited.cells[0, 0, 1], 4)
        self.assertEqual(edited.cells[1, 1, 1], 15)
        self.assertEqual(edited.cells[2, 2, 1], 14)
        self.assertNotIn((5, 5, 1), edited.cells)
        self.assertTrue(any("left unchanged" in note for note in edited.notes))
        self.assertTrue(any("not entirely inside" in note for note in edited.notes))

        previous = solve(parse_model(voxel_document(original.cells, original.pieces)))
        model = parse_model(voxel_document(edited.cells, edited.pieces))
        placements, loose, rebuilt = repack_region(model, previous, zone)
        self.assertEqual(loose, [])
        self.assertTrue(set(model.pieces) <= set(placements))
        self.assertNotIn(original.pieces[0], rebuilt)

    def test_infill_changes_only_the_zone(self):
        base = voxelize_program(_program(_part("wall", [4, 1, 1.2], [8, 2, 2.4], 4))).cells
        zone = [parse_region({"min": [2, 0, 3], "max": [5, 1, 5]})]
        patch = {
            "name": "patch",
            "size": [8, 2, 2.4],
            "parts": [
                _part("window", [4, 1, 1.6], [2, 2, 0.8], 0, mode="carve"),
                # Reaches far outside the zone; only the in-zone cells may change.
                _part("stripe", [4, 1, 1.8], [20, 2, 0.4], 15, mode="paint"),
                _part("turret", [4, 1, 3.0], [2, 2, 1.2], 1),
            ],
        }
        result = infill(base, patch, zone)
        for cell, color in base.items():
            if not in_zone(cell, zone):
                self.assertEqual(result.cells.get(cell), color, cell)
        self.assertNotIn((3, 0, 3), result.cells)
        self.assertEqual(result.cells[2, 0, 4], 15)
        self.assertEqual(result.cells[0, 0, 4], 4)
        self.assertFalse(any(z > 5 for _, _, z in result.cells))
        # A clipped part saved into the program replays to the same cells.
        program = _program(_part("wall", [4, 1, 1.2], [8, 2, 2.4], 4))
        program["parts"] += [
            {**part, "clip": [region_json(box) for box in zone]} for part in patch["parts"]
        ]
        self.assertEqual(voxelize_program(program).cells, result.cells)
        # Without a zone the patch may change the whole model.
        whole = infill(base, patch, None)
        self.assertEqual(whole.cells[0, 0, 4], 15)
        self.assertTrue(any(z > 5 for _, _, z in whole.cells))

    def test_edit_zone_adds_one_brick_around_each_selected_piece(self):
        self.assertIsNone(edit_zone([]))
        zone = edit_zone([((0, 3, 0), (1, 4, 2)), ((18, 5, 57), (19, 6, 59))])
        self.assertEqual(zone, [((0, 2, 0), (2, 5, 5)), ((17, 4, 54), (19, 7, 59))])

    def test_selection_validation(self):
        for raw in (
            {"min": [0, 0, 0]},
            {"min": [3, 0, 0], "max": [2, 0, 0]},
            {"min": [0, 0, 0], "max": [20, 0, 0]},
            {"min": [0, 0, 0.5], "max": [1, 1, 1]},
        ):
            with self.assertRaises(ValueError):
                parse_region(raw)
            with self.assertRaises(ValueError):
                parse_selection([raw])
        self.assertEqual(parse_selection([]), [])
        with self.assertRaises(ValueError):
            parse_selection({"min": [0, 0, 0], "max": [1, 1, 1]})
        with self.assertRaises(ValueError):
            parse_selection([{"min": [0, 0, 0], "max": [1, 1, 1]}] * 401)

    def test_zone_repack_keeps_outside_and_unchanged_pieces(self):
        program = _program(
            _part("base", [5, 2, 1.2], [10, 4, 2.4], 4),
            _part("left tower", [1, 1, 3.0], [2, 2, 1.2], 1, mirror=True),
        )
        base = voxelize_program(program).cells
        previous = solve(parse_model(voxel_document(base)))
        # Both towers are editable, but the patch only recolors the right one.
        zone = [
            parse_region({"min": [0, 0, 6], "max": [1, 1, 8]}),
            parse_region({"min": [8, 0, 6], "max": [9, 1, 8]}),
        ]
        patch = {
            "name": "patch",
            "size": [10, 4, 3.6],
            "parts": [_part("recolor", [9, 1, 3.0], [2, 2, 1.2], 14, mode="paint")],
        }
        model = parse_model(voxel_document(infill(base, patch, zone).cells))
        placements, loose, rebuilt = repack_region(model, previous, zone)
        self.assertEqual(loose, [])
        outside = [p for p in previous if not any(in_zone(c, zone) for c in placement_cells(p))]
        left = [p for p in previous if all(c[0] < 2 and c[2] >= 6 for c in placement_cells(p))]
        self.assertTrue(outside)
        self.assertTrue(left)
        self.assertTrue(set(outside + left) <= set(placements))
        self.assertTrue(rebuilt)
        self.assertTrue(all(any(in_zone(c, zone) for c in placement_cells(p)) for p in rebuilt))
        covered = {c: p.color for p in placements for c in placement_cells(p)}
        self.assertEqual(covered[9, 1, 7], 14)
        self.assertEqual(set(covered), {(v.x, v.y, v.z) for v in model.voxels})

    def test_refine_picks_the_best_parallel_candidate(self):
        from legolizer import cli, providers

        program = _program(
            _part("base", [5, 2, 1.2], [10, 4, 2.4], 4),
            _part("left tower", [1, 1, 3.0], [2, 2, 1.2], 1, mirror=True),
        )
        document = voxel_document(voxelize_program(program).cells)
        model = parse_model(document)
        good = {
            "name": "patch",
            "size": [10, 4, 3.6],
            "parts": [_part("recolor", [9, 1, 3.0], [2, 2, 1.2], 14, mode="paint")],
        }
        # Paints a cell far outside the zone, so clipping leaves the model unchanged.
        idle = {
            "name": "patch",
            "size": [10, 4, 3.6],
            "parts": [_part("recolor", [5, 2, 0.2], [1, 1, 0.4], 14, mode="paint")],
        }
        responses = iter(
            [
                {"assessment": "", "program": idle},
                {"assessment": "", "program": good},
                {"assessment": "", "program": idle},
            ]
        )
        reviews = []
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(providers, "design_infill", lambda *a: next(responses)),
            mock.patch.object(providers, "revise_infill", lambda *a: reviews.append(a)),
            mock.patch.object(cli, "_write_build", lambda *a: 0),
        ):
            source, out = Path(directory) / "source", Path(directory) / "out"
            source.mkdir()
            write_mpd(model, solve(model), source / "model.mpd")
            (source / "model.json").write_text(json.dumps(document), encoding="utf-8")
            (source / "program.json").write_text(json.dumps(program), encoding="utf-8")
            cli.refine_command(
                argparse.Namespace(
                    source=source,
                    out=out,
                    request="make the right tower yellow",
                    selection=[parse_region({"min": [8, 0, 6], "max": [9, 1, 8]})],
                    description="castle",
                    candidates=3,
                    iterations=1,
                    progress=None,
                )
            )
            refinement = json.loads((out / "refine.json").read_text(encoding="utf-8"))
            replayed = voxelize_program(
                json.loads((out / "program.json").read_text(encoding="utf-8"))
            )
            refined = json.loads((out / "model.json").read_text(encoding="utf-8"))
        self.assertEqual(reviews, [])
        self.assertEqual(refinement["candidates"], 3)
        self.assertEqual(refinement["patch"]["parts"][0]["center"], [9, 1, 3.0])
        self.assertIn({"x": 9, "y": 1, "z": 7, "color": 14}, refined["voxels"])
        self.assertEqual(refinement["zone"], [{"min": [7, 0, 3], "max": [10, 2, 11]}])
        self.assertEqual(
            replayed.cells, {(v["x"], v["y"], v["z"]): v["color"] for v in refined["voxels"]}
        )

    def test_preview_outlines_zone(self):
        cells = voxelize_program(_program(_part("block", [2, 1, 0.6], [4, 2, 1.2], 14))).cells
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.png"
            render_preview(cells, path, regions=[((1, 0, 0), (2, 1, 5))])
            from PIL import Image

            with Image.open(path) as image:
                self.assertIn((255, 0, 200), {color for _, color in image.getcolors(1 << 20)})

    def test_garden_gate_example_packs_every_specialty_part(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        program = json.loads((examples / "garden-gate.json").read_text(encoding="utf-8"))
        voxelized = voxelize_program(program)
        model = parse_model(voxel_document(voxelized.cells, voxelized.pieces))
        placements, loose = pack(model)
        self.assertEqual(loose, [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.mpd"
            write_mpd(model, placements, path)
            lines = path.read_text(encoding="utf-8").splitlines()
        used = {line.split()[-1] for line in lines if line.startswith("1 ")}
        self.assertLessEqual({f"{part.code}.dat" for part in SPECIAL_PARTS}, used)

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
