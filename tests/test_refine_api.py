import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from legolizer import providers, server
from legolizer.catalog import PART_BY_CODE
from legolizer.ldraw import write_mpd
from legolizer.model import Placement


class QuietHandler(server.Handler):
    def log_message(self, *args):
        pass


class RefineApiTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "jobs").mkdir()
        parent = self.root / "models" / "parent"
        parent.mkdir(parents=True)
        (parent / "build.json").write_text(
            json.dumps({"name": "Castle", "description": "a castle"}), encoding="utf-8"
        )
        brick = Placement(PART_BY_CODE["3001"], 0, 0, 0, 4, 4, 2)
        write_mpd(None, [brick], parent / "model.mpd")
        self.submitted = []
        for patch in (
            mock.patch.object(server, "ROOT", self.root),
            mock.patch.object(server, "setup_problem", lambda needs_concept: None),
            mock.patch.object(server.WORKER, "submit", lambda *a: self.submitted.append(a)),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def post(self, path, body, key="k1", content_type="application/json"):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port)
        self.addCleanup(connection.close)
        data = json.dumps(body).encode()
        headers = {"Content-Type": content_type}
        if key:
            headers["Idempotency-Key"] = key
        connection.request("POST", path, data, headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def test_refinement_is_queued_with_its_selection(self):
        body = {"prompt": "add a flag", "selection": [{"min": [0, 0, 0], "max": [1, 1, 2]}]}
        status, job = self.post("/api/v1/builds/parent/refinements", body)
        self.assertEqual(status, 202)
        self.assertEqual((job["inputType"], job["parentId"]), ("refine", "parent"))
        self.assertEqual(job["name"], "Castle (refined)")
        saved = json.loads((self.root / "jobs" / f"{job['id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["selection"], body["selection"])
        self.assertEqual(saved["parentDescription"], "a castle")
        self.assertEqual(self.submitted, [(server.generate, job["id"])])

        status, again = self.post("/api/v1/builds/parent/refinements", body)
        self.assertEqual((status, again["id"]), (202, job["id"]))
        status, _ = self.post("/api/v1/builds/parent/refinements", {"prompt": "other"})
        self.assertEqual(status, 409)
        self.assertEqual(len(self.submitted), 1)

    def test_refinement_rejects_bad_requests(self):
        path = "/api/v1/builds/parent/refinements"
        self.assertEqual(self.post("/api/v1/builds/missing/refinements", {})[0], 404)
        for body in (
            {"prompt": ""},
            {"prompt": "x", "extra": 1},
            {"prompt": "x", "name": 5},
            {"prompt": "x", "selection": [{"min": [0, 0, 0]}]},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.post(path, body)[0], 400)
        self.assertEqual(self.post(path, {"prompt": "x"}, key="")[0], 400)
        self.assertEqual(self.post(path, {"prompt": "x"}, content_type="text/plain")[0], 400)
        (self.root / "models" / "parent" / "model.mpd").write_text(
            "1 4 0 0 0 1 0 0 0 1 9999.dat\n", encoding="utf-8"
        )
        status, error = self.post(path, {"prompt": "x"})
        self.assertEqual(status, 400)
        self.assertIn("cannot rebuild", error["message"])
        self.assertEqual(self.submitted, [])

    def _refine_job(self):
        job = {
            "id": "child",
            "name": "Castle (refined)",
            "inputType": "refine",
            "sourceFile": None,
            "description": "add a flag",
            "parentId": "parent",
            "parentName": "Castle",
            "parentDescription": "a castle",
            "selection": [{"min": [0, 0, 0], "max": [1, 1, 2]}],
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "buildId": None,
            "error": None,
        }
        server.write_json(self.root / "jobs" / "child.json", job)
        return self.root / "models" / "child"

    def test_generate_runs_refinement_and_publishes_metadata(self):
        output = self._refine_job()
        calls = []

        def refine(args):
            calls.append(args)
            args.progress(1, 2)
            (args.out / "refine.json").write_text(
                json.dumps(
                    {"request": "add a flag", "selection": [], "keptPieces": 3, "rebuilt": [{}]}
                ),
                encoding="utf-8",
            )

        def export(*args, **kwargs):
            (output / "build-guide.pdf").write_bytes(b"%PDF")
            return mock.Mock(wait=lambda timeout: 0, poll=lambda: 0)

        with (
            mock.patch("legolizer.cli.refine_command", refine),
            mock.patch.object(server, "_ldraw_dir", lambda: str(self.root)),
            mock.patch.object(server.subprocess, "Popen", export),
            mock.patch.object(server.subprocess, "run"),
            mock.patch.object(server, "package_build", lambda *a: {"id": "child"}),
        ):
            server.generate("child")
        job = json.loads((self.root / "jobs" / "child.json").read_text(encoding="utf-8"))
        self.assertEqual(job["status"], "succeeded", job["error"])
        self.assertEqual(calls[0].source, self.root / "models" / "parent")
        self.assertEqual(calls[0].selection, [((0, 0, 0), (1, 1, 2))])
        build = json.loads((output / "build.json").read_text(encoding="utf-8"))
        self.assertEqual(
            build["refinement"],
            {
                "parentId": "parent",
                "prompt": "add a flag",
                "selection": [],
                "keptPieces": 3,
                "rebuiltPieces": 1,
            },
        )

    def test_generate_reports_design_errors(self):
        self._refine_job()

        def refine(args):
            raise ValueError("Every candidate edit was invalid.")

        with mock.patch("legolizer.cli.refine_command", refine):
            server.generate("child")
        job = json.loads((self.root / "jobs" / "child.json").read_text(encoding="utf-8"))
        self.assertEqual(job["status"], "failed")
        self.assertIn("Every candidate edit was invalid.", job["error"]["message"])


class SetupProblemTests(unittest.TestCase):
    def test_reports_missing_design_key_and_concept_problem(self):
        with mock.patch.dict(server.os.environ, {}, clear=True):
            self.assertIn("OPENAI_API_KEY", server.setup_problem(False))
        with (
            mock.patch.dict(server.os.environ, {"OPENAI_API_KEY": "x"}, clear=True),
            mock.patch.object(server, "image_setup_problem", lambda: "No image key"),
        ):
            self.assertIn("No image key", server.setup_problem(True))
        with (
            mock.patch.dict(server.os.environ, {"OPENAI_API_KEY": "x"}, clear=True),
            mock.patch.object(server, "_ldraw_dir", lambda: None),
        ):
            self.assertIn("LDRAW_LIBRARY_PATH", server.setup_problem(False))


class InfillPromptTests(unittest.TestCase):
    def test_prompts_describe_the_zone_and_the_request(self):
        asked = []
        with mock.patch.object(providers, "_ask_json", lambda content: asked.append(content)):
            preview = Path("before.png")
            providers.design_infill(
                "castle",
                "add a flag",
                "Selected bricks: X 0..1",
                [4, 4, 2.4],
                preview,
                "report",
                {"parts": []},
                None,
            )
            providers.revise_infill(
                "castle",
                "add a flag",
                None,
                [4, 4, 2.4],
                {"parts": []},
                preview,
                "report",
                Path("concept.png"),
            )
        design, revise = ("\n".join(map(str, content)) for content in asked)
        self.assertIn("INFILL EDIT", design)
        self.assertIn("Selected bricks: X 0..1", design)
        self.assertIn("Requested change: add a flag", design)
        self.assertIn("WHOLE-MODEL EDIT", revise)
        self.assertIn("concept.png", revise)


if __name__ == "__main__":
    unittest.main()
