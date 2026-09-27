"""Persistent generation API. Start with: uv run python -m legolizer.server."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from legolizer import auth
from legolizer.catalog import COLORS
from legolizer.ldraw import read_mpd
from legolizer.providers import design_setup_problem, image_setup_problem
from legolizer.render import _app_binary, _ldraw_dir
from legolizer.shape import parse_selection, region_json
from legolizer.storage import PENDING, AwsStore, LocalStore, read_json, write_json
from legolizer.uploads import validate_upload
from legolizer.web_assets import package_build

REPO = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("LEGOLIZER_DATA_DIR", REPO / "builds" / "studio")).resolve()
LOCK = threading.RLock()
WORKER = ThreadPoolExecutor(max_workers=1)
# Set when LEGOLIZER_BACKEND=aws; ROOT is then only a per-container working directory.
REMOTE: AwsStore | None = None
HEARTBEAT_SECONDS = 30
# Concept images for queued text jobs start at once instead of waiting for the worker;
# three threads match the three-pending-job cap, and each job still gets one image.
IMAGES = ThreadPoolExecutor(max_workers=3)
CONCEPTS = {}
DEMO_ID = "robot-corrected"
ASSETS = {
    "packed.mpd",
    "model.mpd",
    "LDConfig.ldr",
    "build-guide.pdf",
    "parts.json",
    "render.png",
    "readme.txt",
    "careadme.txt",
    "calicense.txt",
    "calicense4.txt",
}
ORIGINS = {
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
}
PAUSED = "Temporary generation pause to conserve compute. Please try again later."
INTERRUPTED = {
    "code": "interrupted",
    "message": "The generation server restarted. Submit again to retry; saved sets are intact.",
}


def store():
    return REMOTE or LocalStore(ROOT)


def jobs():
    return store().jobs()


def _env_list(name):
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def origin_allowed(origin):
    return origin in ORIGINS or any(
        fnmatch.fnmatchcase(origin, pattern) for pattern in _env_list("LEGOLIZER_ALLOWED_ORIGINS")
    )


def host_allowed(host):
    return host in ("127.0.0.1", "localhost") or any(
        fnmatch.fnmatchcase(host or "", pattern) for pattern in _env_list("LEGOLIZER_ALLOWED_HOSTS")
    )


def program_jobs_enabled():
    return os.getenv("LEGOLIZER_PROGRAM_JOBS", "").lower() in ("1", "true", "yes")


def public_job(job):
    return {
        **{
            k: job[k]
            for k in (
                "id",
                "status",
                "stage",
                "progress",
                "buildId",
                "error",
                "name",
                "description",
            )
        },
        "inputType": job.get("inputType", "text"),
        "parentId": job.get("parentId"),
    }


def owner_id(user):
    """Whose jobs and sets a request lists: the signed-in user, or everyone's with auth off."""
    return user["id"] if auth.mode() == "google" else None


def owns(user, record):
    return auth.mode() == "off" or (user is not None and record.get("userId") == user["id"])


def readable(user, build):
    """Published sets are public. Sets saved before accounts have no owner and stay readable."""
    return build.get("visibility") == "public" or not build.get("userId") or owns(user, build)


def page_args(query):
    """(cursor, limit) of a listing request; ValueError when the limit is out of range."""
    limit = int(query.get("limit", ["20"])[0])
    if not 1 <= limit <= 100:
        raise ValueError()
    return query.get("cursor", [""])[0], limit


def public_build(build, user):
    return {**{k: v for k, v in build.items() if k != "userId"}, "mine": owns(user, build)}


def update_job(job_id, **changes):
    with LOCK:
        store().update_job(job_id, **changes)


def setup_problem(needs_concept, needs_design=True):
    """Return why the server cannot run a generation job, or None."""
    if needs_design and (problem := design_setup_problem()):
        return f"{problem} on the local server, then restart it."
    if needs_concept and (problem := image_setup_problem()):
        return f"Text generation draws a concept image first. {problem} on the local server."
    library = _ldraw_dir()
    if not library or not (Path(library) / "parts.lst").is_file():
        return "Configure LDRAW_LIBRARY_PATH on the server before generating."
    if not (os.getenv("LPUB3D_BIN") or shutil.which("lpub3d") or _app_binary("LPub3D")):
        return "Install LPub3D on the server before generating."
    if not (
        os.getenv("LDVIEW_BIN")
        or shutil.which("LDView64")
        or shutil.which("LDView")
        or shutil.which("ldview")
        or _app_binary("LDView")
    ):
        return "Install LDView on the server before generating."
    return None


