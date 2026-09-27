"""HTTP API, job lifecycle and startup, with the worker, CLI and renderers mocked."""

import base64
import contextlib
import http.client
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from PIL import Image

from legolizer import auth, cli, providers, reference, server
from legolizer.catalog import PART_BY_CODE
from legolizer.ldraw import write_mpd
from legolizer.model import Placement
from legolizer.storage import AwsStore
from test_storage import aws_store

REPO = Path(__file__).resolve().parents[1]

SETUP_PROBLEM = server.setup_problem


class QuietHandler(server.Handler):
    def log_message(self, *args):
        pass


def _png(size=(64, 48)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "jobs").mkdir()
        (self.root / "models").mkdir()
        self.submitted = []
        self.problem = None
        for patch in (
            mock.patch.object(server, "ROOT", self.root),
            mock.patch.object(
                server, "setup_problem", lambda needs_concept, needs_design=True: self.problem
            ),
            mock.patch.object(server.WORKER, "submit", lambda *a: self.submitted.append(a)),
            mock.patch.object(providers, "generate_concept", self.no_generation),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    @staticmethod
    def no_generation(*args):
        raise AssertionError("tests must not call providers")

    def add_build(self, build_id, mtime=None, **metadata):
        directory = self.root / "models" / build_id
        directory.mkdir(parents=True)
        server.write_json(directory / "build.json", {"id": build_id, "name": build_id, **metadata})
        server.write_json(directory / "parts.json", {"parts": [{"part_id": "3001"}]})
        (directory / "render.png").write_bytes(b"\x89PNG")
        if mtime is not None:
            os.utime(directory / "build.json", (mtime, mtime))
        return directory

    def add_job(self, job_id, **fields):
        job = {
            "id": job_id,
            "name": "Robot",
            "description": "a robot",
            "inputType": "text",
            "sourceFile": None,
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "buildId": None,
            "error": None,
            **fields,
        }
        server.write_json(self.root / "jobs" / f"{job_id}.json", job)
        return job

    def job(self, job_id):
        return server.read_json(self.root / "jobs" / f"{job_id}.json")


class LoopbackApiTestCase(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.concepts = []
        patch = mock.patch.object(server, "start_concept", lambda *a: self.concepts.append(a))
        patch.start()
        self.addCleanup(patch.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port)
        self.addCleanup(connection.close)
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        connection.request(method, path, data, headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def get(self, path, **headers):
        status, _, data = self.request("GET", path, headers=headers)
        return status, json.loads(data)

    def post(
        self, body, key="k1", path="/api/v1/builds", content_type="application/json", cookie=None
    ):
        headers = {"Content-Type": content_type}
        if key:
            headers["Idempotency-Key"] = key
        if cookie:
            headers["Cookie"] = cookie
        status, _, data = self.request("POST", path, body, headers)
        return status, json.loads(data)


class ApiTests(LoopbackApiTestCase):
    def test_builds_are_listed_newest_first_with_a_cursor(self):
        self.assertEqual(self.get("/api/v1/builds"), (200, {"items": [], "nextCursor": None}))
        for index, build_id in enumerate(("old", "mid", "new")):
            self.add_build(build_id, mtime=1_000_000 + index)
        status, page = self.get("/api/v1/builds?limit=2")
        self.assertEqual((status, [b["id"] for b in page["items"]]), (200, ["new", "mid"]))
        self.assertEqual(page["nextCursor"], "2")
        status, page = self.get("/api/v1/builds?cursor=2&limit=2")
        self.assertEqual(([b["id"] for b in page["items"]], page["nextCursor"]), (["old"], None))
        for query in ("limit=0", "limit=101", "cursor=-1", "limit=abc"):
            with self.subTest(query=query):
                self.assertEqual(self.get(f"/api/v1/builds?{query}")[0], 400)

    def test_build_and_parts_lookup(self):
        self.add_build("robot", description="a robot")
        self.assertEqual(self.get("/api/v1/builds/robot")[1]["description"], "a robot")
        self.assertEqual(self.get("/api/v1/builds/robot/parts")[1]["parts"][0]["part_id"], "3001")
        self.assertEqual(self.get("/api/v1/builds/missing")[0], 404)
        self.assertEqual(self.get("/api/v1/nothing")[0], 404)
        (self.root / "models" / "robot" / "parts.json").unlink()
        self.assertEqual(self.get("/api/v1/builds/robot/parts")[0], 404)

    def test_jobs_hide_idempotency_details(self):
        self.add_job("j1", key="secret", digest="abc")
        status, listing = self.get("/api/v1/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(listing["items"][0]["id"], "j1")
        self.assertNotIn("key", listing["items"][0])
        status, job = self.get("/api/v1/jobs/j1")
        self.assertEqual((status, job["inputType"], job["parentId"]), (200, "text", None))
        self.assertNotIn("digest", job)
        self.assertEqual(self.get("/api/v1/jobs/missing")[0], 404)

    def test_assets_are_allowlisted(self):
        directory = self.add_build("robot")
        origin = "http://localhost:5173"
        status, headers, data = self.request(
            "GET", "/api/v1/assets/robot/render.png", headers={"Origin": origin}
        )
        self.assertEqual((status, data), (200, b"\x89PNG"))
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Access-Control-Allow-Origin"], origin)
        (directory / "secret.txt").write_text("x", encoding="utf-8")
        for path in (
            "robot/build.json",
            "robot/secret.txt",
            "robot/model.mpd",
            "missing/render.png",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", f"/api/v1/assets/{path}")[0], 404)
        (directory / "build.json").unlink()
        self.assertEqual(self.request("GET", "/api/v1/assets/robot/render.png")[0], 404)

    def test_only_local_hosts_and_origins_are_served(self):
        for headers in ({"Host": "example.com"}, {"Origin": "http://example.com"}):
            for method in ("GET", "POST", "OPTIONS"):
                with self.subTest(method=method, headers=headers):
                    status, _, _ = self.request(method, "/api/v1/builds", b"{}", headers)
                    self.assertEqual(status, 403)
        status, headers, _ = self.request(
            "OPTIONS", "/api/v1/builds", headers={"Origin": "http://127.0.0.1:5173"}
        )
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://127.0.0.1:5173")
        self.assertIn("Idempotency-Key", headers["Access-Control-Allow-Headers"])
        _, headers, _ = self.request(
            "GET", "/api/v1/jobs", headers={"Origin": "http://localhost:8000"}
        )
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://localhost:8000")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_text_build_is_queued_once_per_key(self):
        body = {"description": "  a small red robot  "}
        status, job = self.post(body)
        self.assertEqual(status, 202)
        self.assertEqual(
            (job["status"], job["inputType"], job["name"], job["description"]),
            ("queued", "text", "a small red robot", "a small red robot"),
        )
        self.assertEqual(self.job(job["id"])["key"], "k1")
        self.assertEqual(self.submitted, [(server.generate, job["id"])])
        self.assertEqual(self.concepts, [(job["id"], "a small red robot", True)])
        self.assertEqual(self.post(body), (202, job))
        self.assertEqual(self.post({"description": "a boat"})[0], 409)
        self.assertEqual((len(self.submitted), len(self.concepts)), (1, 1))

    def test_stylize_flag_is_saved_and_validated(self):
        status, job = self.post({"description": "a cat", "stylize": False})
        self.assertEqual(status, 202)
        self.assertFalse(self.job(job["id"])["stylize"])
        self.assertEqual(self.concepts[-1], (job["id"], "a cat", False))
        status, _ = self.post({"description": "a cat", "stylize": "yes"}, key="k2")
        self.assertEqual(status, 400)
        status, job = self.post(
            {"image": {"mediaType": "image/png", "data": _png()}, "stylize": True}, key="k3"
        )
        self.assertFalse(self.job(job["id"])["stylize"])

    def test_image_build_saves_the_upload(self):
        status, job = self.post({"image": {"mediaType": "image/png", "data": _png()}})
        self.assertEqual(status, 202)
        self.assertEqual((job["inputType"], job["name"]), ("image", "Image-inspired set"))
        self.assertEqual(self.job(job["id"])["sourceFile"], "source.png")
        self.assertTrue((self.root / "models" / job["id"] / "source.png").is_file())
        self.assertEqual(self.concepts, [])

        status, error = self.post({"image": {"mediaType": "image/png", "data": "!"}}, key="k2")
        self.assertEqual(
            (status, error["message"]), (400, "The uploaded image is not valid base64.")
        )

    def test_build_requests_are_validated(self):
        cases = [
            ({"description": ""}, {}),
            ({"description": "x" * 2001}, {}),
            ({"description": "robot", "name": "x" * 81}, {}),
            ({"description": "robot", "name": 3}, {}),
            ({"description": "robot", "extra": True}, {}),
            (["robot"], {}),
            (b"{not json", {}),
            ({"description": "robot"}, {"key": ""}),
            ({"description": "robot"}, {"content_type": "text/plain"}),
        ]
        for body, options in cases:
            with self.subTest(body=body, options=options):
                self.assertEqual(self.post(body, **options)[0], 400)
        self.assertEqual(self.post({"description": "robot"}, path="/api/v1/other")[0], 404)
        self.assertEqual(self.submitted, [])

    def test_setup_problems_and_queue_limits_reject_new_jobs(self):
        self.problem = "Install LDView on the server before generating."
        self.assertEqual(self.post({"description": "robot"}), (503, mock.ANY))
        self.problem = None
        for index in range(3):
            self.add_job(f"busy{index}", status="running" if index else "queued")
        status, error = self.post({"description": "robot"})
        self.assertEqual(status, 429)
        self.assertIn("3 builds", error["message"])
        self.assertEqual(self.submitted, [])

    def test_without_auth_any_set_can_be_shared(self):
        self.add_build("robot")
        status, _, data = self.request(
            "PUT",
            "/api/v1/builds/robot/visibility",
            {"visibility": "public"},
            {"Content-Type": "application/json"},
        )
        self.assertEqual((status, json.loads(data)["authorName"]), (200, "Local workspace"))
        self.assertEqual([b["id"] for b in self.get("/api/v1/gallery")[1]["items"]], ["robot"])

    def test_without_auth_everyone_is_the_local_user(self):
        local = {"auth": "off", "googleClientId": None, "user": auth.LOCAL_USER}
        self.assertEqual(self.get("/api/v1/session"), (200, local))
        self.assertEqual(self.get("/api/v1/health")[1]["auth"], "off")
        status, error = self.post({"credential": "x"}, key=None, path="/api/v1/session")
        self.assertEqual((status, error["code"]), (400, "auth_disabled"))
        status, headers, data = self.request("DELETE", "/api/v1/session")
        self.assertEqual((status, json.loads(data)), (200, local))
        self.assertNotIn("Set-Cookie", headers)
        self.assertEqual(self.post({"description": "robot"})[0], 202)


class GoogleAuthTestCase(LoopbackApiTestCase):
    CLIENT = "client-123.apps.googleusercontent.com"
    PEOPLE = {"ada": "1", "bob": "2", "cy": "3"}

    def setUp(self):
        super().setUp()
        env = {
            "LEGOLIZER_AUTH": "google",
            "LEGOLIZER_GOOGLE_CLIENT_ID": self.CLIENT,
            "LEGOLIZER_ALLOWED_HOSTS": "studio.example.com",
        }
        for patch in (
            mock.patch.dict(os.environ, env),
            mock.patch.object(auth, "verify_google", self.verify),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    @classmethod
    def verify(cls, credential):
        if credential == "down":
            raise RuntimeError("Google sign-in is unavailable. Try again shortly.")
        if credential not in cls.PEOPLE:
            raise ValueError("Google sign-in could not be verified.")
        return {
            "sub": cls.PEOPLE[credential],
            "email": f"{credential}@example.com",
            "given_name": credential.title(),
            "picture": None,
        }

    def sign_in(self, credential="ada", **headers):
        status, response_headers, data = self.request(
            "POST",
            "/api/v1/session",
            {"credential": credential},
            {"Content-Type": "application/json", **headers},
        )
        return status, response_headers.get("Set-Cookie", ""), json.loads(data)

    def session(self, credential):
        return self.sign_in(credential)[1].split(";")[0]


class SignInTests(GoogleAuthTestCase):
    def test_signed_out_visitors_get_the_sign_in_configuration_and_cannot_generate(self):
        self.assertEqual(
            self.get("/api/v1/session"),
            (200, {"auth": "google", "googleClientId": self.CLIENT, "user": None}),
        )
        self.assertEqual(self.get("/api/v1/health")[1]["auth"], "google")
        for path in ("/api/v1/builds", "/api/v1/sizing", "/api/v1/builds/robot/refinements"):
            with self.subTest(path=path):
                status, error = self.post({"description": "robot"}, path=path)
                self.assertEqual((status, error["code"]), (401, "sign_in_required"))
        self.assertEqual(self.post({"description": "robot"}, path="/api/v1/other")[0], 404)
        self.assertEqual(self.submitted, [])

    def test_sign_in_sets_a_session_cookie_that_unlocks_generation(self):
        status, cookie, state = self.sign_in()
        ada = {"id": "google-1", "name": "Ada", "picture": None}
        self.assertEqual((status, state["user"]), (200, ada))
        self.assertRegex(cookie, r"^lgz_session=[\w-]{40,}; Path=/; HttpOnly; SameSite=Lax;")
        self.assertNotIn("Secure", cookie)
        saved = server.read_json(self.root / "users" / "google-1.json")
        self.assertEqual(saved["email"], "ada@example.com")
        session = cookie.split(";")[0]
        self.assertEqual(self.get("/api/v1/session", Cookie=session)[1]["user"], ada)
        self.assertEqual(self.post({"description": "robot"}, cookie=session)[0], 202)
        self.assertEqual(len(self.submitted), 1)
        self.assertIsNone(self.get("/api/v1/session", Cookie="lgz_session=forged")[1]["user"])

    def test_sign_out_revokes_the_session(self):
        session = self.sign_in()[1].split(";")[0]
        status, headers, data = self.request(
            "DELETE", "/api/v1/session", headers={"Cookie": session}
        )
        self.assertEqual((status, json.loads(data)["user"]), (200, None))
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertIsNone(self.get("/api/v1/session", Cookie=session)[1]["user"])
        self.assertEqual(self.post({"description": "robot"}, cookie=session)[0], 401)
        self.assertEqual(self.request("DELETE", "/api/v1/session")[0], 200)
        self.assertEqual(self.request("DELETE", "/api/v1/builds")[0], 404)
        status, headers, _ = self.request(
            "OPTIONS", "/api/v1/session", headers={"Origin": "http://127.0.0.1:5173"}
        )
        self.assertIn("DELETE", headers["Access-Control-Allow-Methods"])

    def test_bad_credentials_are_refused(self):
        status, cookie, error = self.sign_in("forged")
        self.assertEqual((status, error["code"], cookie), (401, "sign_in_failed", ""))
        status, _, error = self.sign_in("down")
        self.assertEqual((status, error["code"]), (503, "sign_in_unavailable"))
        for body, content_type in (
            ({}, "application/json"),
            ({"credential": 5}, "application/json"),
            ({"credential": "ada", "extra": 1}, "application/json"),
            (["ada"], "application/json"),
            (b"{broken", "application/json"),
            ({"credential": "ada"}, "text/plain"),
        ):
            with self.subTest(body=body, content_type=content_type):
                status, error = self.post(
                    body, key=None, path="/api/v1/session", content_type=content_type
                )
                self.assertEqual(status, 400)
        self.assertEqual(
            self.request("DELETE", "/api/v1/session", headers={"Host": "evil.test"})[0], 403
        )

    def test_hosts_other_than_loopback_get_a_host_prefixed_secure_cookie(self):
        status, cookie, _ = self.sign_in(Host="studio.example.com")
        self.assertEqual(status, 200)
        self.assertTrue(cookie.startswith("__Host-lgz_session="))
        self.assertTrue(cookie.endswith("; Secure"))
        token = cookie.split(";")[0].split("=", 1)[1]
        host = {"Host": "studio.example.com"}
        plain = self.get("/api/v1/session", Cookie=f"lgz_session={token}", **host)[1]
        prefixed = self.get("/api/v1/session", Cookie=f"__Host-lgz_session={token}", **host)[1]
        self.assertEqual((plain["user"], prefixed["user"]["id"]), (None, "google-1"))


class OwnershipTests(GoogleAuthTestCase):
    def setUp(self):
        super().setUp()
        self.ada, self.bob = self.session("ada"), self.session("bob")

    def as_user(self, cookie, path):
        return self.get(path, **({"Cookie": cookie} if cookie else {}))

    def test_each_user_sees_only_their_own_jobs(self):
        ada_job = self.post({"description": "a robot"}, key="a", cookie=self.ada)[1]
        bob_job = self.post({"description": "a boat"}, key="b", cookie=self.bob)[1]
        self.assertEqual(self.job(ada_job["id"])["userId"], "google-1")
        for cookie, expected in ((self.ada, [ada_job["id"]]), (self.bob, [bob_job["id"]])):
            items = self.as_user(cookie, "/api/v1/jobs")[1]["items"]
            self.assertEqual([job["id"] for job in items], expected)
        self.assertEqual(self.as_user(None, "/api/v1/jobs"), (200, {"items": []}))
        self.assertEqual(self.as_user(self.bob, f"/api/v1/jobs/{ada_job['id']}")[0], 404)
        self.assertEqual(self.as_user(self.ada, f"/api/v1/jobs/{ada_job['id']}")[0], 200)
        self.add_job("legacy")
        self.assertEqual(self.as_user(self.ada, "/api/v1/jobs/legacy")[0], 404)

    def test_saved_sets_are_private_to_their_owner(self):
        self.add_build("ada-set", mtime=1_000_001, userId="google-1")
        self.add_build("bob-set", mtime=1_000_002, userId="google-2")
        self.add_build("legacy", mtime=1_000_003)
        status, page = self.as_user(self.ada, "/api/v1/builds")
        self.assertEqual((status, [b["id"] for b in page["items"]]), (200, ["ada-set"]))
        self.assertEqual(page["items"][0]["mine"], True)
        self.assertNotIn("userId", page["items"][0])
        self.assertEqual(self.as_user(None, "/api/v1/builds")[1]["code"], "sign_in_required")

        for cookie, status in ((self.ada, 200), (self.bob, 404), (None, 404)):
            with self.subTest(cookie=cookie):
                for path in (
                    "/api/v1/builds/ada-set",
                    "/api/v1/builds/ada-set/parts",
                    "/api/v1/assets/ada-set/render.png",
                ):
                    self.assertEqual(
                        self.request("GET", path, headers={"Cookie": cookie or ""})[0], status
                    )
        status, legacy = self.as_user(None, "/api/v1/builds/legacy")
        self.assertEqual((status, legacy["mine"]), (200, False))

    def test_only_the_owner_can_refine_a_set(self):
        brick = Placement(PART_BY_CODE["3001"], 0, 0, 0, 4, 4, 2)
        for build_id, owner in (("ada-set", "google-1"), ("legacy", None)):
            directory = self.add_build(build_id, **({"userId": owner} if owner else {}))
            write_mpd(None, [brick], directory / "model.mpd")
        path = "/api/v1/builds/{}/refinements"
        body = {"prompt": "add a flag"}
        self.assertEqual(self.post(body, path=path.format("ada-set"), cookie=self.bob)[0], 404)
        status, error = self.post(body, path=path.format("legacy"), cookie=self.bob)
        self.assertEqual((status, error["code"]), (403, "not_owner"))
        status, job = self.post(body, path=path.format("ada-set"), cookie=self.ada)
        self.assertEqual((status, self.job(job["id"])["userId"]), (202, "google-1"))

    def test_each_user_may_have_one_pending_build_within_the_shared_cap(self):
        first = self.post({"description": "a robot"}, key="a1", cookie=self.ada)
        self.assertEqual(first[0], 202)
        status, error = self.post({"description": "a boat"}, key="a2", cookie=self.ada)
        self.assertEqual(status, 429)
        self.assertIn("still in progress", error["message"])
        self.assertEqual(self.post({"description": "a robot"}, key="a1", cookie=self.ada), first)
        with mock.patch.dict(os.environ, {"LEGOLIZER_MAX_PENDING": "2"}):
            self.assertEqual(self.post({"description": "a cat"}, key="b1", cookie=self.bob)[0], 202)
            status, error = self.post({"description": "a dog"}, key="c1", cookie=self.session("cy"))
        self.assertEqual(status, 429)
        self.assertIn("2 builds are already queued", error["message"])
        with mock.patch.dict(os.environ, {"LEGOLIZER_MAX_PENDING_PER_USER": "2"}):
            self.assertEqual(
                self.post({"description": "a boat"}, key="a2", cookie=self.ada)[0], 202
            )
            status, error = self.post({"description": "a van"}, key="a3", cookie=self.ada)
        self.assertIn("2 builds in progress", error["message"])


class GalleryTests(GoogleAuthTestCase):
    def setUp(self):
        super().setUp()
        self.ada, self.bob = self.session("ada"), self.session("bob")
        directory = self.add_build("castle", userId="google-1")
        write_mpd(
            None, [Placement(PART_BY_CODE["3001"], 0, 0, 0, 4, 4, 2)], directory / "model.mpd"
        )

    def share(self, cookie, visibility, build_id="castle"):
        headers = {"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})}
        path = f"/api/v1/builds/{build_id}/visibility"
        status, _, data = self.request("PUT", path, {"visibility": visibility}, headers)
        return status, json.loads(data)

    def test_published_sets_open_for_everyone_but_only_the_owner_edits_them(self):
        self.assertEqual(self.get("/api/v1/gallery"), (200, {"items": [], "nextCursor": None}))
        self.assertEqual(self.get("/api/v1/builds/castle")[0], 404)
        status, shared = self.share(self.ada, "public")
        self.assertEqual(
            (status, shared["visibility"], shared["authorName"], shared["mine"]),
            (200, "public", "Ada", True),
        )
        status, page = self.get("/api/v1/gallery")
        self.assertEqual(
            [(b["id"], b["authorName"], b["mine"]) for b in page["items"]],
            [("castle", "Ada", False)],
        )
        self.assertNotIn("userId", page["items"][0])
        for path in (
            "/api/v1/builds/castle",
            "/api/v1/builds/castle/parts",
            "/api/v1/assets/castle/render.png",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path, headers={"Cookie": self.bob})[0], 200)
                self.assertEqual(self.request("GET", path)[0], 200)
        refine = "/api/v1/builds/castle/refinements"
        status, error = self.post({"prompt": "add a flag"}, path=refine, cookie=self.bob)
        self.assertEqual((status, error["code"]), (403, "not_owner"))
        self.assertEqual(self.share(self.bob, "private")[1]["code"], "not_owner")
        self.assertEqual(self.get("/api/v1/builds", Cookie=self.bob)[1]["items"], [])

        status, hidden = self.share(self.ada, "private")
        self.assertEqual((status, hidden["visibility"]), (200, "private"))
        self.assertEqual(self.get("/api/v1/gallery")[1]["items"], [])
        self.assertEqual(self.get("/api/v1/builds/castle", Cookie=self.bob)[0], 404)

    def test_sharing_needs_the_owner_and_a_valid_request(self):
        self.assertEqual(self.share(None, "public")[1]["code"], "sign_in_required")
        self.assertEqual(self.share(self.bob, "public")[0], 404)
        self.add_build("legacy")
        self.assertEqual(self.share(self.ada, "public", "legacy")[1]["code"], "not_owner")
        self.assertEqual(self.share(self.ada, "public", "missing")[0], 404)
        headers = {"Content-Type": "application/json", "Cookie": self.ada}
        for body in ({"visibility": "friends"}, {}, {"visibility": "public", "x": 1}, ["public"]):
            with self.subTest(body=body):
                path = "/api/v1/builds/castle/visibility"
                self.assertEqual(self.request("PUT", path, body, headers)[0], 400)
        with mock.patch.object(server.LocalStore, "set_visibility", return_value=None):
            self.assertEqual(self.share(self.ada, "public")[0], 404)
        self.assertEqual(self.request("PUT", "/api/v1/builds/castle", {}, headers)[0], 404)
        evil = {**headers, "Host": "evil.test"}
        self.assertEqual(self.request("PUT", "/api/v1/builds/castle/visibility", {}, evil)[0], 403)
        for query in ("limit=0", "cursor=-1"):
            self.assertEqual(self.get(f"/api/v1/gallery?{query}")[0], 400)
        _, headers, _ = self.request(
            "OPTIONS", "/api/v1/gallery", headers={"Origin": "http://127.0.0.1:5173"}
        )
        self.assertIn("PUT", headers["Access-Control-Allow-Methods"])


class GenerateTests(ServerTestCase):
    def run_generate(self, job_id, *, run=None, pdf=True, exit_code=0, finished=True, **kwargs):
        output = self.root / "models" / job_id
        built, guide = [], mock.Mock()
        guide.wait.return_value = exit_code
        guide.returncode = exit_code
        guide.poll.return_value = 0 if finished else None

        def export(*args, **popen_kwargs):
            if pdf:
                (output / "build-guide.pdf").write_bytes(b"%PDF")
            return guide

        with (
            mock.patch("legolizer.cli.build_command", lambda args: built.append(args)),
            mock.patch.object(server, "_ldraw_dir", lambda: str(self.root)),
            mock.patch.object(server.subprocess, "Popen", export),
            mock.patch.object(server.subprocess, "run", run or mock.Mock()),
            mock.patch.object(server, "package_build", lambda *a: {"id": a[3], "name": a[4]}),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            server.generate(job_id, **kwargs)
        return built, guide

    def test_text_job_draws_a_concept_and_publishes(self):
        self.add_job("t1")
        drawn = []
        with mock.patch.object(providers, "generate_concept", lambda *a: drawn.append(a)):
            [args], _ = self.run_generate("t1")
        output = self.root / "models" / "t1"
        self.assertEqual(drawn, [("a robot", output / "concept.png", None)])
        self.assertEqual((args.concept, args.fixture_json, args.out), (drawn[0][1], None, output))
        job = self.job("t1")
        self.assertEqual((job["status"], job["buildId"], job["progress"]), ("succeeded", "t1", 1))
        self.assertEqual(server.read_json(output / "build.json"), {"id": "t1", "name": "Robot"})

    def test_stylized_job_publishes_its_brief(self):
        self.add_job("s1", stylize=True)
        output = self.root / "models" / "s1"
        output.mkdir(parents=True)
        server.write_json(
            output / "brief.json",
            {"original": "a robot", "brief": "A red robot.", "palette": [4, 71], "expanded": "x"},
        )
        with mock.patch.object(providers, "generate_concept", lambda *a: None):
            [args], _ = self.run_generate("s1")
        self.assertTrue(args.stylize)
        self.assertEqual(
            server.read_json(output / "build.json")["brief"],
            {"prompt": "A red robot.", "palette": ["Red", "Light Bluish Grey"]},
        )

    def test_stylized_job_credits_its_reference_photo(self):
        self.add_job("p1", stylize=True)
        output = self.root / "models" / "p1"
        output.mkdir(parents=True)
        server.write_json(
            output / "brief.json",
            {"original": "a robot", "brief": "b", "palette": [], "expanded": "x"},
        )
        server.write_json(
            output / "reference.json",
            {
                "query": "Eiffel Tower",
                "file": "reference.jpg",
                "title": "Tour Eiffel.jpg",
                "page": "https://commons.wikimedia.org/wiki/File:Tour_Eiffel.jpg",
                "license": "Public domain",
            },
        )
        server.write_json(output / "size.json", {"size": 32, "reason": "tall"})
        with mock.patch.object(providers, "generate_concept", lambda *a: None):
            self.run_generate("p1")
        self.assertEqual(server.read_json(output / "build.json")["size"]["size"], 32)
        self.assertEqual(
            server.read_json(output / "build.json")["brief"]["reference"],
            {
                "title": "Tour Eiffel.jpg",
                "page": "https://commons.wikimedia.org/wiki/File:Tour_Eiffel.jpg",
                "license": "Public domain",
                "artist": "",
            },
        )

    def test_draw_concept_uses_the_expanded_prompt_and_reference(self):
        drawn = []
        output = self.root / "models" / "d1"
        output.mkdir(parents=True)
        brief = {"brief": "b", "palette": [], "expanded": "A tall tower.", "reference": "Tower"}
        photo = output / "reference.jpg"
        with (
            mock.patch.object(providers, "stylize_prompt", lambda d: dict(brief)),
            mock.patch.object(reference, "find_reference", lambda query, out: photo),
            mock.patch.object(
                providers, "generate_concept", lambda d, o, r: drawn.append((d, o, r))
            ),
            mock.patch.dict(os.environ, {"REFERENCE_IMAGES": "wikimedia"}),
        ):
            server.draw_concept("tower", output, True)
            server.draw_concept("tower", output, False)
        self.assertEqual(
            drawn,
            [
                ("A tall tower.", output / "concept.png", photo),
                ("tower", output / "concept.png", None),
            ],
        )
        self.assertEqual(server.read_json(output / "brief.json")["original"], "tower")

    def test_image_job_uses_the_upload_as_concept(self):
        self.add_job("i1", inputType="image", sourceFile="source.png", description="")
        [args], _ = self.run_generate("i1")
        self.assertEqual(args.concept, self.root / "models" / "i1" / "source.png")
        self.assertIn("main subject of the reference image", args.description)
        self.assertEqual(self.job("i1")["status"], "succeeded")

    def test_resume_assembly_repacks_the_saved_model(self):
        self.add_job("r1")
        [args], _ = self.run_generate("r1", resume_assembly=True)
        self.assertEqual(args.fixture_json, self.root / "models" / "r1" / "model.json")
        self.assertIsNone(args.concept)

    def test_the_build_keeps_the_owner_of_its_job(self):
        self.add_job("o1", userId="google-1")
        self.run_generate("o1", resume_assembly=True)
        build = server.read_json(self.root / "models" / "o1" / "build.json")
        self.assertEqual(build["userId"], "google-1")

    def test_render_and_export_failures_fail_the_job_generically(self):
        self.add_job("f1")
        with mock.patch.object(providers, "generate_concept", lambda *a: None):
            render_error = mock.Mock(side_effect=subprocess.CalledProcessError(1, "render"))
            _, guide = self.run_generate("f1", run=render_error, finished=False)
        guide.kill.assert_called_once()
        job = self.job("f1")
        self.assertEqual((job["status"], job["error"]["code"]), ("failed", "generation_failed"))
        self.assertIn("during render", job["error"]["message"])
        self.assertIn("Check provider and renderer setup", job["error"]["message"])

        for job_id, options, stage in (
            ("f2", {"pdf": False}, "instructions"),
            ("f3", {"exit_code": 2}, "instructions"),
        ):
            self.add_job(job_id)
            with mock.patch.object(providers, "generate_concept", lambda *a: None):
                self.run_generate(job_id, **options)
            with self.subTest(job_id=job_id):
                self.assertIn(f"during {stage}", self.job(job_id)["error"]["message"])


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

        def fake_concept(description, output, reference):
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

        def broken_concept(description, output, reference):
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
        self.assertFalse(self.store.job(job["id"])["stylize"])
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

    def test_signed_in_users_share_the_queue_but_not_their_sets(self):
        cookies = {}
        for name, sub in (("ada", "1"), ("bob", "2")):
            user = {"id": f"google-{sub}", "name": name.title(), "picture": None}
            self.store.create_session(auth.token_hash(name), user, 60)
            cookies[name] = {"Cookie": f"lgz_session={name}"}
        env = {"LEGOLIZER_AUTH": "google", "LEGOLIZER_GOOGLE_CLIENT_ID": "client"}
        program = {"name": "Tower", "parts": [{"shape": "box", "min": [0, 0, 0], "max": [2, 2, 1]}]}
        with mock.patch.dict(os.environ, env):
            response, job = self.request(
                "POST", "/api/v1/builds", {"program": program}, headers=cookies["ada"]
            )
            self.assertEqual(response.status, 202, job)
            self.assertEqual(self.store.pending(), 1)
            self.assertEqual(
                self.request("GET", "/api/v1/jobs", headers=cookies["bob"])[1]["items"], []
            )
            with self.fake_pipeline([]):
                self.assertTrue(server.work_once("worker-a"))
            self.assertEqual(self.store.pending(), 0)
            _, page = self.request("GET", "/api/v1/builds", headers=cookies["ada"])
            self.assertEqual([(b["id"], b["mine"]) for b in page["items"]], [(job["id"], True)])
            _, page = self.request("GET", "/api/v1/builds", headers=cookies["bob"])
            self.assertEqual(page["items"], [])
            guide = f"/api/v1/assets/{job['id']}/build-guide.pdf"
            self.assertEqual(self.request("GET", guide, headers=cookies["ada"])[0].status, 302)
            self.assertEqual(self.request("GET", guide, headers=cookies["bob"])[0].status, 404)

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

    def test_initialize_puts_an_old_demo_seed_in_the_gallery_once(self):
        old = self.root / "old"
        old.mkdir()
        self.store.publish("robot-corrected", old, {"id": "robot-corrected", "name": "Little Bot"})
        server.initialize()
        self.assertEqual(self.store.build("robot-corrected")["visibility"], "public")
        self.assertEqual([b["id"] for b in self.store.gallery("", 5)[0]], ["robot-corrected"])
        self.store.set_visibility("robot-corrected", None, False, "Legolizer")
        shutil.rmtree(self.root / "models")
        server.initialize()
        self.assertEqual(self.store.gallery("", 5)[0], [])

    def test_initialize_seeds_the_demo_robot_without_touching_running_jobs(self):
        from test_storage import job

        self.store.create_job(job("elsewhere", status="running"))
        server.initialize()
        self.assertEqual(self.store.build("robot-corrected")["id"], "robot-corrected")
        self.assertIsNotNone(self.store.asset("robot-corrected", "packed.mpd"))
        self.assertEqual(self.store.job("elsewhere")["status"], "running")


class StartupTests(ServerTestCase):
    def test_initialize_seeds_the_demo_and_settles_interrupted_jobs(self):
        repo = self.root / "repo"
        demo = repo / "src/frontend/public/demo"
        demo.mkdir(parents=True)
        (demo / "render.png").write_bytes(b"png")
        server.write_json(
            demo / "build.json",
            {"id": "robot-corrected", "assets": {"preview": "/demo/render.png"}},
        )
        self.add_build("done")
        self.add_job("done", status="running")
        self.add_job("lost", status="queued")
        self.add_job("old", status="succeeded", buildId="old")
        with mock.patch.object(server, "REPO", repo):
            server.initialize()
            seeded = self.root / "models" / "robot-corrected"
            self.assertEqual(
                server.read_json(seeded / "build.json")["assets"],
                {"preview": "/api/v1/assets/robot-corrected/render.png"},
            )
            self.assertEqual((seeded / "render.png").read_bytes(), b"png")
            self.assertEqual(server.read_json(seeded / "build.json")["visibility"], "public")
            (seeded / "render.png").write_bytes(b"kept")
            server.initialize()
            before_gallery = server.read_json(seeded / "build.json")
            del before_gallery["visibility"]
            server.write_json(seeded / "build.json", before_gallery)
            server.initialize()
        self.assertEqual(server.read_json(seeded / "build.json")["authorName"], "Legolizer")
        self.assertEqual((seeded / "render.png").read_bytes(), b"kept")
        self.assertEqual(self.job("done")["status"], "succeeded")
        self.assertEqual(
            (self.job("lost")["status"], self.job("lost")["error"]["code"]),
            ("failed", "interrupted"),
        )
        self.assertEqual(self.job("old")["status"], "succeeded")

    def test_setup_problem_checks_renderers(self):
        library = self.root / "ldraw"
        library.mkdir()
        (library / "parts.lst").write_text("", encoding="utf-8")
        cases = [
            ({"OPENAI_API_KEY": "o"}, "Install LPub3D"),
            ({"OPENAI_API_KEY": "o", "LPUB3D_BIN": "lpub3d"}, "Install LDView"),
            ({"OPENAI_API_KEY": "o", "LPUB3D_BIN": "lpub3d", "LDVIEW_BIN": "ldview"}, None),
        ]
        with (
            mock.patch.object(server, "_ldraw_dir", lambda: str(library)),
            mock.patch.object(server.shutil, "which", lambda name: None),
            mock.patch.object(server, "_app_binary", lambda name: None),
        ):
            for env, expected in cases:
                with self.subTest(env=env), mock.patch.dict(os.environ, env, clear=True):
                    problem = SETUP_PROBLEM(False)
                    if expected is None:
                        self.assertIsNone(problem)
                    else:
                        self.assertIn(expected, problem)

    def test_directory_lock_is_exclusive(self):
        path = self.root / "server.lock"
        with path.open("a") as first, path.open("a") as second:
            server.lock_directory(first)
            with self.assertRaises(OSError):
                server.lock_directory(second)

    def test_main_serves_until_interrupted_and_refuses_a_second_server(self):
        root = mock.MagicMock()
        lock_file = (root / "server.lock").open.return_value
        httpd = mock.Mock()
        httpd.serve_forever.side_effect = KeyboardInterrupt
        with (
            mock.patch.object(server, "ROOT", root),
            mock.patch("dotenv.load_dotenv"),
            mock.patch.object(server, "lock_directory") as lock,
            mock.patch.object(server, "initialize") as initialize,
            mock.patch.object(server, "ThreadingHTTPServer", return_value=httpd) as cls,
            mock.patch.object(server.WORKER, "shutdown") as shutdown,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            server.main()
        lock.assert_called_once_with(lock_file)
        initialize.assert_called_once()
        cls.assert_called_once_with(("127.0.0.1", 8000), server.Handler)
        httpd.server_close.assert_called_once()
        shutdown.assert_called_once_with(wait=False, cancel_futures=True)

        with (
            mock.patch.object(server, "ROOT", root),
            mock.patch("dotenv.load_dotenv"),
            mock.patch.object(server, "lock_directory", side_effect=OSError),
            mock.patch.object(server, "initialize") as initialize,
        ):
            with self.assertRaisesRegex(SystemExit, "already owns"):
                server.main()
        initialize.assert_not_called()

    def test_main_refuses_google_auth_without_a_client_id(self):
        env = {"LEGOLIZER_AUTH": "google", "LEGOLIZER_GOOGLE_CLIENT_ID": ""}
        with (
            mock.patch("dotenv.load_dotenv"),
            mock.patch.dict(os.environ, env),
            mock.patch.object(server, "lock_directory") as lock,
        ):
            with self.assertRaisesRegex(SystemExit, "LEGOLIZER_GOOGLE_CLIENT_ID"):
                server.main()
        lock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
