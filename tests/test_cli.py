"""Generated support repairs and offline recovery of saved generation jobs."""

import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from legolizer import cli, server
from legolizer.model import parse_model
from legolizer.shape import voxel_document, voxelize_program
from legolizer.solver import disconnected_placements, pack


def arch_program(rotation=0, gap=4, raised=0):
    width, depth = (4, 1) if rotation % 180 == 0 else (1, 4)
    return {
        "name": "supported arch",
        "size": [width, depth, 8],
        "parts": [
            {
                "name": "base",
                "shape": "box",
                "mode": "solid",
                "center": [width / 2, depth / 2, raised * 0.4 + 0.2],
                "size": [width, depth, 0.4],
                "axis": "z",
                "taper": 1,
                "color": 71,
                "mirror": False,
            }
        ],
        "pieces": [
            {
                "part": "3659",
                "x": 0,
                "y": 0,
                "z": raised + gap + 1,
                "rotation": rotation,
                "color": 19,
            }
        ],
    }


def propose(program):
    voxels = voxelize_program(program)
    placed, loose = pack(parse_model(voxel_document(voxels.cells, voxels.pieces)), attempts=1)
    return cli._support_program(program, voxels, placed, loose)


class GeneratedSupportTests(unittest.TestCase):
    def pruning_program(self, raised=0):
        return {
            "name": "tower with stray detail",
            "size": [4, 1, 40],
            "parts": [
                {
                    "name": "hidden beneath stray part",
                    "shape": "box",
                    "mode": "solid",
                    "center": [3.5, 0.5, (10 + raised + 0.5) * 0.4],
                    "size": [1, 1, 0.4],
                    "axis": "z",
                    "taper": 1,
                    "color": 4,
                    "mirror": False,
                }
            ],
            "pieces": [
                dict(part="3023", x=0, y=0, z=raised + z, color=19, rotation=0) for z in range(29)
            ]
            + [dict(part="3024", x=3, y=0, z=raised + 10, color=14, rotation=0)],
        }

    def test_pruning_preserves_retained_cells_and_handles_ground_offsets(self):
        for raised in (0, 10):
            with self.subTest(raised=raised):
                program = self.pruning_program(raised)
                original = copy.deepcopy(program)
                voxels = voxelize_program(program)
                placed, loose = pack(parse_model(voxel_document(voxels.cells, voxels.pieces)))
                pruned, document, model, kept = cli._prune_program(program, placed, loose)
                after = voxelize_program(pruned)
                self.assertEqual(program, original)
                self.assertEqual(voxels.ground_offset, raised)
                self.assertEqual(set(voxels.cells) - set(after.cells), {(3, 0, 10)})
                self.assertEqual(len(after.pieces), 29)
                self.assertEqual(parse_model(document), model)
                self.assertEqual(disconnected_placements(kept), [])
                self.assertEqual(pack(model)[1], [])

    def test_pruning_rejects_large_removals_and_disconnected_remainder(self):
        program = self.pruning_program()
        voxels = voxelize_program(program)
        placed, loose = pack(parse_model(voxel_document(voxels.cells, voxels.pieces)))
        self.assertIsNone(cli._prune_program(program, placed, []))
        self.assertIsNone(cli._prune_program(program, placed, placed[:9]))
        self.assertIsNone(cli._prune_program(program, placed[:10], loose))
        self.assertIsNone(cli._prune_program(program, placed, [placed[0]]))
        with mock.patch.object(cli, "disconnected_placements", return_value=loose):
            self.assertIsNone(cli._prune_program(program, placed, loose))

    def test_pruning_is_final_generated_only_and_records_removed_parts(self):
        for imported in (False, True):
            with self.subTest(imported=imported), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                program = self.pruning_program()

                def preview(model, cells, placements, loose, path, name):
                    path.touch()

                with (
                    mock.patch.object(cli, "_render_build_preview", side_effect=preview),
                    mock.patch(
                        "legolizer.providers.revise_invalid_program",
                        side_effect=AssertionError("Unexpected validation failure"),
                    ),
                    mock.patch(
                        "legolizer.providers.revise_program",
                        return_value={
                            "program": program,
                            "satisfied": False,
                        },
                    ) as review,
                ):
                    result = cli._refine(
                        argparse.Namespace(
                            iterations=1,
                            program=Path("input.json") if imported else None,
                            repair_supports=False,
                            description="tower",
                        ),
                        output,
                        program,
                        None,
                    )
                review.assert_called_once()
                self.assertIn("UNATTACHED", review.call_args.args[-1])
                self.assertEqual(bool(result[-1]), imported)
                self.assertEqual((output / "pruning.json").exists(), not imported)
                if not imported:
                    self.assertEqual(
                        json.loads((output / "program.before-pruning.json").read_text()), program
                    )
                    removed = json.loads((output / "pruning.json").read_text())["removed"]
                    self.assertEqual([p["part"] for p in removed], ["3024"])
                    self.assertIn("Removed 1", (output / "design.log").read_text())

    def test_invalid_initial_program_uses_review_budget_and_keeps_failed_input(self):
        invalid = arch_program(gap=0)
        invalid["pieces"].append(dict(invalid["pieces"][0]))
        valid = arch_program(gap=0)
        with tempfile.TemporaryDirectory() as directory:

            def preview(model, cells, placements, loose, output, name):
                output.touch()

            with (
                mock.patch.object(cli, "_render_build_preview", side_effect=preview) as render,
                mock.patch(
                    "legolizer.providers.revise_invalid_program", return_value={"program": valid}
                ) as repair,
                mock.patch("legolizer.providers.revise_program") as review,
            ):
                result = cli._refine(
                    argparse.Namespace(iterations=1, program=None, description="arch"),
                    Path(directory),
                    invalid,
                    None,
                )
            self.assertEqual(result[-1], [])
            self.assertEqual(json.loads((Path(directory) / "program.v0.json").read_text()), invalid)
            self.assertIn("overlaps", repair.call_args.args[2])
            repair.assert_called_once()
            render.assert_called_once()
            review.assert_not_called()

    def test_invalid_program_stops_at_review_limit_without_rendering(self):
        invalid = arch_program(gap=0)
        invalid["pieces"].append(dict(invalid["pieces"][0]))
        for rounds in (0, 2):
            with self.subTest(rounds=rounds), tempfile.TemporaryDirectory() as directory:
                with (
                    mock.patch.object(cli, "_render_build_preview") as render,
                    mock.patch(
                        "legolizer.providers.revise_invalid_program",
                        return_value={"program": invalid},
                    ) as repair,
                    self.assertRaisesRegex(ValueError, "overlaps"),
                ):
                    cli._refine(
                        argparse.Namespace(iterations=rounds, program=None, description="arch"),
                        Path(directory),
                        invalid,
                        None,
                    )
                self.assertEqual(repair.call_count, rounds)
                self.assertEqual(len(list(Path(directory).glob("program.v*.json"))), rounds + 1)
                render.assert_not_called()

    def test_invalid_last_review_keeps_the_previous_valid_program(self):
        valid = arch_program(gap=0)
        invalid = copy.deepcopy(valid)
        invalid["pieces"].append(dict(invalid["pieces"][0]))
        with tempfile.TemporaryDirectory() as directory:

            def preview(model, cells, placements, loose, output, name):
                output.touch()

            with (
                mock.patch.object(cli, "_render_build_preview", side_effect=preview),
                mock.patch(
                    "legolizer.providers.revise_program",
                    return_value={"program": invalid, "satisfied": False},
                ),
                mock.patch("legolizer.providers.revise_invalid_program") as repair,
            ):
                result = cli._refine(
                    argparse.Namespace(iterations=1, program=None, description="arch"),
                    Path(directory),
                    valid,
                    None,
                )
            self.assertEqual(result[0], valid)
            self.assertEqual(result[-1], [])
            repair.assert_not_called()

    def test_rotated_arch_supports_preserve_opening_and_source_program(self):
        for rotation in (0, 90, 180, 270):
            for raised in (0, 10):
                with self.subTest(rotation=rotation, raised=raised):
                    program = arch_program(rotation, raised=raised)
                    original = copy.deepcopy(program)
                    supported = propose(program)
                    self.assertEqual(program, original)
                    self.assertEqual(len(supported["parts"]), 3)
                    voxels = voxelize_program(supported)
                    placed, loose = pack(parse_model(voxel_document(voxels.cells, voxels.pieces)))
                    self.assertEqual(loose, [])
                    self.assertIn(voxels.pieces[0], placed)
                    for offset in (1, 2):
                        x, y = (offset, 0) if rotation % 180 == 0 else (0, offset)
                        for z in range(1, 5):
                            self.assertNotIn((x, y, z), voxels.cells)

    def test_large_gaps_and_tile_tops_are_not_filled(self):
        self.assertIsNone(propose(arch_program(gap=7)))
        program = arch_program(gap=1)
        program["pieces"].append(dict(part="98138", x=0, y=0, z=1, color=71, rotation=0))
        self.assertIsNone(propose(program))

    def test_already_supported_piece_needs_no_change(self):
        self.assertIsNone(propose(arch_program(gap=0)))

    def test_support_columns_are_capped(self):
        program = arch_program()
        program["size"][0] = 10
        program["parts"][0]["center"][0] = 5
        program["parts"][0]["size"][0] = 10
        program["pieces"] = [
            dict(part="6141", x=x, y=0, z=2, color=19, rotation=0) for x in range(10)
        ]
        self.assertEqual(len(propose(program)["parts"]), 9)

    def test_refinement_repairs_generated_program_but_preserves_imports(self):
        for imported in (False, True):
            with self.subTest(imported=imported), tempfile.TemporaryDirectory() as directory:
                args = argparse.Namespace(
                    iterations=0,
                    program=Path("input.json") if imported else None,
                    description="arch",
                )

                def preview(model, cells, placements, loose, output, name):
                    output.touch()

                with mock.patch.object(cli, "_render_build_preview", side_effect=preview):
                    program, document, model, placed, loose = cli._refine(
                        args, Path(directory), arch_program(), None
                    )
                self.assertEqual(bool(loose), imported)
                self.assertEqual(len(program["parts"]), 1 if imported else 3)
                self.assertEqual(parse_model(document), model)
                self.assertTrue((Path(directory) / "preview.png").exists())


