"""Local, persistent generation API. Start with: uv run python -m legolizer.server."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from legolizer.ldraw import read_mpd
from legolizer.providers import image_setup_problem
from legolizer.render import _app_binary, _ldraw_dir
from legolizer.shape import parse_selection, region_json
from legolizer.uploads import validate_upload
from legolizer.web_assets import package_build

REPO = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("LEGOLIZER_DATA_DIR", REPO / "builds" / "studio")).resolve()
LOCK = threading.RLock()
WORKER = ThreadPoolExecutor(max_workers=1)
# Concept images for queued text jobs start at once instead of waiting for the worker;
# three threads match the three-pending-job cap, and each job still gets one image.
IMAGES = ThreadPoolExecutor(max_workers=3)
CONCEPTS = {}
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


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def jobs():
    return [read_json(p) for p in sorted((ROOT / "jobs").glob("*.json"), reverse=True)]


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


def update_job(job_id, **changes):
    with LOCK:
        path = ROOT / "jobs" / f"{job_id}.json"
        job = read_json(path)
        job.update(changes)
        write_json(path, job)


def setup_problem(needs_concept):
    """Return why the server cannot run a generation job, or None."""
    if not (
        os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    ):
        return "Set OPENAI_API_KEY (or ANTHROPIC_API_KEY) on the local server, then restart it."
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


def start_concept(job_id, description):
    """Request a text job's concept image in the background; returns its future."""
    from legolizer.providers import generate_concept

    output = ROOT / "models" / job_id
    output.mkdir(parents=True, exist_ok=True)
    with LOCK:
        if job_id not in CONCEPTS:
            CONCEPTS[job_id] = IMAGES.submit(generate_concept, description, output / "concept.png")
        return CONCEPTS[job_id]


def generate(job_id, *, resume_assembly=False):
    from legolizer.cli import build_command, refine_command

    job = read_json(ROOT / "jobs" / f"{job_id}.json")
    output = ROOT / "models" / job_id
    output.mkdir(parents=True, exist_ok=True)
    image_input = job.get("inputType") == "image"
    refine_input = job.get("inputType") == "refine"
    stage = "assembly" if resume_assembly else ("scene" if image_input or refine_input else "views")
    try:
        update_job(job_id, status="running", stage=stage, progress=0.05, error=None)

        def progress(round_, rounds):
            # Design-and-review rounds run inside build_command / refine_command.
            update_job(
                job_id, stage="scene", progress=round(0.2 + 0.4 * round_ / max(1, rounds), 2)
            )

        if refine_input:
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
                args = dict(fixture_json=output / "model.json", program=None, concept=None)
            else:
                # An uploaded picture plays the concept image's role: a reference for the
                # designer, never measured. Text jobs draw their own concept first.
                concept = output / job["sourceFile"] if image_input else output / "concept.png"
                if not image_input:
                    try:
                        start_concept(job_id, job["description"]).result()
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
        # Publish only when all artifacts exist. Every generation has its own directory.
        write_json(output / "build.json", metadata)
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


