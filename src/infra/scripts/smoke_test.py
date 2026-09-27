"""End-to-end check of a running Legolizer deployment (local compose stack or AWS).

Local (after `docker compose ... up`):
    uv run python src/infra/scripts/smoke_test.py --api http://127.0.0.1:8000 \
        --table legolizer --bucket legolizer-assets \
        --dynamodb-endpoint http://127.0.0.1:8900 --s3-endpoint http://127.0.0.1:9090
Deployed (the Vercel function queues jobs; the Fargate worker starts on demand):
    uv run python src/infra/scripts/smoke_test.py --api https://<app>.vercel.app \
        --origin https://<app>.vercel.app --remote-worker

Shape-program jobs make no provider calls, so the default run is free and repeatable;
--live adds one paid text generation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def shared_config():
    values = {}
    for line in (REPO / "src/infra/container.env").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


class Api:
    def __init__(self, base, origin):
        self.base = base.rstrip("/")
        self.origin = origin
        self.cookie = None

    def call(self, method, path, body=None, key=None):
        headers = {"Origin": self.origin} if self.origin else {}
        if self.cookie:
            headers["Cookie"] = self.cookie
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            headers["Idempotency-Key"] = key or uuid.uuid4().hex
        request = urllib.request.Request(self.base + path, data, headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def json(self, method, path, body=None, key=None):
        status, data, _ = self.call(method, path, body, key)
        return status, json.loads(data)


def check(condition, message):
    if not condition:
        raise SystemExit(f"FAIL: {message}")
    print(f"ok   {message}")


def wait_healthy(apis, timeout, live, remote_worker):
    """Wait for every API; return the last health report."""
    deadline = time.time() + timeout
    for api in apis:
        while True:
            try:
                status, health = api.json("GET", "/api/v1/health")
                if status == 200:
                    break
            except OSError:
                pass
            if time.time() > deadline:
                raise SystemExit(f"FAIL: {api.base} never became healthy")
            time.sleep(2)
        check(health["backend"] == "aws", f"{api.base} uses the shared aws backend")
        if remote_worker:
            continue
        check(health["renderersReady"], f"{api.base} has LDView, LPub3D and the LDraw library")
        if live:
            check(health["setupProblem"] is None, f"{api.base} has provider keys")
    return health


def credentials(args):
    options = {"region_name": args.region}
    if args.dynamodb_endpoint or args.s3_endpoint:
        options |= {"aws_access_key_id": "local", "aws_secret_access_key": "local"}
    return options


def sign_in(args, apis):
    """Record a test user and session in the table, as signIn does after Google verifies."""
    import boto3

    from legolizer import auth
    from legolizer.storage import AwsStore

    if not args.table:
        raise SystemExit("FAIL: the API requires Google sign-in; pass --table to create a session")
    dynamodb = boto3.resource("dynamodb", endpoint_url=args.dynamodb_endpoint, **credentials(args))
    store = AwsStore(args.bucket, args.table, dynamodb=dynamodb)
    user = {"id": f"smoke-{uuid.uuid4().hex[:12]}", "name": "Smoke test", "picture": None}
    store.save_user({**user, "email": ""})
    token = auth.new_token()
    store.create_session(auth.token_hash(token), user, 3600)
    for api in apis:
        secure = urllib.parse.urlsplit(api.base).hostname not in ("127.0.0.1", "localhost")
        api.cookie = f"{auth.cookie_name(secure)}={token}"
    status, session = apis[0].json("GET", "/api/v1/session")
    check(status == 200 and session["user"]["id"] == user["id"], "test session is signed in")


def poll(apis, ids, capacity, timeout):
    """Wait for jobs to finish; return (peak running, whether jobs queued at full capacity)."""
    peak, queued_at_capacity, turn = 0, False, 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        api = apis[turn % len(apis)]
        turn += 1
        _, page = api.json("GET", "/api/v1/jobs")
        mine = [j for j in page["items"] if j["id"] in ids]
        running = sum(j["status"] == "running" for j in mine)
        queued = sum(j["status"] == "queued" for j in mine)
        peak = max(peak, running)
        queued_at_capacity |= running == capacity and queued > 0
        failed = [j for j in mine if j["status"] == "failed"]
        if failed:
            raise SystemExit(f"FAIL: job {failed[0]['id']} failed: {failed[0]['error']}")
        done = sum(j["status"] == "succeeded" for j in mine)
        print(f"     {done}/{len(ids)} done, {running} running, {queued} queued", flush=True)
        if done == len(ids):
            return peak, queued_at_capacity
        time.sleep(1.5)
    raise SystemExit("FAIL: jobs did not finish before the timeout")


def check_outputs(apis, build_id):
    reader = apis[-1]
    status, build = reader.json("GET", f"/api/v1/builds/{build_id}")
    check(
        status == 200 and build["id"] == build_id, f"build {build_id} readable from {reader.base}"
    )
    status, parts = reader.json("GET", f"/api/v1/builds/{build_id}/parts")
    check(status == 200 and parts["parts"], "parts list is available")
    expected = {"render.png": b"\x89PNG", "build-guide.pdf": b"%PDF", "packed.mpd": b"0 "}
    for name, magic in expected.items():
        status, data, _ = reader.call("GET", f"/api/v1/assets/{build_id}/{name}")
        check(status == 200 and data.startswith(magic), f"{name} served ({len(data):,} bytes)")


def check_storage(args, build_id):
    import boto3
    from botocore.config import Config

    region = credentials(args)
    dynamodb = boto3.resource("dynamodb", endpoint_url=args.dynamodb_endpoint, **region)
    item = dynamodb.Table(args.table).get_item(Key={"pk": f"BUILD#{build_id}"}).get("Item")
    check(item is not None, f"DynamoDB has a build record for {build_id}")
    s3 = boto3.client(
        "s3",
        endpoint_url=args.s3_endpoint,
        config=Config(s3={"addressing_style": "path"}) if args.s3_endpoint else None,
        **region,
    )
    for name in ("render.png", "build-guide.pdf", "packed.mpd"):
        key = item["objects"][name]
        size = s3.head_object(Bucket=args.bucket, Key=key)["ContentLength"]
        check(size > 0, f"s3://{args.bucket}/{key} exists")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", action="append", required=True, help="API origin (repeatable)")
    parser.add_argument("--origin", default="http://127.0.0.1:5173", help="frontend origin")
    parser.add_argument(
        "--remote-worker",
        action="store_true",
        help="the API has no renderers; jobs run on a separate on-demand worker",
    )
    parser.add_argument("--program", type=Path, default=REPO / "tests/fixtures/trial-windmill.json")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--live", action="store_true", help="also run one paid text job")
    parser.add_argument("--table")
    parser.add_argument("--bucket")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--dynamodb-endpoint")
    parser.add_argument("--s3-endpoint")
    args = parser.parse_args()

    config = shared_config()
    capacity = int(config["LEGOLIZER_WORKERS"])
    max_pending = int(config["LEGOLIZER_MAX_PENDING"])
    apis = [Api(base, args.origin) for base in args.api]
    health = wait_healthy(apis, 300, args.live, args.remote_worker)
    if health.get("auth") == "google":
        sign_in(args, apis)

    status, data, headers = apis[0].call("GET", "/api/v1/jobs")
    check(
        status == 200 and headers.get("Access-Control-Allow-Origin") == args.origin,
        f"CORS allows {args.origin}",
    )
    _, page = apis[0].json("GET", "/api/v1/jobs")
    busy = sum(j["status"] in ("queued", "running") for j in page["items"])
    check(busy == 0, "queue is idle before the test")

    program = json.loads(args.program.read_text())
    ids, first_key = [], uuid.uuid4().hex
    for index in range(max_pending):
        key = first_key if index == 0 else uuid.uuid4().hex
        body = {"name": f"Smoke test {index + 1}", "program": program}
        status, job = apis[index % len(apis)].json("POST", "/api/v1/builds", body, key)
        check(status == 202, f"job {index + 1} queued via {apis[index % len(apis)].base}")
        ids.append(job["id"])
    status, overflow = apis[-1].json("POST", "/api/v1/builds", {"program": program})
    check(status == 429, f"job {max_pending + 1} is refused while {max_pending} are pending")
    status, again = apis[-1].json(
        "POST", "/api/v1/builds", {"name": "Smoke test 1", "program": program}, first_key
    )
    check(status == 202 and again["id"] == ids[0], "idempotent retry returns the same job")

    started = time.time()
    peak, queued_at_capacity = poll(apis, set(ids), capacity, args.timeout)
    print(f"     finished {len(ids)} jobs in {time.time() - started:.0f}s")
    check(peak <= capacity, f"at most {capacity} jobs ran at once (peak {peak})")
    check(peak == capacity, f"the worker ran {capacity} job(s) at once")
    check(queued_at_capacity, "extra jobs waited in the queue while the worker was busy")
    for build_id in ids:
        check_outputs(apis, build_id)
    if args.table and args.bucket:
        check_storage(args, ids[0])

    if args.live:
        body = {"name": "Smoke test live", "description": "a small red mushroom"}
        status, job = apis[0].json("POST", "/api/v1/builds", body)
        check(status == 202, "live text job queued")
        poll(apis, {job["id"]}, capacity, args.timeout)
        check_outputs(apis, job["id"])
    print("PASS")


if __name__ == "__main__":
    sys.exit(main())
