"""Regression checks for shape loss and the native LDraw coordinate mismatch."""

import argparse
import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from legolizer.catalog import PARTS, orientations
from legolizer.ldraw import read_mpd, write_mpd
from legolizer.model import parse_model
from legolizer.preview import render_preview
from legolizer.shape import (edit_zone, in_zone, infill, parse_region, parse_selection, region_json,
                             voxel_document, voxelize_program)
from legolizer.solver import Placement, pack, placement_cells, repack_region, solve


def _part(name, center, size, color, mode="solid", mirror=False):
    return {"name": name, "shape": "box", "mode": mode, "center": center, "size": size,
            "axis": "z", "taper": 1, "color": color, "mirror": mirror}


def _program(*parts):
    width = max(p["center"][0] + p["size"][0] / 2 for p in parts)
    return {"name": "test", "size": [round(width), 20, 20], "parts": list(parts)}


class GeometryRegressionTests(unittest.TestCase):
    def test_program_preserves_leg_gap_and_inset_colors(self):
        document = voxel_document(voxelize_program(_program(
            _part("left leg", [1, 1, 0.6], [2, 2, 1.2], 1, mirror=True),
            _part("hip bridge", [3, 1, 1.8], [6, 2, 1.2], 4),
            _part("inset detail", [2.5, 0.5, 1.8], [1, 1, 0.4], 15, mode="paint"),
        )).cells)
        model = parse_model(document)
        cells = {(v.x, v.y, v.z): v.color for v in model.voxels}
        self.assertNotIn((2, 0, 0), cells)
        self.assertEqual(cells[5, 1, 0], 1)
        self.assertEqual(cells[2, 0, 4], 15)
        self.assertEqual(cells[2, 1, 4], 4)
        placed = solve(model)
        reconstructed = {}
        for p in placed:
            for coord in itertools.product(range(p.x, p.x + p.width), range(p.y, p.y + p.depth), range(p.z, p.z + p.part.height)):
                self.assertNotIn(coord, reconstructed)
                reconstructed[coord] = p.color
        self.assertEqual(cells, reconstructed)

    def test_program_units_mirror_carve_and_ground(self):
        result = voxelize_program(_program(
            # A 1.2-unit box is exactly one brick (three plates) tall.
            _part("block", [3, 2, 2.0], [6, 4, 1.2], 4),
            _part("left post", [0.5, 0.5, 2.0], [1, 1, 1.2], 1, mirror=True),
            _part("notch", [3, 0.5, 2.0], [2, 1, 1.2], 0, mode="carve"),
            _part("stray paint", [3, 10, 10], [1, 1, 1], 15, mode="paint"),
        ))
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
        sideways = voxelize_program(_program(
            _part("tower", [1, 1, 1.2], [2, 2, 2.4], 4),
            _part("side block", [3, 1, 1.8], [2, 2, 1.2], 1),
        ))
        _, loose = pack(parse_model(voxel_document(sideways.cells)))
        self.assertTrue(loose)
        self.assertTrue(all(p.color == 1 for p in loose))
        bridged = voxelize_program(_program(
            _part("left tower", [1, 1, 0.6], [2, 2, 1.2], 4, mirror=True),
            _part("lintel", [3, 1, 1.8], [6, 2, 1.2], 1),
        ))
        _, loose = pack(parse_model(voxel_document(bridged.cells)))
        self.assertEqual(loose, [])

    def test_hidden_cells_may_take_any_color(self):
        result = voxelize_program(_program(
            _part("cube", [2, 2, 1.8], [4, 4, 3.6], 4),
            _part("hidden core", [2, 2, 1.8], [2, 2, 1.2], 1, mode="paint"),
        ))
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
                    line = next(line for line in path.read_text().splitlines() if line.startswith("1 "))
                fields = line.split()
                translation = list(map(float, fields[2:5]))
                matrix = list(map(float, fields[5:14]))
                vertices = []
                for v in itertools.product((-half_x, half_x), (0, body_height), (-half_z, half_z)):
                    vertices.append([translation[row] + sum(matrix[row * 3 + col] * v[col] for col in range(3)) for row in range(3)])
                self.assertEqual([min(v[i] for v in vertices) for i in range(3)], [40, -(5 + part.height) * 8, 60])
                self.assertEqual([max(v[i] for v in vertices) for i in range(3)], [(2 + width) * 20, -40, (3 + depth) * 20])

    def test_mpd_round_trips_placements(self):
        model = parse_model(voxel_document(voxelize_program(_program(
            _part("base", [3, 2, 0.6], [6, 4, 1.2], 4),
            _part("tower", [1, 1, 1.8], [2, 2, 1.2], 1),
            _part("cap", [1, 1, 2.6], [2, 2, 0.4], 14),
        )).cells))
        placements = solve(model)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.mpd"
            write_mpd(model, placements, path)
            self.assertEqual(sorted(read_mpd(path), key=repr), sorted(placements, key=repr))

    def test_infill_changes_only_the_zone(self):
        base = voxelize_program(_program(_part("wall", [4, 1, 1.2], [8, 2, 2.4], 4))).cells
        zone = [parse_region({"min": [2, 0, 3], "max": [5, 1, 5]})]
        patch = {"name": "patch", "size": [8, 2, 2.4], "parts": [
            _part("window", [4, 1, 1.6], [2, 2, 0.8], 0, mode="carve"),
            # Reaches far outside the zone; only the in-zone cells may change.
            _part("stripe", [4, 1, 1.8], [20, 2, 0.4], 15, mode="paint"),
            _part("turret", [4, 1, 3.0], [2, 2, 1.2], 1),
        ]}
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
        program["parts"] += [{**part, "clip": [region_json(box) for box in zone]} for part in patch["parts"]]
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
        for raw in ({"min": [0, 0, 0]}, {"min": [3, 0, 0], "max": [2, 0, 0]},
                    {"min": [0, 0, 0], "max": [20, 0, 0]}, {"min": [0, 0, 0.5], "max": [1, 1, 1]}):
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
        zone = [parse_region({"min": [0, 0, 6], "max": [1, 1, 8]}),
                parse_region({"min": [8, 0, 6], "max": [9, 1, 8]})]
        patch = {"name": "patch", "size": [10, 4, 3.6], "parts": [
            _part("recolor", [9, 1, 3.0], [2, 2, 1.2], 14, mode="paint")]}
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
        good = {"name": "patch", "size": [10, 4, 3.6], "parts": [
            _part("recolor", [9, 1, 3.0], [2, 2, 1.2], 14, mode="paint")]}
        # Paints a cell far outside the zone, so clipping leaves the model unchanged.
        idle = {"name": "patch", "size": [10, 4, 3.6], "parts": [
            _part("recolor", [5, 2, 0.2], [1, 1, 0.4], 14, mode="paint")]}
        responses = iter([{"assessment": "", "program": idle}, {"assessment": "", "program": good},
                          {"assessment": "", "program": idle}])
        reviews = []
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(providers, "design_infill", lambda *a: next(responses)), \
                mock.patch.object(providers, "revise_infill", lambda *a: reviews.append(a)), \
                mock.patch.object(cli, "_write_build", lambda *a: 0):
            source, out = Path(directory) / "source", Path(directory) / "out"
            source.mkdir()
            write_mpd(model, solve(model), source / "model.mpd")
            (source / "model.json").write_text(json.dumps(document), encoding="utf-8")
            (source / "program.json").write_text(json.dumps(program), encoding="utf-8")
            cli.refine_command(argparse.Namespace(
                source=source, out=out, request="make the right tower yellow",
                selection=[parse_region({"min": [8, 0, 6], "max": [9, 1, 8]})],
                description="castle", candidates=3, iterations=1, progress=None))
            refinement = json.loads((out / "refine.json").read_text(encoding="utf-8"))
            replayed = voxelize_program(json.loads((out / "program.json").read_text(encoding="utf-8")))
            refined = json.loads((out / "model.json").read_text(encoding="utf-8"))
        self.assertEqual(reviews, [])
        self.assertEqual(refinement["candidates"], 3)
        self.assertEqual(refinement["patch"]["parts"][0]["center"], [9, 1, 3.0])
        self.assertIn({"x": 9, "y": 1, "z": 7, "color": 14}, refined["voxels"])
        self.assertEqual(refinement["zone"], [{"min": [7, 0, 3], "max": [10, 2, 11]}])
        self.assertEqual(replayed.cells, {(v["x"], v["y"], v["z"]): v["color"] for v in refined["voxels"]})

    def test_preview_outlines_zone(self):
        cells = voxelize_program(_program(_part("block", [2, 1, 0.6], [4, 2, 1.2], 14))).cells
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.png"
            render_preview(cells, path, regions=[((1, 0, 0), (2, 1, 5))])
            from PIL import Image

            with Image.open(path) as image:
                self.assertIn((255, 0, 200), {color for _, color in image.getcolors(1 << 20)})

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
