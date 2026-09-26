"""CLI orchestration with providers, renderers and the LDraw library mocked."""

import argparse
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from legolizer import cli, providers
from legolizer.ldraw import write_mpd
from legolizer.model import load_model, parse_model
from legolizer.shape import voxel_document, voxelize_program
from legolizer.solver import pack, solve


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
            mock.patch.object(providers, "design_program", _no_api),
            mock.patch.object(providers, "revise_program", _no_api),
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

    def test_review_rounds_use_the_latest_sound_program(self):
        revisions, progress = [], []

        def revise(description, program, preview, concept, report):
            revisions.append((program, preview.name, concept, report))
            return _design(YELLOW_TOWER)

        with (
            mock.patch.object(providers, "design_program", lambda d, c: _design(TOWER)),
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
            mock.patch.object(providers, "design_program", lambda d, c: _design(TOWER)),
            mock.patch.object(providers, "revise_program", revise),
        ):
            cli.build_command(self.build_args(iterations=2))
        self.assertEqual(len(reviews), 1)
        self.assertEqual(self.read_json("program.json"), TOWER)
        self.assertFalse((self.out / "program.v1.json").exists())

    def test_invalid_revision_keeps_the_last_valid_round(self):
        with (
            mock.patch.object(providers, "design_program", lambda d, c: _design(TOWER)),
            mock.patch.object(providers, "revise_program", lambda *a: _design(INVALID)),
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
            providers, "design_program", lambda d, c: designed.append(c) or _design(TOWER)
        ):
            cli.build_command(self.build_args(concept=concept, iterations=0))
        self.assertEqual(designed, [self.out / "concept.png"])
        self.assertEqual((self.out / "concept.png").read_bytes(), b"png")

    def test_text_builds_draw_a_concept_first(self):
        drawn = []
        with (
            mock.patch.object(providers, "generate_concept", lambda d, o: drawn.append((d, o))),
            mock.patch.object(providers, "design_program", lambda d, c: _design(TOWER)),
        ):
            cli.build_command(self.build_args(no_concept=False, iterations=0))
        self.assertEqual(drawn, [("a tower", self.out / "concept.png")])

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
            mock.patch.object(providers, "design_program", lambda d, c: _design(LIT_TOWER)),
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
