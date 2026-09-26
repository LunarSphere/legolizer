"""Server job orchestration with the providers and the design step mocked."""

import contextlib
import http.client
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from legolizer import cli, providers, server
from legolizer.catalog import PART_BY_CODE
from legolizer.ldraw import write_mpd
from legolizer.model import Placement
from legolizer.storage import AwsStore
from test_storage import aws_store

REPO = Path(__file__).resolve().parents[1]


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


class QuietHandler(server.Handler):
    def log_message(self, *args):
        pass


class RemoteBackendTests(unittest.TestCase):
    """LEGOLIZER_BACKEND=aws: shared DynamoDB queue and S3 artifacts (moto), renderers mocked."""

    def setUp(self):
        self.store = aws_store(self)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.submitted = []
        for patch in (
            mock.patch.object(server, "ROOT", self.root),
            mock.patch.object(server, "REMOTE", self.store),
            mock.patch.object(server, "setup_problem", lambda *needs, **flags: None),
            mock.patch.object(server.WORKER, "submit", lambda *a: self.submitted.append(a)),
            mock.patch.dict(
                os.environ,
                {
                    "LEGOLIZER_PROGRAM_JOBS": "1",
                    "LEGOLIZER_ALLOWED_HOSTS": "*.example.com",
                    "LEGOLIZER_ALLOWED_ORIGINS": "https://*.vercel.app",
                },
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, body=None, headers=None, key="k1"):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port)
        self.addCleanup(connection.close)
        headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
            headers["Idempotency-Key"] = key
        connection.request(method, path, data, headers)
        response = connection.getresponse()
        payload = response.read()
        content_type = response.getheader("Content-Type", "")
        return response, json.loads(payload) if "json" in content_type else payload

    def submit_program(self, key="k1"):
        program = {"name": "Tower", "parts": [{"shape": "box", "min": [0, 0, 0], "max": [2, 2, 1]}]}
        response, job = self.request("POST", "/api/v1/builds", {"program": program}, key=key)
        self.assertEqual(response.status, 202, job)
        return job

    def fake_pipeline(self, seen):
        def build(args):
            seen.append(json.loads(args.program.read_text()))
            time.sleep(0.05)
            brick = Placement(PART_BY_CODE["3001"], 0, 0, 0, 4, 4, 2)
            write_mpd(None, [brick], args.out / "model.mpd")

        def export(command, **kwargs):
            Path(command[-2]).write_bytes(b"%PDF")
            return mock.Mock(wait=lambda timeout: 0, poll=lambda: 0)

        def render(command, **kwargs):
            Path(command[-1]).write_bytes(b"png")

        def package(output, _out, _library, build_id, name, description, prefix):
            return {"id": build_id, "name": name, "assets": {"instructions": f"{prefix}/x"}}

        stack = contextlib.ExitStack()
        for patch in (
            mock.patch.object(cli, "build_command", build),
            mock.patch.object(server, "_ldraw_dir", lambda: str(self.root)),
            mock.patch.object(server.subprocess, "Popen", export),
            mock.patch.object(server.subprocess, "run", render),
            mock.patch.object(server, "package_build", package),
            mock.patch.object(server, "HEARTBEAT_SECONDS", 0.01),
        ):
            stack.enter_context(patch)
        return stack

    def test_program_job_runs_through_the_shared_queue_and_serves_s3_assets(self):
        job = self.submit_program()
        self.assertEqual((job["inputType"], job["name"]), ("program", "Tower"))
        self.assertEqual(self.submitted, [])
        self.assertEqual(self.request("GET", f"/api/v1/jobs/{job['id']}")[1]["status"], "queued")

        seen = []
        with self.fake_pipeline(seen):
            with mock.patch.object(self.store, "touch", wraps=self.store.touch) as touch:
                self.assertTrue(server.work_once("worker-a"))
            self.assertFalse(server.work_once("worker-b"))
        touch.assert_called()
        self.assertEqual(seen[0]["name"], "Tower")
        done = self.store.job(job["id"])
        self.assertEqual((done["status"], done["buildId"]), ("succeeded", job["id"]), done)

        _, page = self.request("GET", "/api/v1/builds?limit=5")
        self.assertEqual([b["id"] for b in page["items"]], [job["id"]])
        response, _ = self.request("GET", f"/api/v1/assets/{job['id']}/build-guide.pdf")
        self.assertEqual(response.status, 302)
        self.assertIn(f"builds/{job['id']}/build-guide.pdf", response.getheader("Location"))
        for path in (
            f"/api/v1/assets/{job['id']}/secrets.txt",
            "/api/v1/assets/missing/render.png",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0].status, 404)
        self.assertEqual(self.request("GET", f"/api/v1/builds/{job['id']}")[1]["name"], "Tower")
        self.assertEqual(self.request("GET", "/api/v1/builds/missing/parts")[0].status, 404)
        self.assertEqual(self.request("GET", "/api/v1/builds?cursor=bad")[0].status, 400)

    def test_queue_cap_and_disabled_program_jobs(self):
        with mock.patch.dict(os.environ, {"LEGOLIZER_MAX_PENDING": "2"}):
            self.submit_program("a")
            self.submit_program("b")
            response, error = self.request("POST", "/api/v1/builds", {"program": {}}, key="c")
            self.assertEqual(response.status, 429)
            self.assertIn("2 builds", error["message"])
        with mock.patch.dict(os.environ, {"LEGOLIZER_PROGRAM_JOBS": "0"}):
            response, error = self.request("POST", "/api/v1/builds", {"program": {}}, key="d")
        self.assertEqual((response.status, error["code"]), (403, "program_disabled"))
        body = {"program": {}, "image": "data:image/png;base64,AA=="}
        self.assertEqual(self.request("POST", "/api/v1/builds", body, key="e")[0].status, 400)

    def test_health_and_configured_hosts_and_origins(self):
        response, health = self.request("GET", "/api/v1/health", headers={"Host": "10.0.0.5"})
        self.assertEqual((response.status, health["backend"]), (200, "aws"))
        allowed = {"Host": "api.example.com", "Origin": "https://legolizer.vercel.app"}
        response, _ = self.request("GET", "/api/v1/jobs", headers=allowed)
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.getheader("Access-Control-Allow-Origin"), "https://legolizer.vercel.app"
        )
        for headers in (
            {"Host": "api.example.com", "Origin": "https://evil.test"},
            {"Host": "evil.test"},
        ):
            with self.subTest(headers=headers):
                self.assertEqual(
                    self.request("GET", "/api/v1/jobs", headers=headers)[0].status, 403
                )

    def test_refinement_fetches_the_parent_from_s3(self):
        parent = self.root / "published" / "parent"
        parent.mkdir(parents=True)
        brick = Placement(PART_BY_CODE["3001"], 0, 0, 0, 4, 4, 2)
        write_mpd(None, [brick], parent / "model.mpd")
        self.store.publish("parent", parent, {"id": "parent", "name": "Castle"})
        response, job = self.request(
            "POST", "/api/v1/builds/parent/refinements", {"prompt": "add a flag"}
        )
        self.assertEqual((response.status, job["name"]), (202, "Castle (refined)"))
        self.assertTrue((self.root / "models" / "parent" / "model.mpd").is_file())
        self.assertEqual(self.store.job(job["id"])["status"], "queued")

    def test_worker_survives_errors_and_waits_only_when_idle(self):
        class Stop(Exception):
            pass

        with (
            mock.patch.object(server, "work_once", side_effect=[RuntimeError("x"), True, False]),
            mock.patch.object(server.time, "sleep", side_effect=[None, Stop]) as sleep,
            self.assertRaises(Stop),
        ):
            server.work("worker-a")
        self.assertEqual(sleep.call_count, 2)

    def test_worker_reports_missing_setup_instead_of_running(self):
        job = self.submit_program()
        with mock.patch.object(server, "setup_problem", lambda *needs: "Install LDView"):
            self.assertTrue(server.work_once("worker-a"))
        failed = self.store.job(job["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"], {"code": "setup_required", "message": "Install LDView"})

    def test_queued_jobs_start_one_on_demand_worker(self):
        env = {
            "LEGOLIZER_WORKER_CLUSTER": "legolizer",
            "LEGOLIZER_WORKER_TASK_DEFINITION": "worker:1",
            "LEGOLIZER_WORKER_SUBNETS": "subnet-a, subnet-b",
            "LEGOLIZER_WORKER_SECURITY_GROUPS": "sg-1",
        }
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(self.store, "run_worker_task", return_value="arn") as run,
        ):
            self.submit_program("a")
            self.submit_program("b")
            self.request("GET", "/api/v1/jobs")
            run.assert_called_once_with("legolizer", "worker:1", ["subnet-a", "subnet-b"], ["sg-1"])

            self.store.release_worker("starting")
            run.side_effect = RuntimeError("no capacity")
            self.request("GET", "/api/v1/jobs")
            self.assertEqual(run.call_count, 2)
            self.assertTrue(self.store.reserve_worker_start(300))

    def test_no_worker_is_started_without_a_cluster(self):
        with mock.patch.object(self.store, "run_worker_task") as run:
            self.submit_program()
        run.assert_not_called()
        self.assertTrue(self.store.reserve_worker_start(300))

    def test_idle_worker_exits_and_releases_its_lease(self):
        with mock.patch.dict(os.environ, {"LEGOLIZER_POLL_SECONDS": "0.001"}):
            server.work("worker-a", idle_exit=0.01)
        rounds = []

        def work(owner, idle_exit):
            rounds.append(owner)
            if len(rounds) == 1:
                self.submit_program()
            else:
                self.store.update_job(self.store.jobs()[0]["id"], status="succeeded")

        with mock.patch.object(server, "work", work):
            server.run_workers("host", 1, idle_exit=1)
        self.assertEqual(rounds, ["host-0", "host-0"])
        self.assertTrue(self.store.acquire_worker("next"))

    def test_idle_worker_leaves_new_jobs_to_a_freshly_started_task(self):
        release = self.store.release_worker

        def release_then_api_starts_worker(owner):
            release(owner)
            self.store.reserve_worker_start(300)

        with (
            mock.patch.object(server, "work", lambda owner, idle_exit: self.submit_program()),
            mock.patch.object(self.store, "release_worker", release_then_api_starts_worker),
        ):
            server.run_workers("host", 1, idle_exit=1)
        lease = self.store.table.get_item(Key=self.store.WORKER)["Item"]
        self.assertEqual(lease["owner"], "starting")

    def test_worker_lease_is_renewed_while_jobs_run(self):
        with (
            mock.patch.object(server, "HEARTBEAT_SECONDS", 0.01),
            mock.patch.object(server, "work", lambda owner, idle_exit: time.sleep(0.1)),
            mock.patch.object(self.store, "hold_worker", wraps=self.store.hold_worker) as hold,
        ):
            server.run_workers("host", 1, idle_exit=1)
        self.assertGreater(hold.call_count, 2)

    def test_vercel_entry_point_serves_the_handler_from_the_shared_store(self):
        env = {
            "LEGOLIZER_BUCKET": "assets",
            "LEGOLIZER_TABLE": "legolizer",
            "VERCEL_PROJECT_PRODUCTION_URL": "legolizer.vercel.app",
            "VERCEL_URL": "legolizer-abc123.vercel.app",
        }
        with mock.patch.dict(os.environ, env):
            os.environ.pop("LEGOLIZER_ALLOWED_HOSTS", None)
            os.environ.pop("LEGOLIZER_ALLOWED_ORIGINS", None)
            spec = importlib.util.spec_from_file_location("vercel_api", REPO / "api" / "index.py")
            entry = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(entry)
            self.assertTrue(issubclass(entry.handler, server.Handler))
            self.assertIsInstance(server.REMOTE, AwsStore)
            self.assertTrue(server.host_allowed("legolizer-abc123.vercel.app"))
            self.assertTrue(server.origin_allowed("https://legolizer.vercel.app"))
            self.assertFalse(server.origin_allowed("https://other.vercel.app"))
        self.assertIsNotNone(self.store.build("robot-corrected"))

    def test_post_routes_ignore_the_query_string_added_by_vercel_rewrites(self):
        response, job = self.request("POST", "/api/v1/builds?path=builds", {"program": {}})
        self.assertEqual(response.status, 202, job)
        response, _ = self.request("POST", "/api/v1/nothing?path=nothing", {"program": {}})
        self.assertEqual(response.status, 404)

    def test_initialize_seeds_the_demo_robot_without_touching_running_jobs(self):
        from test_storage import job

        self.store.create_job(job("elsewhere", status="running"))
        server.initialize()
        self.assertEqual(self.store.build("robot-corrected")["id"], "robot-corrected")
        self.assertIsNotNone(self.store.asset("robot-corrected", "packed.mpd"))
        self.assertEqual(self.store.job("elsewhere")["status"], "running")


if __name__ == "__main__":
    unittest.main()
