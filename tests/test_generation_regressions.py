"""Offline regression corpus from real generated programs."""

import argparse
import copy
import json
import tempfile
import unittest
from functools import partial
from pathlib import Path
from unittest import mock

from legolizer import cli
from legolizer.catalog import PARTS
from legolizer.model import parse_model
from legolizer.shape import voxel_document, voxelize_program
from legolizer.solver import disconnected_placements, pack, solve

FIXTURES = Path(__file__).parent / "fixtures"


def load_program(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class GenerationRegressionTests(unittest.TestCase):
    def test_colosseum_prunes_only_the_two_floating_arches(self):
        program = load_program("colosseum-floating-arches")
        voxels = voxelize_program(program)
        placed, loose = pack(parse_model(voxel_document(voxels.cells, voxels.pieces)), attempts=1)
        self.assertEqual(
            {(p.part.code, p.x, p.y, p.z) for p in loose},
            {
                ("3659", 8, 0, 11),
                ("3659", 0, 8, 11),
            },
        )
        pruned, document, model, kept = cli._prune_program(program, placed, loose)
        removed = {cell for p in loose for cell in p.envelope()}
        self.assertEqual(
            voxelize_program(pruned).cells,
            {cell: color for cell, color in voxels.cells.items() if cell not in removed},
        )
        self.assertEqual(len(placed) - len(kept), 2)
        self.assertEqual(disconnected_placements(kept), [])
        self.assertEqual(parse_model(document), model)
        self.assert_exact_packing(model, kept)

    def test_treehouse_base_repairs_but_floating_railings_are_still_rejected(self):
        program = load_program("treehouse-unsupported-rails")
        voxels = voxelize_program(program)
        model = parse_model(voxel_document(voxels.cells, voxels.pieces))
        placed, loose = pack(model, attempts=1)
        self.assertTrue(loose)
        self.assertEqual(
            {voxels.owners[cell] for piece in loose for cell in piece.envelope()},
            {"balcony_railing_right", "balcony_railing_back"},
        )
        self.assertIsNone(cli._support_program(program, voxels, placed, loose))
        self.assert_exact_packing(model, placed)

    def test_lighthouse_decimal_boundary_keeps_the_lantern_attached(self):
        voxels = voxelize_program(load_program("lighthouse-boundary-gap"))
        self.assertEqual(voxels.cells.get((5, 4, 47)), 14)
        model = parse_model(voxel_document(voxels.cells, voxels.pieces))
        placed, loose = pack(model)
        self.assertEqual(loose, [])
        self.assert_exact_packing(model, placed)

    def assert_exact_packing(self, model, placements):
        source = {(v.x, v.y, v.z): v.color for v in model.voxels}
        expected = dict(source)
        for piece in model.pieces:
            expected.update(dict.fromkeys(piece.envelope(), piece.color))
        covered = {}
        for piece in placements:
            self.assertIn(piece.part, PARTS)
            for cell in piece.envelope():
                self.assertNotIn(cell, covered, f"Overlapping part at {cell}")
                covered[cell] = piece.color
        self.assertEqual(covered.keys(), expected.keys())
        self.assertTrue(set(model.pieces) <= set(placements))
        for (x, y, z), color in source.items():
            if any(
                z + dz >= 0 and (x + dx, y + dy, z + dz) not in source
                for dx, dy, dz in (
                    (1, 0, 0),
                    (-1, 0, 0),
                    (0, 1, 0),
                    (0, -1, 0),
                    (0, 0, 1),
                    (0, 0, -1),
                )
            ):
                self.assertEqual(covered[x, y, z], color, f"Changed visible color at {(x, y, z)}")

    def test_saved_builds_remain_connected_and_exact(self):
        names = [
            "garden-gate",
            "seaside-market",
            "burj-khalifa",
            "hagia-sophia-repaired",
            *(path.stem for path in sorted(FIXTURES.glob("trial-*.json"))),
        ]
        for name in names:
            with self.subTest(name=name):
                voxels = voxelize_program(load_program(name))
                model = parse_model(voxel_document(voxels.cells, voxels.pieces))
                placed, loose = pack(model)
                self.assertEqual(loose, [])
                self.assertEqual(disconnected_placements(placed), [])
                self.assert_exact_packing(model, placed)

    def test_original_hagia_sophia_only_needs_arch_support_after_retiling(self):
        voxels = voxelize_program(load_program("hagia-sophia-original"))
        model = parse_model(voxel_document(voxels.cells, voxels.pieces))
        placed, loose = pack(model, attempts=1)
        self.assertEqual([(p.part.code, p.x, p.y, p.z) for p in loose], [("3659", 8, 0, 5)])
        self.assert_exact_packing(model, placed)

    def test_generated_hagia_sophia_recovery_only_adds_endpoint_columns(self):
        program = load_program("hagia-sophia-original")
        original = copy.deepcopy(program)
        before = voxelize_program(program)
        with tempfile.TemporaryDirectory() as directory:

            def preview(model, cells, placements, loose, output, name):
                output.touch()

            with (
                mock.patch.object(cli, "_render_build_preview", side_effect=preview),
                mock.patch.object(cli, "pack", side_effect=partial(pack, attempts=1)),
                mock.patch("legolizer.providers.revise_program") as review,
            ):
                result, document, model, placed, loose = cli._refine(
                    argparse.Namespace(iterations=0, program=None, description="Hagia Sophia"),
                    Path(directory),
                    program,
                    None,
                )
            review.assert_not_called()
        after = voxelize_program(result)
        self.assertEqual(program, original)
        self.assertEqual(loose, [])
        self.assertEqual(after.pieces, before.pieces)
        self.assertEqual(
            set(after.cells) - set(before.cells), {(x, 0, z) for x in (8, 11) for z in range(1, 5)}
        )
        self.assertEqual({cell: after.cells[cell] for cell in before.cells}, before.cells)
        self.assertEqual(parse_model(document), model)
        self.assert_exact_packing(model, placed)

    def test_unbuildable_inputs_fail_instead_of_publishing_loose_parts(self):
        cases = {
            "large unsupported gap": [("3005", 0, 0, 0), ("3005", 0, 0, 11)],
            "sideways only": [("3005", 0, 0, 0), ("3005", 1, 0, 0)],
            "tile top": [("3024", 0, 0, 0), ("98138", 0, 0, 1), ("6141", 0, 0, 2)],
        }
        for name, pieces in cases.items():
            with self.subTest(name=name):
                program = {
                    "name": name,
                    "size": [4, 4, 8],
                    "parts": [],
                    "pieces": [
                        dict(part=code, x=x, y=y, z=z, color=4, rotation=0)
                        for code, x, y, z in pieces
                    ],
                }
                voxels = voxelize_program(program)
                model = parse_model(voxel_document(voxels.cells, voxels.pieces))
                placed, loose = pack(model)
                self.assertTrue(loose)
                self.assertIsNone(cli._support_program(program, voxels, placed, loose))
                with self.assertRaisesRegex(ValueError, "floating/disconnected"):
                    solve(model)


if __name__ == "__main__":
    unittest.main()
