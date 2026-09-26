"""Server job orchestration with the providers and the design step mocked."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from legolizer import cli, providers, server


class ConceptPrefetchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "jobs").mkdir()
        patcher = mock.patch.object(server, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _job(self, job_id):
        job = {
            "id": job_id,
            "name": "mushroom",
            "inputType": "text",
            "sourceFile": None,
            "description": "a red mushroom",
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "buildId": None,
            "error": None,
        }
        (self.root / "jobs" / f"{job_id}.json").write_text(json.dumps(job), encoding="utf-8")

    def _read(self, job_id):
        return json.loads((self.root / "jobs" / f"{job_id}.json").read_text(encoding="utf-8"))

    def test_generate_reuses_the_concept_started_at_queue_time(self):
        self._job("j1")
        calls, release = [], threading.Event()

        def fake_concept(description, output):
            calls.append(description)
            release.wait(5)
            output.write_bytes(b"png")

        seen = []

        def fake_build(args):
            seen.append(args.concept.read_bytes())
            raise ValueError("stop after the design step")

        with (
            mock.patch.object(providers, "generate_concept", fake_concept),
            mock.patch.object(cli, "build_command", fake_build),
        ):
            future = server.start_concept("j1", "a red mushroom")
            self.assertIs(server.start_concept("j1", "a red mushroom"), future)
            worker = threading.Thread(target=server.generate, args=("j1",))
            worker.start()
            release.set()
            worker.join(10)
        self.assertEqual(calls, ["a red mushroom"])
        self.assertEqual(seen, [b"png"])
        self.assertNotIn("j1", server.CONCEPTS)
        self.assertIn("stop after the design step", self._read("j1")["error"]["message"])

    def test_concept_failure_fails_the_job_during_views(self):
        self._job("j2")

        def broken_concept(description, output):
            raise RuntimeError("image service down")

        with (
            mock.patch.object(providers, "generate_concept", broken_concept),
            mock.patch.object(cli, "build_command") as build,
        ):
            server.start_concept("j2", "a red mushroom")
            server.generate("j2")
        build.assert_not_called()
        job = self._read("j2")
        self.assertEqual((job["status"], job["error"]["code"]), ("failed", "generation_failed"))
        self.assertIn("during views", job["error"]["message"])
        self.assertNotIn("j2", server.CONCEPTS)


if __name__ == "__main__":
    unittest.main()