def ensure_worker():
    """Start the on-demand worker task when no worker has checked in recently."""
    cluster = os.getenv("LEGOLIZER_WORKER_CLUSTER")
    if not (REMOTE and cluster):
        return
    if not REMOTE.reserve_worker_start(float(os.getenv("LEGOLIZER_WORKER_START_SECONDS", "300"))):
        return
    try:
        task = REMOTE.run_worker_task(
            cluster,
            os.environ["LEGOLIZER_WORKER_TASK_DEFINITION"],
            _env_list("LEGOLIZER_WORKER_SUBNETS"),
            _env_list("LEGOLIZER_WORKER_SECURITY_GROUPS"),
        )
        print(f"Started worker task {task}", flush=True)
    except Exception as exc:
        REMOTE.release_worker("starting")
        print(f"Worker start failed: {type(exc).__name__}: {exc}", flush=True)


def draw_concept(description, output, stylize):
    from legolizer.cli import prepare_brief, reference_photo
    from legolizer.providers import generate_concept

    reference = None
    if stylize:
        brief = prepare_brief(description, output)
        description = brief["expanded"]
        reference = reference_photo(brief, output)
    generate_concept(description, output / "concept.png", reference)


def start_concept(job_id, description, stylize=False):
    """Request a text job's brief and concept image in the background; returns its future."""
    output = ROOT / "models" / job_id
    output.mkdir(parents=True, exist_ok=True)
    with LOCK:
        if job_id not in CONCEPTS:
            CONCEPTS[job_id] = IMAGES.submit(draw_concept, description, output, stylize)
        return CONCEPTS[job_id]