def initialize():
    (ROOT / "jobs").mkdir(parents=True, exist_ok=True)
    (ROOT / "models").mkdir(exist_ok=True)
    # Preserve the existing robot independently of future demo changes.
    demo = REPO / "src/frontend/public/demo"
    target = ROOT / "models/robot-corrected"
    if not (target / "build.json").exists() and demo.is_dir():
        target.mkdir(exist_ok=True)
        for name in ASSETS:
            if (demo / name).exists():
                shutil.copyfile(demo / name, target / name)
        metadata = read_json(demo / "build.json")
        metadata["assets"] = {
            key: value.replace("/demo/", "/api/v1/assets/robot-corrected/")
            for key, value in metadata["assets"].items()
        }
        write_json(target / "build.json", metadata)
    for job in jobs():
        if job["status"] in ("running", "queued"):
            if (ROOT / "models" / job["id"] / "build.json").exists():
                update_job(
                    job["id"], status="succeeded", stage="complete", progress=1, buildId=job["id"]
                )
            else:
                update_job(
                    job["id"],
                    status="failed",
                    stage="failed",
                    error={
                        "code": "interrupted",
                        "message": "The local server restarted. Submit again to retry; saved sets are intact.",
                    },
                )


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if self.headers.get("Origin") in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(data)

    def failure(self, status, message, code="request_failed"):
        self.send_json(status, {"code": code, "message": message})

    def allowed(self):
        host = urlsplit("http://" + self.headers.get("Host", "")).hostname
        return host in ("127.0.0.1", "localhost") and self.headers.get("Origin") in (None, *ORIGINS)

    def do_OPTIONS(self):
        if not self.allowed():
            return self.failure(403, "This API is available only to the local workspace.")
        self.send_response(204)
        self.send_header(
            "Access-Control-Allow-Origin", self.headers.get("Origin", "http://127.0.0.1:5173")
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key")
        self.end_headers()

    def do_GET(self):
        if not self.allowed():
            return self.failure(403, "This API is available only to the local workspace.")
        path = urlsplit(self.path).path
        if path == "/api/v1/builds":
            query = parse_qs(urlsplit(self.path).query)
            try:
                offset = int(query.get("cursor", ["0"])[0])
                limit = int(query.get("limit", ["20"])[0])
                if offset < 0 or not 1 <= limit <= 100:
                    raise ValueError()
            except ValueError:
                return self.failure(400, "Invalid cursor or limit.")
            entries = sorted(
                (ROOT / "models").glob("*/build.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            self.send_json(
                200,
                {
                    "items": [read_json(p) for p in entries[offset : offset + limit]],
                    "nextCursor": str(offset + limit) if offset + limit < len(entries) else None,
                },
            )
        elif path == "/api/v1/jobs":
            with LOCK:
                self.send_json(200, {"items": [public_job(j) for j in jobs()]})
        elif match := re.fullmatch(r"/api/v1/jobs/([a-zA-Z0-9_-]+)", path):
            source = ROOT / "jobs" / f"{match[1]}.json"
            if source.is_file():
                self.send_json(200, public_job(read_json(source)))
            else:
                self.failure(404, "Job not found.")
        elif match := re.fullmatch(r"/api/v1/builds/([a-zA-Z0-9_-]+)(/parts)?", path):
            directory = ROOT / "models" / match[1]
            if not (directory / "build.json").is_file():
                return self.failure(404, "Saved build not found.")
            self.send_json(200, read_json(directory / ("parts.json" if match[2] else "build.json")))
        elif match := re.fullmatch(r"/api/v1/assets/([a-zA-Z0-9_-]+)/([^/]+)", path):
            directory = ROOT / "models" / match[1]
            source = directory / match[2]
            if (
                match[2] not in ASSETS
                or not (directory / "build.json").exists()
                or not source.is_file()
            ):
                return self.failure(404, "Asset not found.")
            data = source.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(source.name)[0] or "text/plain")
            self.send_header("Content-Length", str(len(data)))
            if self.headers.get("Origin") in ORIGINS:
                self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
        else:
            self.failure(404, "Endpoint not found.")

    def do_POST(self):
        if not self.allowed():
            return self.failure(403, "This API is available only to the local workspace.")
        if match := re.fullmatch(r"/api/v1/builds/([a-zA-Z0-9_-]+)/refinements", self.path):
            return self.refine(match[1])
        if self.path != "/api/v1/builds":
            return self.failure(404, "Endpoint not found.")
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
                "image",
            }:
                raise ValueError()
            image_input = "image" in raw
            upload = validate_upload(raw["image"]) if image_input else None
            description = raw.get("description", "")
            name = raw.get("name", "")
            if (
                not isinstance(description, str)
                or not (0 if image_input else 1) <= len(description.strip()) <= 2000
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
            if upload:
                directory = ROOT / "models" / job_id
                directory.mkdir(parents=True, exist_ok=False)
                (directory / ("source" + upload[1])).write_bytes(upload[0])
            return {
                "name": name.strip() or description.strip()[:60] or "Image-inspired set",
                "inputType": "image" if image_input else "text",
                "sourceFile": "source" + upload[1] if upload else None,
                "description": description.strip(),
            }

        self.enqueue(key, digest, not image_input, prepare)

    def refine(self, parent_id):
        parent = ROOT / "models" / parent_id
        if not (parent / "build.json").is_file():
            return self.failure(404, "Saved build not found.")
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
            read_mpd(parent / "model.mpd")
        except (OSError, ValueError):
            return self.failure(400, "This set uses pieces the editor cannot rebuild.")
        build = read_json(parent / "build.json")
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

        self.enqueue(key, digest, False, prepare)

    def enqueue(self, key, digest, needs_concept, prepare):
        with LOCK:
            history = jobs()
            for job in history:
                if job.get("key") == key:
                    if job["digest"] != digest:
                        return self.failure(
                            409, "This request key was already used for another prompt."
                        )
                    return self.send_json(202, public_job(job))
            if problem := setup_problem(needs_concept):
                return self.failure(503, problem)
            if sum(j["status"] in ("running", "queued") for j in history) >= 3:
                return self.failure(
                    429, "Three builds are already queued. Please wait for one to finish."
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
            }
            write_json(ROOT / "jobs" / f"{job_id}.json", job)
            if needs_concept:
                start_concept(job_id, job["description"])
            WORKER.submit(generate, job_id)
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
    from dotenv import find_dotenv, load_dotenv

    # Same configuration as the CLI: .env fills in anything not already set.
    load_dotenv(find_dotenv(usecwd=True))
    ROOT.mkdir(parents=True, exist_ok=True)
    # Prevent a second server from interrupting the first server's job records.
    process_lock = (ROOT / "server.lock").open("a")
    try:
        lock_directory(process_lock)
    except OSError:
        raise SystemExit("A server already owns this saved-build directory.") from None
    initialize()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print(f"Legolizer API: http://127.0.0.1:8000/api/v1 | Saved builds: {ROOT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
    finally:
        WORKER.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