class SavedGenerationRecoveryTests(unittest.TestCase):
    def test_resume_uses_saved_program_without_provider_requests(self):
        for saved_program in (False, True):
            with (
                self.subTest(saved_program=saved_program),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                (root / "jobs").mkdir()
                output = root / "models" / "example"
                output.mkdir(parents=True)
                if saved_program:
                    (output / "program.json").write_text("{}")
                (output / "build-guide.pdf").write_bytes(b"pdf")
                job_path = root / "jobs" / "example.json"
                job_path.write_text(
                    json.dumps({"id": "example", "name": "arch", "description": "arch"})
                )
                with (
                    mock.patch.object(server, "ROOT", root),
                    mock.patch.object(cli, "build_command") as build,
                    mock.patch("legolizer.providers.generate_concept") as concept,
                    mock.patch("legolizer.providers.design_program") as design,
                    mock.patch.object(server.subprocess, "run"),
                    mock.patch.object(server, "_ldraw_dir", return_value=directory),
                    mock.patch.object(server, "_app_binary", return_value="renderer"),
                    mock.patch.object(server, "package_build", return_value={"id": "example"}),
                ):
                    server.generate("example", resume_assembly=True)
                args = build.call_args.args[0]
                self.assertTrue(args.repair_supports)
                self.assertTrue(args.prune_loose)
                self.assertEqual(args.program, output / "program.json" if saved_program else None)
                self.assertEqual(
                    args.fixture_json, None if saved_program else output / "model.json"
                )
                concept.assert_not_called()
                design.assert_not_called()
                self.assertEqual(json.loads(job_path.read_text())["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
