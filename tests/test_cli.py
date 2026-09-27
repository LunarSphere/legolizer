"""CLI orchestration, generated support repairs and offline recovery of saved jobs.

Providers, renderers and the LDraw library are mocked.
"""

import argparse
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from legolizer import cli, providers, server
from legolizer.ldraw import write_mpd
from legolizer.model import load_model, parse_model
from legolizer.shape import voxel_document, voxelize_program
from legolizer.solver import disconnected_placements, pack, solve


def _box(name, center, size, color, mode="solid"):
    return {
        "name": name,
        "shape": "box",
        "mode": mode,
        "center": center,
        "size": size,
        "axis": "z",
        "taper": 1,
        "color": color,
        "mirror": False,
    }


def _program(*parts):
    return {"name": "tower", "size": [4, 2, 6], "pieces": [], "parts": list(parts)}


BASE = _box("base", [2, 1, 0.6], [4, 2, 1.2], 4)
TOWER = _program(BASE, _box("top", [2, 1, 1.8], [4, 2, 1.2], 1))
YELLOW_TOWER = _program(BASE, _box("top", [2, 1, 1.8], [4, 2, 1.2], 14))
FLOATING = _program(BASE, _box("balloon", [2, 1, 4.8], [2, 2, 1.2], 15))
INVALID = _program({**BASE, "shape": "blob"})
LIT_TOWER = {
    **TOWER,
    "pieces": [{"part": "6141", "x": 0, "y": 0, "z": 6, "color": 14, "rotation": 0}],
}


def _design(program, satisfied=False):
    return {"assessment": "looks fine", "satisfied": satisfied, "program": program}


def _no_api(*args):
    raise AssertionError("tests must not call providers")


class CliTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.out = self.root / "out"
        library = self.root / "ldraw"
        library.mkdir()
        (library / "parts.lst").write_text("", encoding="utf-8")
        self.issues = []
        self.read_model = mock.MagicMock()
        for patch in (
            mock.patch("sys.stdout", new_callable=io.StringIO),
            mock.patch.object(cli, "_ldraw_dir", lambda: str(library)),
            mock.patch("ldraw.parts.Parts"),
            mock.patch("ldraw.validation.iter_ldr_issues", lambda *a: iter(self.issues)),
            mock.patch("ldraw.read_model", self.read_model),
            mock.patch.object(providers, "generate_concept", _no_api),
            mock.patch.object(
                providers, "estimate_size", lambda *a, **k: {"size": 16, "reason": "test"}
            ),
            mock.patch.object(providers, "design_program", _no_api),
            mock.patch.object(providers, "revise_program", _no_api),
            mock.patch.object(providers, "revise_invalid_program", _no_api),
            mock.patch.object(providers, "design_infill", _no_api),
            mock.patch.object(providers, "revise_infill", _no_api),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def build_args(self, **overrides):
        values = dict(
            out=self.out,
            description="a tower",
            concept=None,
            no_concept=True,
            program=None,
            iterations=None,
            fixture_json=None,
            max_size=16,
        )
        return argparse.Namespace(**{**values, **overrides})

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def read_json(self, name):
        return json.loads((self.out / name).read_text(encoding="utf-8"))


class BuildCommandTests(CliTestCase):
    def test_fixture_json_writes_every_artifact_offline(self):
        document = voxel_document(voxelize_program(TOWER).cells)
        fixture = self.write_json("model.json", document)
        self.assertEqual(cli.build_command(self.build_args(fixture_json=fixture)), 0)
        for name in ("model.mpd", "parts.json", "preview.png"):
            self.assertTrue((self.out / name).is_file(), name)
        self.assertEqual(self.read_json("model.json"), document)
        self.assertEqual(sum(p["quantity"] for p in self.read_json("parts.json")["parts"]), 2)
        self.read_model.assert_called_once_with(self.out / "model.mpd")

    def test_saved_design_response_runs_without_review_rounds(self):
        program = self.write_json("design.json", _design(TOWER))
        self.assertEqual(cli.build_command(self.build_args(program=program)), 0)
        self.assertEqual(self.read_json("program.json"), TOWER)
        self.assertTrue((self.out / "program.v0.json").is_file())
        self.assertFalse((self.out / "program.v1.json").exists())
        self.assertIn("round 0 build report", (self.out / "design.log").read_text("utf-8"))

    def test_omitted_max_size_estimates_before_design(self):
        estimated = []

        with (
            mock.patch.object(
                providers,
                "estimate_size",
                lambda description, image=None: (
                    estimated.append((description, image)) or {"size": 10, "reason": "compact"}
                ),
            ),
            mock.patch.object(
                providers,
                "design_program",
                lambda d, c, size=16, category=None: self.assertIsNone(category) or _design(TOWER),
            ),
        ):
            cli.build_command(self.build_args(max_size=None, iterations=0))
        self.assertEqual(estimated, [("a tower", None)])
        self.assertEqual(self.read_json("size.json"), {"size": 10, "reason": "compact"})
        self.assertEqual(self.read_json("program.json"), TOWER)

    def test_review_rounds_use_the_latest_sound_program(self):
        revisions, progress = [], []

        def revise(description, program, preview, concept, report, max_size=16):
            revisions.append((program, preview.name, concept, report))
            return _design(YELLOW_TOWER)

        with (
            mock.patch.object(providers, "design_program", lambda d, c, *a: _design(TOWER)),
            mock.patch.object(providers, "revise_program", revise),
        ):
            cli.build_command(self.build_args(iterations=1, progress=lambda *a: progress.append(a)))
        self.assertEqual(progress, [(0, 2), (1, 2)])
        [(program, preview, concept, report)] = revisions
        self.assertEqual((program, preview, concept), (TOWER, "preview.v0.png", None))
        self.assertIn("Structure: every piece connects", report)
        self.assertEqual(self.read_json("program.json"), YELLOW_TOWER)
        log = (self.out / "design.log").read_text("utf-8")
        self.assertIn("== initial design ==\nlooks fine", log)
        self.assertIn("== round 0 review ==", log)

    def test_satisfied_reviewer_stops_early(self):
        reviews = []

        def revise(*args):
            reviews.append(args)
            return _design(YELLOW_TOWER, satisfied=True)

        with (
            mock.patch.object(providers, "design_program", lambda d, c, *a: _design(TOWER)),
            mock.patch.object(providers, "revise_program", revise),
        ):
            cli.build_command(self.build_args(iterations=2))
        self.assertEqual(len(reviews), 1)
        self.assertEqual(self.read_json("program.json"), TOWER)
        self.assertFalse((self.out / "program.v1.json").exists())

    def test_invalid_revision_keeps_the_last_valid_round(self):
        with (
            mock.patch.object(providers, "design_program", lambda d, c, *a: _design(TOWER)),
            mock.patch.object(providers, "revise_program", lambda *a: _design(INVALID)),
            mock.patch.object(providers, "revise_invalid_program", lambda *a: _design(INVALID)),
        ):
            cli.build_command(self.build_args(iterations=2))
        self.assertEqual(self.read_json("program.json"), TOWER)

    def test_invalid_first_program_is_a_value_error(self):
        program = self.write_json("program.json", INVALID)
        with self.assertRaises(ValueError):
            cli.build_command(self.build_args(program=program))

    def test_concept_inputs(self):
        with self.assertRaisesRegex(ValueError, "PNG, JPEG, WebP, or GIF"):
            cli.build_command(self.build_args(concept=self.root / "concept.bmp"))

        concept = self.root / "photo.png"
        concept.write_bytes(b"png")
        designed = []
        with mock.patch.object(
            providers, "design_program", lambda d, c, *a: designed.append(c) or _design(TOWER)
        ):
            cli.build_command(self.build_args(concept=concept, iterations=0))
        self.assertEqual(designed, [self.out / "concept.png"])
        self.assertEqual((self.out / "concept.png").read_bytes(), b"png")

    def test_text_builds_draw_a_concept_first(self):
        drawn = []
        with (
            mock.patch.object(providers, "generate_concept", lambda d, o: drawn.append((d, o))),
            mock.patch.object(providers, "design_program", lambda d, c, *a: _design(TOWER)),
        ):
            cli.build_command(self.build_args(no_concept=False, iterations=0))
        self.assertEqual(drawn, [("a tower", self.out / "concept.png")])

    def test_stylized_text_build_uses_the_brief_everywhere(self):
        brief = {
            "brief": "A stone tower with a red flag.",
            "palette": [71, 4],
            "expanded": "A stone tower with a red flag. Palette, most used first: grey, red.",
            "category": "building",
            "size": 20,
            "reason": "fits",
        }
        stylized, drawn, designed = [], [], []
        with (
            mock.patch.object(
                providers, "stylize_prompt", lambda d: stylized.append(d) or dict(brief)
            ),
            mock.patch.object(
                providers, "estimate_size", lambda *a: self.fail("brief already sized it")
            ),
            mock.patch.object(providers, "generate_concept", lambda d, o: drawn.append(d)),
            mock.patch.object(
                providers,
                "design_program",
                lambda d, c, size=16, category=None: (
                    designed.append((d, size, category)) or _design(TOWER)
                ),
            ),
        ):
            args = self.build_args(no_concept=False, iterations=0, max_size=None, stylize=True)
            cli.build_command(args)
            self.assertEqual(self.read_json("size.json"), {"size": 20, "reason": "fits"})
            cli.build_command(self.build_args(no_concept=False, iterations=0, stylize=True))
        self.assertEqual(stylized, ["a tower"])
        self.assertEqual(drawn, [brief["expanded"]] * 2)
        self.assertEqual(
            designed,
            [(brief["expanded"], 20, "building"), (brief["expanded"], 16, "building")],
        )
        self.assertEqual(self.read_json("brief.json"), {"original": "a tower", **brief})

    def test_stylize_skips_saved_programs_concepts_and_opt_outs(self):
        concept = self.root / "photo.png"
        concept.write_bytes(b"png")
        program = self.write_json("design.json", _design(TOWER))
        with (
            mock.patch.object(providers, "stylize_prompt", _no_api),
            mock.patch.object(providers, "design_program", lambda d, c, *a: _design(TOWER)),
        ):
            for overrides in (dict(program=program), dict(iterations=0, stylize=False)):
                with self.subTest(overrides=overrides):
                    cli.build_command(self.build_args(**{"stylize": True, **overrides}))
            seen = []
            argv = ["legolizer", "build", "a tower", "--concept", str(concept)]
            with (
                mock.patch("sys.argv", argv),
                mock.patch.object(cli, "load_dotenv"),
                mock.patch.object(cli, "build_command", lambda args: seen.append(args) or 0),
                self.assertRaises(SystemExit),
            ):
                cli.main()
        self.assertFalse(seen[0].stylize)
        self.assertFalse((self.out / "brief.json").exists())

    def test_server_prefetched_concept_still_designs_from_the_brief(self):
        self.out.mkdir()
        (self.out / "concept.png").write_bytes(b"png")
        brief = {
            "brief": "A stone tower.",
            "palette": [71],
            "expanded": "A stone tower. Palette, most used first: light bluish grey.",
            "category": "building",
            "size": 24,
            "reason": "fits",
        }
        self.write_json("out/brief.json", {"original": "a tower", **brief})
        designed = []
        with (
            mock.patch.object(providers, "stylize_prompt", _no_api),
            mock.patch.object(providers, "estimate_size", _no_api),
            mock.patch.object(
                providers,
                "design_program",
                lambda d, c, size=16, category=None: (
                    designed.append((d, c, size, category)) or _design(TOWER)
                ),
            ),
        ):
            cli.build_command(
                self.build_args(
                    concept=self.out / "concept.png", max_size=None, iterations=0, stylize=True
                )
            )
        self.assertEqual(designed, [(brief["expanded"], self.out / "concept.png", 24, "building")])

    def test_prepare_brief_reuses_a_brief_for_the_same_prompt(self):
        calls = []
        self.out.mkdir()
        with mock.patch.object(
            providers,
            "stylize_prompt",
            lambda d: calls.append(d) or {"brief": d, "palette": [], "expanded": d},
        ):
            first = cli.prepare_brief("a boat", self.out)
            self.assertEqual(cli.prepare_brief("a boat", self.out), first)
            cli.prepare_brief("a ship", self.out)
        self.assertEqual(calls, ["a boat", "a ship"])

    def test_report_mentions_specialty_pieces_only_when_present(self):
        for program, expected in ((TOWER, False), (LIT_TOWER, True)):
            voxelized = voxelize_program(program)
            model = parse_model(voxel_document(voxelized.cells, voxelized.pieces))
            placements, loose = pack(model)
            report = cli._build_report(voxelized, placements, loose)
            with self.subTest(pieces=expected):
                self.assertIn(f"{len(placements)} official pieces.", report)
                self.assertEqual("Specialty pieces" in report, expected)

    def test_review_rounds_keep_specialty_pieces(self):
        def render(source, output, timeout):
            output.write_bytes(b"png")

        with (
            mock.patch.object(providers, "design_program", lambda d, c, *a: _design(LIT_TOWER)),
            mock.patch.object(providers, "revise_program", lambda *a: _design(LIT_TOWER)),
            mock.patch.object(cli, "render_model", side_effect=render) as render_model,
        ):
            cli.build_command(self.build_args(iterations=1))
        self.assertEqual(render_model.call_count, 2)
        self.assertEqual(
            [p.part.code for p in load_model(self.out / "model.json").pieces], ["6141"]
        )
        self.assertIn(" 6141.dat", (self.out / "model.mpd").read_text(encoding="utf-8"))

    def test_unattached_pieces_are_reported_and_fail_the_build(self):
        voxelized = voxelize_program(FLOATING)
        placements, loose = pack(parse_model(voxel_document(voxelized.cells)))
        report = cli._build_report(voxelized, placements, loose)
        self.assertIn(f"UNATTACHED: {len(loose)} pieces", report)
        self.assertIn("- balloon: 12 cells", report)

        program = self.write_json("program.json", FLOATING)
        with self.assertRaisesRegex(RuntimeError, "not attached to the main build"):
            cli.build_command(self.build_args(program=program))
        self.assertTrue((self.out / "model.mpd").is_file())


class WriteBuildTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.out.mkdir()
        self.model = parse_model(voxel_document(voxelize_program(TOWER).cells))
        self.placements = solve(self.model)

    def test_library_validation_and_parse_failures(self):
        with mock.patch.object(cli, "_ldraw_dir", lambda: None):
            with self.assertRaisesRegex(RuntimeError, "LDRAW_LIBRARY_PATH"):
                cli._write_build(self.out, self.model, self.placements, [])
        self.issues = ["unknown part"]
        with self.assertRaisesRegex(RuntimeError, "validation failed"):
            cli._write_build(self.out, self.model, self.placements, [])
        self.issues = []
        self.read_model.side_effect = Exception("bad line")
        with self.assertRaisesRegex(RuntimeError, "could not parse generated MPD: bad line"):
            cli._write_build(self.out, self.model, self.placements, [])

    def test_specialty_models_preview_through_the_renderer(self):
        output = self.out / "preview.v0.png"
        with (
            mock.patch.object(cli, "write_mpd") as write,
            mock.patch.object(cli, "render_model") as render,
            mock.patch.object(cli, "render_preview") as preview,
        ):
            cli._render_build_preview(SimpleNamespace(pieces=(1,)), {}, [], [], output, "x")
            cli._render_build_preview(SimpleNamespace(pieces=()), {}, [], [], output, "x")
        write.assert_called_once_with(mock.ANY, [], self.out / "preview.v0.mpd")
        render.assert_called_once_with(self.out / "preview.v0.mpd", output, timeout=120)
        preview.assert_called_once()


class RefineCommandTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.source = self.root / "source"
        self.source.mkdir()
        model = parse_model(voxel_document(voxelize_program(TOWER).cells))
        write_mpd(model, solve(model), self.source / "model.mpd")
        patch = mock.patch.object(cli, "_write_build", lambda *a: 0)
        patch.start()
        self.addCleanup(patch.stop)

    def refine_args(self, **overrides):
        values = dict(
            source=self.source,
            out=self.out,
            request="make the top yellow",
            selection=[],
            description="tower",
            candidates=1,
            iterations=0,
        )
        return argparse.Namespace(**{**values, **overrides})

    def test_rejects_in_place_and_empty_requests(self):
        with self.assertRaisesRegex(ValueError, "new directory"):
            cli.refine_command(self.refine_args(out=self.source))
        with self.assertRaisesRegex(ValueError, "Describe the change"):
            cli.refine_command(self.refine_args(request="  "))

    def test_failed_and_invalid_candidates(self):
        def fail(*args):
            raise RuntimeError("no design key")

        with mock.patch.object(providers, "design_infill", fail):
            with self.assertRaisesRegex(RuntimeError, "no design key"):
                cli.refine_command(self.refine_args(candidates=2))
        with mock.patch.object(providers, "design_infill", lambda *a: _design({"parts": None})):
            with self.assertRaisesRegex(ValueError, "Every candidate edit was invalid"):
                cli.refine_command(self.refine_args())

    def test_edit_that_changes_nothing_is_rejected(self):
        same = _program(_box("repaint", [2, 1, 0.6], [4, 2, 1.2], 4, mode="paint"))
        with mock.patch.object(providers, "design_infill", lambda *a: _design(same)):
            with self.assertRaisesRegex(ValueError, "did not change the model"):
                cli.refine_command(self.refine_args())

    def test_review_replaces_a_candidate_that_changed_nothing(self):
        same = _program(_box("repaint", [2, 1, 0.6], [4, 2, 1.2], 4, mode="paint"))
        yellow = _program(_box("repaint", [2, 1, 1.8], [4, 2, 1.2], 14, mode="paint"))
        reviews = []

        def revise(*args):
            reviews.append(args)
            return _design(yellow)

        with (
            mock.patch.object(providers, "design_infill", lambda *a: _design(same)),
            mock.patch.object(providers, "revise_infill", revise),
        ):
            self.assertEqual(cli.refine_command(self.refine_args(iterations=1)), 0)
        self.assertEqual(len(reviews), 1)
        refinement = self.read_json("refine.json")
        self.assertEqual((refinement["chosen"], refinement["zone"]), ("r1", None))
        self.assertIn({"x": 0, "y": 0, "z": 3, "color": 14}, self.read_json("model.json")["voxels"])


class ArgumentTests(unittest.TestCase):
    def test_region_arguments(self):
        self.assertEqual(cli._parse_region_arg("0,0,0,1,1,2"), ((0, 0, 0), (1, 1, 2)))
        for text in ("0,0,0", "a,b,c,d,e,f", "2,0,0,1,1,2"):
            with self.subTest(text=text), self.assertRaises(argparse.ArgumentTypeError):
                cli._parse_region_arg(text)

    def test_main_maps_errors_to_exit_code_one(self):
        def run(render):
            argv = ["legolizer", "render", "model.mpd", "--out", "shot.png"]
            with (
                mock.patch("sys.argv", argv),
                mock.patch.object(cli, "load_dotenv"),
                mock.patch.object(cli, "render_model", render),
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
                self.assertRaises(SystemExit) as exit_,
            ):
                cli.main()
            return exit_.exception.code, stdout.getvalue(), stderr.getvalue()

        code, stdout, _ = run(lambda source, out: None)
        self.assertEqual((code, stdout.strip()), (0, "shot.png"))

        def missing(source, out):
            raise RuntimeError("Install LDView")

        code, _, stderr = run(missing)
        self.assertEqual((code, stderr.strip()), (1, "error: Install LDView"))


if __name__ == "__main__":
    unittest.main()


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
                            max_size=16,
                        ),
                        output,
                        program,
                        None,
                    )
                review.assert_called_once()
                self.assertIn("UNATTACHED", review.call_args.args[-2])
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
                    argparse.Namespace(iterations=1, program=None, description="arch", max_size=16),
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
                        argparse.Namespace(
                            iterations=rounds, program=None, description="arch", max_size=16
                        ),
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
                    argparse.Namespace(iterations=1, program=None, description="arch", max_size=16),
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
                    max_size=16,
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
                    mock.patch.object(server.subprocess, "Popen") as popen,
                    mock.patch.object(server, "_ldraw_dir", return_value=directory),
                    mock.patch.object(server, "_app_binary", return_value="renderer"),
                    mock.patch.object(server, "package_build", return_value={"id": "example"}),
                ):
                    popen.return_value.wait.return_value = 0
                    popen.return_value.poll.return_value = 0
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