def generate(job_id, *, resume_assembly=False):
    from legolizer.cli import build_command, refine_command

    job = store().job(job_id)
    output = ROOT / "models" / job_id
    output.mkdir(parents=True, exist_ok=True)
    image_input = job.get("inputType") == "image"
    refine_input = job.get("inputType") == "refine"
    program_input = job.get("inputType") == "program"
    stage = (
        "assembly"
        if resume_assembly
        else ("scene" if image_input or refine_input or program_input else "views")
    )
    # The shared queue accepts jobs without checking this host's setup; the worker does.
    if REMOTE and (
        problem := setup_problem(
            not (image_input or refine_input or program_input), not program_input
        )
    ):
        update_job(
            job_id,
            status="failed",
            stage="failed",
            error={"code": "setup_required", "message": problem},
        )
        return
    try:
        update_job(job_id, status="running", stage=stage, progress=0.05, error=None)

        def progress(round_, rounds):
            # Design-and-review rounds run inside build_command / refine_command.
            update_job(
                job_id, stage="scene", progress=round(0.2 + 0.4 * round_ / max(1, rounds), 2)
            )

        if refine_input:
            store().fetch_build(job["parentId"], ROOT / "models" / job["parentId"])
            refine_command(
                argparse.Namespace(
                    source=ROOT / "models" / job["parentId"],
                    out=output,
                    request=job["description"],
                    selection=parse_selection(job.get("selection", [])),
                    description=job["parentDescription"] or job["parentName"],
                    candidates=None,
                    iterations=None,
                    progress=progress,
                )
            )
        else:
            if resume_assembly:
                saved_program = output / "program.json"
                args = dict(
                    fixture_json=None if saved_program.is_file() else output / "model.json",
                    program=saved_program if saved_program.is_file() else None,
                    concept=None,
                    repair_supports=True,
                    prune_loose=True,
                )
            elif program_input:
                store().fetch_upload(job_id, job["sourceFile"], output)
                args = dict(fixture_json=None, program=output / job["sourceFile"], concept=None)
            else:
                if image_input:
                    store().fetch_upload(job_id, job["sourceFile"], output)
                # An uploaded picture plays the concept image's role: a reference for the
                # designer, never measured. Text jobs draw their own concept first.
                concept = output / job["sourceFile"] if image_input else output / "concept.png"
                if not image_input:
                    try:
                        start_concept(
                            job_id, job["description"], job.get("stylize", False)
                        ).result()
                    finally:
                        with LOCK:
                            CONCEPTS.pop(job_id, None)
                stage = "scene"
                update_job(job_id, stage=stage, progress=0.2)
                args = dict(fixture_json=None, program=None, concept=concept)
            description = job["description"] or (
                "the main subject of the reference image, ignoring its background"
                if image_input
                else ""
            )
            build_command(
                argparse.Namespace(
                    out=output,
                    description=description,
                    no_concept=False,
                    iterations=None,
                    progress=progress,
                    max_size=job.get("maxSize"),
                    stylize=job.get("stylize", False),
                    **args,
                )
            )
        stage = "assembly"
        stage = "render"
        update_job(job_id, stage=stage, progress=0.65)
        # Native renderers run in subprocesses with bounded runtimes; the render and the
        # PDF export read the same finished model, so they run side by side.
        lpub = os.environ.get("LPUB3D_BIN") or shutil.which("lpub3d") or _app_binary("LPub3D")
        env = {**os.environ, "LDRAWDIR": _ldraw_dir(), "LPUB3D_DISABLE_UPDATE_CHECK": "1"}
        guide = subprocess.Popen(
            [
                lpub,
                "--liblego",
                "--preferred-renderer",
                "native",
                "--process-export",
                "--export-option",
                "pdf",
                "--output-file",
                str(output / "build-guide.pdf"),
                str(output / "model.mpd"),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "legolizer.cli",
                    "render",
                    str(output / "model.mpd"),
                    "--out",
                    str(output / "render.png"),
                ],
                check=True,
                timeout=180,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            stage = "instructions"
            update_job(job_id, stage=stage, progress=0.8)
            if guide.wait(timeout=180) != 0:
                raise subprocess.CalledProcessError(guide.returncode, lpub)
        finally:
            if guide.poll() is None:
                guide.kill()
                guide.wait()
        if not (output / "build-guide.pdf").is_file():
            raise RuntimeError("PDF export did not produce a guide")
        metadata = package_build(
            output,
            output,
            Path(_ldraw_dir()),
            job_id,
            job["name"],
            job["parentDescription"] if refine_input else job["description"],
            f"/api/v1/assets/{job_id}",
        )
        if refine_input:
            refinement = read_json(output / "refine.json")
            metadata["refinement"] = {
                "parentId": job["parentId"],
                "prompt": refinement["request"],
                "selection": refinement["selection"],
                "keptPieces": refinement["keptPieces"],
                "rebuiltPieces": len(refinement["rebuilt"]),
            }
        if (output / "size.json").is_file():
            metadata["size"] = read_json(output / "size.json")
        if (output / "brief.json").is_file():
            brief = read_json(output / "brief.json")
            metadata["brief"] = {
                "prompt": brief["brief"],
                "palette": [COLORS[code].replace("_", " ") for code in brief["palette"]],
            }
            if (output / "reference.json").is_file():
                photo = read_json(output / "reference.json")
                metadata["brief"]["reference"] = {
                    key: photo.get(key, "") for key in ("title", "page", "license", "artist")
                }
        if job.get("userId"):
            metadata["userId"] = job["userId"]
        # Publish only when all artifacts exist. Every generation has its own directory.
        store().publish(job_id, output, metadata)
        update_job(job_id, status="succeeded", stage="complete", progress=1, buildId=job_id)
    except Exception as exc:
        print(f"Generation {job_id} failed during {stage}: {type(exc).__name__}", flush=True)
        # Design and packing errors (e.g. unattached pieces) are safe, actionable messages.
        detail = (
            str(exc)
            if stage in ("scene", "assembly") and isinstance(exc, (ValueError, RuntimeError))
            else ""
        )
        update_job(
            job_id,
            status="failed",
            stage="failed",
            error={
                "code": "generation_failed",
                "message": f"Generation failed during {stage}. Your saved sets are unchanged. "
                + (
                    detail
                    or "Check provider and renderer setup, or retry with a simpler connected sculpture."
                ),
            },
        )


def demo_retracted(build):
    """False for demo seeds from before it left the gallery (auto-published at time 0)."""
    return "visibility" in build and not (
        build["visibility"] == "public" and build.get("publishedAt") == 0
    )


def initialize():
    (ROOT / "jobs").mkdir(parents=True, exist_ok=True)
    (ROOT / "models").mkdir(exist_ok=True)
    # Preserve the existing robot independently of future demo changes. It stays openable
    # by id but out of the gallery and saved sets.
    demo = REPO / "src/frontend/public/demo"
    target = ROOT / "models" / DEMO_ID
    seeded = target / "build.json"
    if demo.is_dir() and (not seeded.exists() or not demo_retracted(read_json(seeded))):
        target.mkdir(exist_ok=True)
        for name in ASSETS:
            if (demo / name).exists() and not (target / name).exists():
                shutil.copyfile(demo / name, target / name)
        metadata = read_json(demo / "build.json")
        metadata["assets"] = {
            key: value.replace("/demo/", f"/api/v1/assets/{DEMO_ID}/")
            for key, value in metadata["assets"].items()
        }
        metadata["visibility"] = "private"
        write_json(seeded, metadata)
    if REMOTE:
        # Other containers may be mid-job; stale jobs are reaped by heartbeat instead.
        current = REMOTE.build(DEMO_ID)
        if current is None or "visibility" not in current:
            if seeded.exists():
                REMOTE.publish(DEMO_ID, target, read_json(seeded))
        elif not demo_retracted(current):
            REMOTE.set_visibility(DEMO_ID, None, False, current.get("authorName"))
        return
    for job in jobs():
        if job["status"] in ("running", "queued"):
            if (ROOT / "models" / job["id"] / "build.json").exists():
                update_job(
                    job["id"], status="succeeded", stage="complete", progress=1, buildId=job["id"]
                )
            else:
                update_job(job["id"], status="failed", stage="failed", error=INTERRUPTED)


def work_once(owner):
    """Claim and run one queued job from the shared table; False when none is waiting."""
    REMOTE.reap(float(os.getenv("LEGOLIZER_STALE_SECONDS", "300")), INTERRUPTED)
    job = REMOTE.claim(owner)
    if job is None:
        return False
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                REMOTE.touch(job["id"])
            except Exception as exc:
                print(f"Heartbeat for {job['id']} failed: {type(exc).__name__}", flush=True)

    threading.Thread(target=heartbeat, daemon=True).start()
    try:
        generate(job["id"])
    finally:
        stop.set()
    return True


def work(owner, idle_exit=0):
    """Run queued jobs; with idle_exit, return once no job has arrived for that many seconds."""
    idle_since = time.monotonic()
    while True:
        try:
            busy = work_once(owner)
        except Exception as exc:
            print(f"Queue worker {owner}: {type(exc).__name__}: {exc}", flush=True)
            busy = False
        if busy:
            idle_since = time.monotonic()
        elif idle_exit and time.monotonic() - idle_since >= idle_exit:
            return
        else:
            time.sleep(float(os.getenv("LEGOLIZER_POLL_SECONDS", "3")))


def run_workers(owner, count, idle_exit=0):
    """Hold the worker lease while running `count` queue workers; return when they go idle.

    The lease is released before the final queue check, and the API queues a job before
    looking at the lease, so a job submitted during shutdown is never left without a worker.
    """
    REMOTE.hold_worker(owner)
    while True:
        stop = threading.Event()

        def lease(stop=stop):
            while not stop.wait(HEARTBEAT_SECONDS):
                try:
                    REMOTE.hold_worker(owner)
                except Exception as exc:
                    print(f"Worker lease renewal failed: {type(exc).__name__}", flush=True)

        threading.Thread(target=lease, daemon=True).start()
        threads = [
            threading.Thread(target=work, args=(f"{owner}-{index}", idle_exit), daemon=True)
            for index in range(count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        stop.set()
        REMOTE.release_worker(owner)
        if not (REMOTE.has_queued() and REMOTE.acquire_worker(owner)):
            return


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, value, cookie=None):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_cors()
        self.end_headers()
        self.wfile.write(data)

    def send_cors(self):
        origin = self.headers.get("Origin")
        if origin and origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def failure(self, status, message, code="request_failed"):
        self.send_json(status, {"code": code, "message": message})

    def allowed(self):
        host = urlsplit("http://" + self.headers.get("Host", "")).hostname
        origin = self.headers.get("Origin")
        return host_allowed(host) and (origin is None or origin_allowed(origin))

    def secure(self):
        """Whether the session cookie must be Secure: every host but plain-HTTP loopback."""
        return urlsplit("http://" + self.headers.get("Host", "")).hostname not in (
            "127.0.0.1",
            "localhost",
        )

    def user(self):
        """The signed-in user, or None; with LEGOLIZER_AUTH=off everyone is the local user."""
        if auth.mode() == "off":
            return auth.LOCAL_USER
        token = auth.read_cookie(self.headers.get("Cookie"), self.secure())
        return store().session_user(auth.token_hash(token)) if token else None

    def is_admin(self, user):
        """Admins may pause generation. With auth off, the one local user is the operator."""
        if auth.mode() == "off":
            return True
        record = store().user(user["id"]) if user else None
        return bool(record) and auth.is_admin_email(record.get("email"))

    def session_state(self, user):
        return {
            "auth": auth.mode(),
            "googleClientId": auth.client_id(),
            "user": user,
            "admin": self.is_admin(user),
            "paused": store().generation_paused(),
        }

    def set_pause(self):
        user = self.user()
        if user is None:
            return self.failure(401, "Sign in with Google first.", "sign_in_required")
        if not self.is_admin(user):
            return self.failure(403, "Only admins can pause generation.", "not_admin")
        try:
            raw = self.json_body(1024)
            paused = raw.get("paused") if len(raw) == 1 else None
            if not isinstance(paused, bool):
                raise ValueError()
        except ValueError:
            return self.failure(400, 'Send {"paused": true} or {"paused": false}.')
        store().set_generation_paused(paused, user["id"])
        print(f"Generation {'paused' if paused else 'resumed'} by {user['id']}", flush=True)
        self.send_json(200, {"paused": paused})

    def json_body(self, limit):
        """The request's JSON object; ValueError when it is missing, too large, or not an object."""
        size = int(self.headers.get("Content-Length", "0"))
        if (
            not 0 < size <= limit
            or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
        ):
            raise ValueError()
        raw = json.loads(self.rfile.read(size))
        if not isinstance(raw, dict):
            raise ValueError()
        return raw

    def sign_in(self):
        if auth.mode() == "off":
            return self.failure(400, "Sign-in is disabled on this server.", "auth_disabled")
        try:
            raw = self.json_body(16 * 1024)
            credential = raw.get("credential") if len(raw) == 1 else None
            if not isinstance(credential, str):
                raise ValueError()
        except ValueError:
            return self.failure(400, "Send the Google sign-in credential as JSON.")
        try:
            claims = auth.verify_google(credential)
        except ValueError as exc:
            return self.failure(401, str(exc), "sign_in_failed")
        except RuntimeError as exc:
            return self.failure(503, str(exc), "sign_in_unavailable")
        profile = auth.profile(claims)
        store().save_user(profile)
        user = {key: profile[key] for key in ("id", "name", "picture")}
        token = auth.new_token()
        store().create_session(auth.token_hash(token), user, auth.SESSION_SECONDS)
        self.send_json(200, self.session_state(user), auth.set_cookie(token, self.secure()))

    def do_DELETE(self):
        if not self.allowed():
            return self.failure(403, "This API is available only to the local workspace.")
        if urlsplit(self.path).path != "/api/v1/session":
            return self.failure(404, "Endpoint not found.")
        if auth.mode() == "off":
            return self.send_json(200, self.session_state(auth.LOCAL_USER))
        if token := auth.read_cookie(self.headers.get("Cookie"), self.secure()):
            store().delete_session(auth.token_hash(token))
        self.send_json(200, self.session_state(None), auth.clear_cookie(self.secure()))

    def do_PUT(self):
        if not self.allowed():
            return self.failure(403, "This API is available only to the local workspace.")
        path = urlsplit(self.path).path
        if path == "/api/v1/pause":
            return self.set_pause()
        match = re.fullmatch(r"/api/v1/builds/([a-zA-Z0-9_-]+)/visibility", path)
        if not match:
            return self.failure(404, "Endpoint not found.")
        user = self.user()
        if user is None:
            return self.failure(401, "Sign in with Google to share sets.", "sign_in_required")
        build = store().build(match[1])
        if build is None or not readable(user, build):
            return self.failure(404, "Saved build not found.")
        if not owns(user, build):
            return self.failure(403, "Only the set's owner can share it.", "not_owner")
        try:
            raw = self.json_body(1024)
            visibility = raw.get("visibility") if len(raw) == 1 else None
            if visibility not in ("public", "private"):
                raise ValueError()
        except ValueError:
            return self.failure(400, 'Send {"visibility": "public"} or {"visibility": "private"}.')
        updated = store().set_visibility(
            match[1], owner_id(user), visibility == "public", user["name"]
        )
        if updated is None:
            return self.failure(404, "Saved build not found.")
        self.send_json(200, public_build(updated, user))

    def do_OPTIONS(self):
        if not self.allowed():
            return self.failure(403, "This API is available only to the local workspace.")
        self.send_response(204)
        self.send_header(
            "Access-Control-Allow-Origin", self.headers.get("Origin", "http://127.0.0.1:5173")
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key")
        self.end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/v1/health":
            return self.send_json(
                200,
                {
                    "status": "ok",
                    "backend": "aws" if REMOTE else "local",
                    "auth": auth.mode(),
                    "renderersReady": setup_problem(False, needs_design=False) is None,
                    "setupProblem": setup_problem(True),
                },
            )
        if not self.allowed():
            return self.failure(403, "This API is available only to the local workspace.")
        if path == "/api/v1/session":
            return self.send_json(200, self.session_state(self.user()))
        if path == "/api/v1/builds":
            user = self.user()
            if user is None:
                return self.failure(
                    401, "Sign in with Google to see your saved sets.", "sign_in_required"
                )
            try:
                cursor, limit = page_args(parse_qs(urlsplit(self.path).query))
                items, next_cursor = store().builds(cursor, limit, owner_id(user))
            except ValueError:
                return self.failure(400, "Invalid cursor or limit.")
            items = [public_build(build, user) for build in items if build.get("id") != DEMO_ID]
            self.send_json(200, {"items": items, "nextCursor": next_cursor})
        elif path == "/api/v1/gallery":
            try:
                items, next_cursor = store().gallery(
                    *page_args(parse_qs(urlsplit(self.path).query))
                )
            except ValueError:
                return self.failure(400, "Invalid cursor or limit.")
            user = self.user()
            items = [public_build(build, user) for build in items]
            self.send_json(200, {"items": items, "nextCursor": next_cursor})
        elif path == "/api/v1/jobs":
            user = self.user()
            with LOCK:
                items = [public_job(j) for j in store().jobs(owner_id(user))] if user else []
            if any(job["status"] == "queued" for job in items):
                ensure_worker()
            self.send_json(200, {"items": items})
        elif match := re.fullmatch(r"/api/v1/jobs/([a-zA-Z0-9_-]+)", path):
            job = store().job(match[1])
            if job and owns(self.user(), job):
                self.send_json(200, public_job(job))
            else:
                self.failure(404, "Job not found.")
        elif match := re.fullmatch(r"/api/v1/builds/([a-zA-Z0-9_-]+)(/parts)?", path):
            user = self.user()
            build = store().build(match[1])
            # Other users' private sets answer 404, like missing ones, so IDs reveal nothing.
            if build is None or not readable(user, build):
                return self.failure(404, "Saved build not found.")
            if match[2]:
                data = store().asset(match[1], "parts.json")
                value = json.loads(data) if data else None
            else:
                value = public_build(build, user)
            if value is None:
                return self.failure(404, "Saved build not found.")
            self.send_json(200, value)
        elif match := re.fullmatch(r"/api/v1/assets/([a-zA-Z0-9_-]+)/([^/]+)", path):
            build = store().build(match[1]) if match[2] in ASSETS else None
            if build is None or not readable(self.user(), build):
                return self.failure(404, "Asset not found.")
            if REMOTE:
                url = REMOTE.asset_url(match[1], match[2]) if match[2] in ASSETS else None
                if url is None:
                    return self.failure(404, "Asset not found.")
                self.send_response(302)
                self.send_header("Location", url)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.send_cors()
                return self.end_headers()
            data = store().asset(match[1], match[2]) if match[2] in ASSETS else None
            if data is None:
                return self.failure(404, "Asset not found.")
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(match[2])[0] or "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.send_cors()
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
        else:
            self.failure(404, "Endpoint not found.")

    def do_POST(self):
        if not self.allowed():
            return self.failure(403, "This API is available only to the local workspace.")
        path = urlsplit(self.path).path
        if path == "/api/v1/session":
            return self.sign_in()
        refinement = re.fullmatch(r"/api/v1/builds/([a-zA-Z0-9_-]+)/refinements", path)
        if not (refinement or path in ("/api/v1/sizing", "/api/v1/builds")):
            return self.failure(404, "Endpoint not found.")
        user = self.user()
        if user is None:
            return self.failure(401, "Sign in with Google to generate sets.", "sign_in_required")
        if store().generation_paused():
            return self.failure(503, PAUSED, "generation_paused")
        if refinement:
            return self.refine(refinement[1], user)
        if path == "/api/v1/sizing":
            return self.size_estimate()
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if (
                not 0 < size <= 6 * 1024 * 1024
                or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
            ):
                return self.failure(
                    400, "Send a JSON description or image upload (maximum request size 6 MB)."
                )
            raw = json.loads(self.rfile.read(size))
            if not isinstance(raw, dict) or set(raw) - {
                "name",
                "description",
                "maxColors",
                "maxSize",
                "stylize",
                "image",
                "program",
            }:
                raise ValueError()
            image_input = "image" in raw
            stylize = raw.get("stylize", True)
            if not isinstance(stylize, bool):
                raise ValueError("stylize must be true or false.")
            program_input = "program" in raw
            if program_input:
                if not program_jobs_enabled():
                    return self.failure(
                        403, "Shape-program jobs are disabled on this server.", "program_disabled"
                    )
                if image_input or not isinstance(raw["program"], dict):
                    raise ValueError()
            upload = validate_upload(raw["image"]) if image_input else None
            description = raw.get("description", "")
            name = raw.get("name", "")
            max_size = raw.get("maxSize")
            if max_size is not None:
                from legolizer.providers import parse_max_size

                max_size = parse_max_size(max_size)
            if (
                not isinstance(description, str)
                or not (0 if image_input or program_input else 1)
                <= len(description.strip())
                <= 2000
            ):
                raise ValueError()
            if not isinstance(name, str) or len(name.strip()) > 80:
                raise ValueError()
            key = self.headers.get("Idempotency-Key", "")
            if not 1 <= len(key) <= 128:
                return self.failure(400, "An Idempotency-Key is required.")
        except (ValueError, TypeError) as exc:
            return self.failure(
                400,
                str(exc)
                if str(exc) and not isinstance(exc, json.JSONDecodeError)
                else "Provide a valid image or a description of 1–2,000 characters, and a name up to 80 characters.",
            )
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()

        def prepare(job_id):
            source, fallback = None, "Image-inspired set"
            if upload:
                source = "source" + upload[1]
                store().save_upload(job_id, source, upload[0])
            elif program_input:
                source = "input-program.json"
                store().save_upload(job_id, source, json.dumps(raw["program"]).encode())
                fallback = str(raw["program"].get("name") or "Shape program")[:60]
            return {
                "name": name.strip() or description.strip()[:60] or fallback,
                "inputType": "image" if image_input else "program" if program_input else "text",
                "sourceFile": source,
                "description": description.strip(),
                "maxSize": max_size,
                "stylize": stylize and not (image_input or program_input),
            }

        text_input = not (image_input or program_input)
        self.enqueue(user, key, digest, text_input, prepare, needs_design=not program_input)

    def size_estimate(self):
        from legolizer.providers import estimate_size

        message = "Provide a description of 1–2,000 characters, or an image, to suggest a size."
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if (
                not 0 < length <= 6 * 1024 * 1024
                or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
            ):
                return self.failure(400, message)
            raw = json.loads(self.rfile.read(length))
            if not isinstance(raw, dict) or set(raw) - {"description", "image"}:
                raise ValueError()
            description = raw.get("description", "")
            image = validate_upload(raw["image"]) if "image" in raw else None
            if not isinstance(description, str) or len(description) > 2000:
                raise ValueError()
            if not description.strip() and not image:
                raise ValueError()
        except (ValueError, TypeError) as exc:
            return self.failure(
                400,
                str(exc) if str(exc) and not isinstance(exc, json.JSONDecodeError) else message,
            )
        if problem := setup_problem(False):
            return self.failure(503, problem)
        path = None
        try:
            if image:
                path = ROOT / "tmp" / f"size-{uuid.uuid4().hex}{image[1]}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(image[0])
            sizing = estimate_size(description.strip(), path)
        except Exception as exc:
            return self.failure(502, f"Size estimate failed: {exc}")
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
        self.send_json(200, sizing)

    def refine(self, parent_id, user):
        parent = ROOT / "models" / parent_id
        build = store().build(parent_id)
        if build is None or not readable(user, build):
            return self.failure(404, "Saved build not found.")
        if not owns(user, build):
            return self.failure(403, "Only the set's owner can refine it.", "not_owner")
        message = "Provide a change of 1–2,000 characters, up to 400 selected bricks, and a name up to 80 characters."
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if (
                not 0 < size <= 64 * 1024
                or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
            ):
                return self.failure(400, message)
            raw = json.loads(self.rfile.read(size))
            if not isinstance(raw, dict) or set(raw) - {"name", "prompt", "selection"}:
                raise ValueError()
            prompt, name = raw.get("prompt"), raw.get("name", "")
            if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 2000:
                raise ValueError()
            if not isinstance(name, str) or len(name.strip()) > 80:
                raise ValueError()
            selection = parse_selection(raw.get("selection", []))
            key = self.headers.get("Idempotency-Key", "")
            if not 1 <= len(key) <= 128:
                return self.failure(400, "An Idempotency-Key is required.")
        except (ValueError, TypeError) as exc:
            return self.failure(
                400, str(exc) if str(exc) and not isinstance(exc, json.JSONDecodeError) else message
            )
        try:
            store().fetch_build(parent_id, parent)
            read_mpd(parent / "model.mpd")
        except (OSError, ValueError):
            return self.failure(400, "This set uses pieces the editor cannot rebuild.")
        digest = hashlib.sha256(
            json.dumps({"parentId": parent_id, **raw}, sort_keys=True).encode()
        ).hexdigest()

        def prepare(job_id):
            return {
                "name": name.strip() or f"{build['name']} (refined)"[:80],
                "inputType": "refine",
                "sourceFile": None,
                "description": prompt.strip(),
                "parentId": parent_id,
                "parentName": build["name"],
                "parentDescription": build.get("description", ""),
                "selection": [region_json(box) for box in selection],
            }

        self.enqueue(user, key, digest, False, prepare)

    def enqueue(self, user, key, digest, needs_concept, prepare, needs_design=True):
        owner = owner_id(user)
        with LOCK:
            mine = store().jobs(owner)
            for job in mine:
                if job.get("key") == key:
                    if job["digest"] != digest:
                        return self.failure(
                            409, "This request key was already used for another prompt."
                        )
                    return self.send_json(202, public_job(job))
            if not REMOTE and (problem := setup_problem(needs_concept, needs_design)):
                return self.failure(503, problem)
            allowed = int(os.getenv("LEGOLIZER_MAX_PENDING_PER_USER", "1"))
            if owner and sum(job["status"] in PENDING for job in mine) >= allowed:
                return self.failure(
                    429,
                    "Your last build is still in progress. Wait for it to finish, then try again."
                    if allowed == 1
                    else f"You already have {allowed} builds in progress. Wait for one to finish.",
                )
            limit = int(os.getenv("LEGOLIZER_MAX_PENDING", "3"))
            if store().pending() >= limit:
                return self.failure(
                    429, f"{limit} builds are already queued. Please wait for one to finish."
                )
            job_id = uuid.uuid4().hex
            job = {
                "id": job_id,
                **prepare(job_id),
                "status": "queued",
                "stage": "queued",
                "progress": 0,
                "buildId": None,
                "error": None,
                "key": key,
                "digest": digest,
                **({"userId": owner} if owner else {}),
            }
            store().create_job(job)
            # With the shared queue, whichever worker claims the job does all its work.
            if not REMOTE:
                if needs_concept:
                    start_concept(job_id, job["description"], job.get("stylize", False))
                WORKER.submit(generate, job_id)
        ensure_worker()
        self.send_json(202, public_job(job))


def lock_directory(handle):
    """Take an exclusive, non-blocking lock that the OS releases when the process exits."""
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def main():
    global REMOTE, WORKER
    from dotenv import find_dotenv, load_dotenv

    # Same configuration as the CLI: .env fills in anything not already set.
    load_dotenv(find_dotenv(usecwd=True))
    backend = os.getenv("LEGOLIZER_BACKEND", "local").lower()
    if backend not in ("local", "aws"):
        raise SystemExit("LEGOLIZER_BACKEND must be local or aws.")
    if problem := auth.configuration_problem():
        raise SystemExit(problem)
    workers = int(os.getenv("LEGOLIZER_WORKERS", "1"))
    ROOT.mkdir(parents=True, exist_ok=True)
    # Prevent a second server from interrupting the first server's job records.
    process_lock = (ROOT / "server.lock").open("a")
    try:
        lock_directory(process_lock)
    except OSError:
        raise SystemExit("A server already owns this saved-build directory.") from None
    if backend == "aws":
        REMOTE = AwsStore.from_env()
    initialize()
    if not REMOTE and workers != 1:
        WORKER = ThreadPoolExecutor(max_workers=workers)
    host = os.getenv("LEGOLIZER_HOST", "127.0.0.1")
    port = int(os.getenv("LEGOLIZER_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    if REMOTE:
        owner = f"{socket.gethostname()}-{os.getpid()}"
        idle_exit = float(os.getenv("LEGOLIZER_IDLE_EXIT_SECONDS", "0"))

        def serve_queue():
            run_workers(owner, workers, idle_exit)
            print(f"Queue idle for {idle_exit:.0f}s; stopping.", flush=True)
            server.shutdown()

        threading.Thread(target=serve_queue, daemon=True).start()
    print(
        f"Legolizer API: http://{host}:{port}/api/v1 | backend: {backend} | "
        f"workers: {workers} | working directory: {ROOT}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
    finally:
        WORKER.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
