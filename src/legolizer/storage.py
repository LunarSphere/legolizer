"""Saved builds and job records: local files, or DynamoDB + S3 shared by several containers."""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import os
import time
from decimal import Decimal
from pathlib import Path

KIND_INDEX = "byKind"
STATUS_INDEX = "byStatus"


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class LocalStore:
    """Files under one directory owned by a single server process."""

    remote = False

    def __init__(self, root: Path):
        self.root = root

    def jobs(self):
        return [read_json(p) for p in sorted((self.root / "jobs").glob("*.json"), reverse=True)]

    def job(self, job_id):
        path = self.root / "jobs" / f"{job_id}.json"
        return read_json(path) if path.is_file() else None

    def create_job(self, job):
        write_json(self.root / "jobs" / f"{job['id']}.json", job)

    def update_job(self, job_id, **changes):
        path = self.root / "jobs" / f"{job_id}.json"
        job = read_json(path)
        job.update(changes)
        write_json(path, job)

    def builds(self, cursor, limit):
        offset = int(cursor or "0")
        if offset < 0:
            raise ValueError("Invalid cursor.")
        entries = sorted(
            (self.root / "models").glob("*/build.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        items = [read_json(p) for p in entries[offset : offset + limit]]
        return items, str(offset + limit) if offset + limit < len(entries) else None

    def build(self, build_id):
        path = self.root / "models" / build_id / "build.json"
        return read_json(path) if path.is_file() else None

    def asset(self, build_id, name):
        directory = self.root / "models" / build_id
        if not (directory / "build.json").is_file() or not (directory / name).is_file():
            return None
        return (directory / name).read_bytes()

    def save_upload(self, job_id, name, data):
        directory = self.root / "models" / job_id
        directory.mkdir(parents=True, exist_ok=False)
        (directory / name).write_bytes(data)

    def fetch_upload(self, job_id, name, directory):
        pass

    def fetch_build(self, build_id, directory):
        pass

    def publish(self, build_id, directory, metadata):
        write_json(directory / "build.json", metadata)


def _item(value):
    return json.loads(json.dumps(value), parse_float=Decimal)


def _plain(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _now():
    return int(time.time() * 1000)


def _lost_race(exc):
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


class AwsStore:
    """DynamoDB records and S3 objects shared by every container.

    Queued job records are the queue: an idle worker claims the oldest one with a
    conditional write, so each job runs once however many containers poll.
    """

    remote = True
    INTERNAL = ("pk", "kind", "createdAt", "heartbeatAt", "owner")
    WORKER = {"pk": "WORKER"}

    def __init__(self, bucket, table, *, session=None, dynamodb=None, s3=None, public_s3=None):
        import boto3

        self.session = session or boto3.Session()
        self.bucket = bucket
        self.table = (dynamodb or self.session.resource("dynamodb")).Table(table)
        self.s3 = s3 or self.session.client("s3")
        self.public_s3 = public_s3 or self.s3

    @classmethod
    def from_env(cls):
        import boto3
        from botocore.config import Config

        bucket, table = os.getenv("LEGOLIZER_BUCKET"), os.getenv("LEGOLIZER_TABLE")
        if not (bucket and table):
            raise RuntimeError("LEGOLIZER_BACKEND=aws needs LEGOLIZER_BUCKET and LEGOLIZER_TABLE.")
        # Vercel reserves the AWS_* names; unset values fall back to the default chain.
        session = boto3.Session(
            aws_access_key_id=os.getenv("LEGOLIZER_AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("LEGOLIZER_AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("LEGOLIZER_AWS_REGION"),
        )
        # Browsers must reach presigned links; inside compose S3 has a container-only name.
        public = os.getenv("LEGOLIZER_S3_PUBLIC_ENDPOINT")
        public_s3 = (
            session.client(
                "s3", endpoint_url=public, config=Config(s3={"addressing_style": "path"})
            )
            if public
            else None
        )
        return cls(bucket, table, session=session, public_s3=public_s3)

    def _query(self, index, key, value, *, forward):
        from boto3.dynamodb.conditions import Key

        kwargs = {
            "IndexName": index,
            "KeyConditionExpression": Key(key).eq(value),
            "ScanIndexForward": forward,
        }
        while True:
            page = self.table.query(**kwargs)
            yield from page["Items"]
            if "LastEvaluatedKey" not in page:
                return
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def _update(self, job_id, changes, condition=None, names=None, values=None):
        kwargs = {"ConditionExpression": condition} if condition else {}
        self.table.update_item(
            Key={"pk": f"JOB#{job_id}"},
            UpdateExpression="SET " + ", ".join(f"#k{i} = :v{i}" for i in range(len(changes))),
            ExpressionAttributeNames={
                **{f"#k{i}": key for i, key in enumerate(changes)},
                **(names or {}),
            },
            ExpressionAttributeValues={
                **{f":v{i}": _item(value) for i, value in enumerate(changes.values())},
                **(values or {}),
            },
            **kwargs,
        )

    def _job(self, item):
        return {k: v for k, v in _plain(item).items() if k not in self.INTERNAL}

    def jobs(self):
        return [self._job(i) for i in self._query(KIND_INDEX, "kind", "job", forward=False)]

    def job(self, job_id):
        item = self.table.get_item(Key={"pk": f"JOB#{job_id}"}, ConsistentRead=True).get("Item")
        return self._job(item) if item else None

    def create_job(self, job):
        now = _now()
        self.table.put_item(
            Item=_item(
                {
                    **job,
                    "pk": f"JOB#{job['id']}",
                    "kind": "job",
                    "createdAt": now,
                    "heartbeatAt": now,
                }
            ),
            ConditionExpression="attribute_not_exists(pk)",
        )

    def update_job(self, job_id, **changes):
        self._update(job_id, {**changes, "heartbeatAt": _now()})

    def touch(self, job_id):
        self._update(job_id, {"heartbeatAt": _now()})

    def claim(self, owner):
        from botocore.exceptions import ClientError

        for item in self._query(STATUS_INDEX, "status", "queued", forward=True):
            try:
                self._update(
                    item["id"],
                    {"status": "running", "owner": owner, "heartbeatAt": _now()},
                    "#status = :queued",
                    {"#status": "status"},
                    {":queued": "queued"},
                )
            except ClientError as exc:
                if _lost_race(exc):
                    continue
                raise
            return self.job(item["id"])
        return None

    def reap(self, stale_seconds, error):
        """Fail running jobs whose worker stopped sending heartbeats."""
        from botocore.exceptions import ClientError

        cutoff = _now() - int(stale_seconds * 1000)
        for item in self._query(STATUS_INDEX, "status", "running", forward=True):
            if item.get("heartbeatAt", 0) >= cutoff:
                continue
            try:
                self._update(
                    item["id"],
                    {"status": "failed", "stage": "failed", "error": error},
                    "#status = :running AND #beat < :cutoff",
                    {"#status": "status", "#beat": "heartbeatAt"},
                    {":running": "running", ":cutoff": cutoff},
                )
            except ClientError as exc:
                if not _lost_race(exc):
                    raise

    def builds(self, cursor, limit):
        from boto3.dynamodb.conditions import Key
        from botocore.exceptions import ClientError

        kwargs = {
            "IndexName": KIND_INDEX,
            "KeyConditionExpression": Key("kind").eq("build"),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if cursor:
            try:
                start = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            except (binascii.Error, ValueError) as exc:
                raise ValueError("Invalid cursor.") from exc
            if not isinstance(start, dict):
                raise ValueError("Invalid cursor.")
            kwargs["ExclusiveStartKey"] = start
        try:
            page = self.table.query(**kwargs)
        except ClientError as exc:
            if cursor and exc.response.get("Error", {}).get("Code") == "ValidationException":
                raise ValueError("Invalid cursor.") from exc
            raise
        last = page.get("LastEvaluatedKey")
        next_cursor = (
            base64.urlsafe_b64encode(json.dumps(_plain(last)).encode()).decode() if last else None
        )
        return [_plain(item["build"]) for item in page["Items"]], next_cursor

    def _record(self, build_id):
        return self.table.get_item(Key={"pk": f"BUILD#{build_id}"}).get("Item")

    def build(self, build_id):
        item = self._record(build_id)
        return _plain(item["build"]) if item else None

    def asset(self, build_id, name):
        item = self._record(build_id)
        key = item["objects"].get(name) if item else None
        if not key:
            return None
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def asset_url(self, build_id, name, expires=900):
        """A short-lived S3 link, so large files bypass the API's response size limit."""
        item = self._record(build_id)
        key = item["objects"].get(name) if item else None
        if not key:
            return None
        params = {"Bucket": self.bucket, "Key": key}
        if not name.endswith((".pdf", ".png")):
            params["ResponseContentDisposition"] = f'attachment; filename="{name}"'
        return self.public_s3.generate_presigned_url("get_object", Params=params, ExpiresIn=expires)

    def has_queued(self):
        from boto3.dynamodb.conditions import Key

        page = self.table.query(
            IndexName=STATUS_INDEX, KeyConditionExpression=Key("status").eq("queued"), Limit=1
        )
        return bool(page["Items"])

    def hold_worker(self, owner):
        """Record that a worker process is alive (and replace a pending start reservation)."""
        self.table.put_item(Item={**self.WORKER, "owner": owner, "beatAt": _now()})

    def acquire_worker(self, owner):
        from botocore.exceptions import ClientError

        try:
            self.table.put_item(
                Item={**self.WORKER, "owner": owner, "beatAt": _now()},
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as exc:
            if _lost_race(exc):
                return False
            raise
        return True

    def release_worker(self, owner):
        from botocore.exceptions import ClientError

        try:
            self.table.delete_item(
                Key=self.WORKER,
                ConditionExpression="#owner = :owner",
                ExpressionAttributeNames={"#owner": "owner"},
                ExpressionAttributeValues={":owner": owner},
            )
        except ClientError as exc:
            if not _lost_race(exc):
                raise

    def reserve_worker_start(self, stale_seconds):
        """True when no worker (or pending start) has checked in recently; the caller starts one."""
        from botocore.exceptions import ClientError

        try:
            self.table.put_item(
                Item={**self.WORKER, "owner": "starting", "beatAt": _now()},
                ConditionExpression="attribute_not_exists(pk) OR beatAt < :cutoff",
                ExpressionAttributeValues={":cutoff": _now() - int(stale_seconds * 1000)},
            )
        except ClientError as exc:
            if _lost_race(exc):
                return False
            raise
        return True

    def run_worker_task(self, cluster, task_definition, subnets, security_groups):
        response = self.session.client("ecs").run_task(
            cluster=cluster,
            taskDefinition=task_definition,
            launchType="FARGATE",
            count=1,
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnets,
                    "securityGroups": security_groups,
                    "assignPublicIp": "DISABLED",
                }
            },
        )
        if response.get("failures") or not response.get("tasks"):
            raise RuntimeError(f"Could not start the worker task: {response.get('failures')}")
        return response["tasks"][0]["taskArn"]

    def save_upload(self, job_id, name, data):
        self.s3.put_object(Bucket=self.bucket, Key=f"uploads/{job_id}/{name}", Body=data)

    def fetch_upload(self, job_id, name, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.s3.download_file(self.bucket, f"uploads/{job_id}/{name}", str(directory / name))

    def fetch_build(self, build_id, directory):
        """Copy a published build into a local working directory (for refinement)."""
        if (directory / "build.json").is_file():
            return
        item = self._record(build_id)
        if not item:
            raise FileNotFoundError(f"Saved build {build_id} not found")
        for name, key in item["objects"].items():
            if name == "build.json":
                continue
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            self.s3.download_file(self.bucket, key, str(target))
        write_json(directory / "build.json", _plain(item["build"]))

    def publish(self, build_id, directory, metadata):
        """Upload every artifact, then record the build so it becomes visible."""
        write_json(directory / "build.json", metadata)
        prefix = f"builds/{build_id}/"
        objects = {}
        for path in sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix != ".tmp"):
            name = path.relative_to(directory).as_posix()
            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            # Single PUTs: build files are MBs, and S3-compatible mocks reject boto3 multipart checksums.
            with path.open("rb") as body:
                self.s3.put_object(
                    Bucket=self.bucket, Key=prefix + name, Body=body, ContentType=content_type
                )
            objects[name] = prefix + name
        self.table.put_item(
            Item=_item(
                {
                    "pk": f"BUILD#{build_id}",
                    "kind": "build",
                    "createdAt": _now(),
                    "id": build_id,
                    "build": metadata,
                    "s3Prefix": prefix,
                    "objects": objects,
                }
            )
        )
