"""Local and DynamoDB + S3 stores; AWS is emulated in-process by moto."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from moto import mock_aws

from legolizer import storage
from legolizer.storage import AwsStore, LocalStore

SCHEMA = Path(__file__).resolve().parents[1] / "src" / "infra" / "table-schema.json"
FAKE_AWS = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
}


def aws_store(test):
    """Start moto and return an AwsStore over a table built from the CDK schema file."""
    patcher = mock.patch.dict(os.environ, FAKE_AWS)
    patcher.start()
    test.addCleanup(patcher.stop)
    mocked = mock_aws()
    mocked.start()
    test.addCleanup(mocked.stop)
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(TableName="legolizer", **json.loads(SCHEMA.read_text()))
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="assets")
    return AwsStore("assets", "legolizer", dynamodb=dynamodb, s3=s3)


def job(job_id, **fields):
    return {
        "id": job_id,
        "name": job_id,
        "inputType": "text",
        "sourceFile": None,
        "description": "a red mushroom",
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "buildId": None,
        "error": None,
        **fields,
    }


class AwsStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = aws_store(self)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)

    def test_schema_declares_the_indexes_the_store_queries(self):
        schema = json.loads(SCHEMA.read_text())
        indexes = {i["IndexName"]: i["KeySchema"] for i in schema["GlobalSecondaryIndexes"]}
        self.assertEqual(indexes[storage.KIND_INDEX][0]["AttributeName"], "kind")
        self.assertEqual(indexes[storage.STATUS_INDEX][0]["AttributeName"], "status")
        self.assertEqual(indexes[storage.USER_INDEX][0]["AttributeName"], "userKind")
        self.assertEqual(indexes[storage.GALLERY_INDEX][0]["AttributeName"], "gallery")

    def test_job_records_round_trip_without_internal_fields(self):
        self.store.create_job(job("a"))
        self.store.update_job("a", status="running", progress=0.25, error=None)
        saved = self.store.job("a")
        self.assertEqual((saved["status"], saved["progress"]), ("running", 0.25))
        self.assertNotIn("pk", saved)
        self.assertIsNone(self.store.job("missing"))
        with self.assertRaises(ClientError):
            self.store.create_job(job("a"))

    def test_claims_oldest_queued_job_once(self):
        self.store.create_job(job("first"))
        time.sleep(0.002)
        self.store.create_job(job("second"))
        self.assertEqual(self.store.claim("w1")["id"], "first")
        self.assertEqual(self.store.claim("w2")["id"], "second")
        self.assertIsNone(self.store.claim("w3"))
        item = self.store.table.get_item(Key={"pk": "JOB#first"})["Item"]
        self.assertEqual((item["status"], item["owner"]), ("running", "w1"))

    def test_claim_skips_a_job_another_worker_won(self):
        self.store.create_job(job("only"))
        stale = list(self.store._query(storage.STATUS_INDEX, "status", "queued", forward=True))
        self.store.claim("w1")
        with mock.patch.object(self.store, "_query", return_value=iter(stale)):
            self.assertIsNone(self.store.claim("w2"))

    def test_reaps_running_jobs_without_heartbeats(self):
        self.store.create_job(job("stale", status="running"))
        self.store.create_job(job("fresh", status="running"))
        self.store.table.update_item(
            Key={"pk": "JOB#stale"},
            UpdateExpression="SET heartbeatAt = :old",
            ExpressionAttributeValues={":old": 1},
        )
        self.store.reap(60, {"code": "interrupted", "message": "restart"})
        self.assertEqual(self.store.job("stale")["error"]["code"], "interrupted")
        self.assertEqual(self.store.job("fresh")["status"], "running")

    def _publish(self, build_id):
        directory = self.tmp / build_id
        (directory / "views").mkdir(parents=True)
        (directory / "build-guide.pdf").write_bytes(b"%PDF")
        (directory / "parts.json").write_text('{"parts": []}')
        (directory / "views" / "front.png").write_bytes(b"png")
        (directory / "scratch.tmp").write_text("partial")
        self.store.publish(build_id, directory, {"id": build_id, "name": build_id, "ratio": 0.5})

    def test_publish_records_s3_objects_and_serves_them(self):
        self._publish("castle")
        item = self.store.table.get_item(Key={"pk": "BUILD#castle"})["Item"]
        self.assertEqual(item["objects"]["build-guide.pdf"], "builds/castle/build-guide.pdf")
        self.assertIn("views/front.png", item["objects"])
        self.assertNotIn("scratch.tmp", item["objects"])
        self.assertEqual(self.store.build("castle")["ratio"], 0.5)
        self.assertEqual(self.store.asset("castle", "build-guide.pdf"), b"%PDF")
        self.assertIsNone(self.store.asset("castle", "render.png"))
        self.assertIsNone(self.store.asset("missing", "build-guide.pdf"))
        self.assertIsNone(self.store.build("missing"))

    def test_builds_page_newest_first_with_opaque_cursor(self):
        self._publish("older")
        time.sleep(0.002)
        self._publish("newer")
        first, cursor = self.store.builds("", 1)
        self.assertEqual([b["id"] for b in first], ["newer"])
        second, _ = self.store.builds(cursor, 1)
        self.assertEqual([b["id"] for b in second], ["older"])
        for bad in ("not base64!", "WzFd"):
            with self.subTest(cursor=bad), self.assertRaises(ValueError):
                self.store.builds(bad, 1)

    def test_fetch_build_copies_a_published_build_once(self):
        self._publish("parent")
        target = self.tmp / "work" / "parent"
        self.store.fetch_build("parent", target)
        self.assertEqual((target / "views" / "front.png").read_bytes(), b"png")
        self.assertEqual(json.loads((target / "build.json").read_text())["id"], "parent")
        with mock.patch.object(self.store.s3, "download_file") as download:
            self.store.fetch_build("parent", target)
        download.assert_not_called()
        with self.assertRaises(FileNotFoundError):
            self.store.fetch_build("missing", self.tmp / "missing")

    def test_uploads_round_trip_through_s3(self):
        self.store.save_upload("j1", "source.png", b"image")
        self.store.fetch_upload("j1", "source.png", self.tmp / "j1")
        self.assertEqual((self.tmp / "j1" / "source.png").read_bytes(), b"image")

    def test_asset_urls_are_presigned_and_force_downloads_for_models(self):
        self._publish("castle")
        guide = self.store.asset_url("castle", "build-guide.pdf")
        self.assertIn("builds/castle/build-guide.pdf", guide)
        self.assertIn("Signature=", guide)
        self.assertNotIn("response-content-disposition", guide)
        self.assertIn("response-content-disposition", self.store.asset_url("castle", "parts.json"))
        self.assertIsNone(self.store.asset_url("castle", "render.png"))
        self.assertIsNone(self.store.asset_url("missing", "build-guide.pdf"))
        self.store.public_s3 = boto3.client(
            "s3",
            endpoint_url="http://127.0.0.1:9090",
            config=Config(s3={"addressing_style": "path"}),
        )
        self.assertTrue(
            self.store.asset_url("castle", "build-guide.pdf").startswith(
                "http://127.0.0.1:9090/assets/builds/castle/"
            )
        )

    def test_worker_lease_allows_one_start_until_it_goes_stale(self):
        self.assertTrue(self.store.reserve_worker_start(300))
        self.assertFalse(self.store.reserve_worker_start(300))
        self.store.hold_worker("w1")
        self.assertFalse(self.store.acquire_worker("w2"))
        self.store.release_worker("someone-else")
        self.assertFalse(self.store.reserve_worker_start(300))
        self.store.release_worker("w1")
        self.assertTrue(self.store.acquire_worker("w2"))
        self.store.table.update_item(
            Key=AwsStore.WORKER,
            UpdateExpression="SET beatAt = :old",
            ExpressionAttributeValues={":old": 1},
        )
        self.assertTrue(self.store.reserve_worker_start(300))

    def test_has_queued_sees_only_waiting_jobs(self):
        self.assertFalse(self.store.has_queued())
        self.store.create_job(job("running", status="running"))
        self.assertFalse(self.store.has_queued())
        self.store.create_job(job("waiting"))
        self.assertTrue(self.store.has_queued())

    def test_run_worker_task_starts_one_fargate_task_without_public_ip(self):
        ecs = mock.Mock()
        ecs.run_task.return_value = {"tasks": [{"taskArn": "arn:task/1"}], "failures": []}
        with mock.patch.object(self.store.session, "client", return_value=ecs):
            arn = self.store.run_worker_task("cluster", "family:3", ["subnet-a"], ["sg-1"])
            self.assertEqual(arn, "arn:task/1")
            network = ecs.run_task.call_args.kwargs["networkConfiguration"]["awsvpcConfiguration"]
            self.assertEqual(
                network,
                {"subnets": ["subnet-a"], "securityGroups": ["sg-1"], "assignPublicIp": "DISABLED"},
            )
            ecs.run_task.return_value = {"tasks": [], "failures": [{"reason": "RESOURCE:ENI"}]}
            with self.assertRaises(RuntimeError):
                self.store.run_worker_task("cluster", "family:3", ["subnet-a"], ["sg-1"])

    def test_jobs_and_builds_list_per_user_through_the_user_index(self):
        self.store.create_job(job("ada-1", userId="google-1"))
        self.store.create_job(job("bob-1", userId="google-2", status="running"))
        self.store.create_job(job("legacy", status="succeeded"))
        self.assertEqual([j["id"] for j in self.store.jobs("google-1")], ["ada-1"])
        self.assertNotIn("userKind", self.store.jobs("google-1")[0])
        self.assertEqual(self.store.jobs("google-1")[0]["userId"], "google-1")
        self.assertEqual(len(self.store.jobs()), 3)
        self.assertEqual(self.store.pending(), 2)

        for build_id, owner in (("a1", "google-1"), ("b1", "google-2"), ("a2", "google-1")):
            directory = self.tmp / build_id
            directory.mkdir()
            self.store.publish(build_id, directory, {"id": build_id, "userId": owner})
            time.sleep(0.002)
        self._publish("shared")
        mine, _ = self.store.builds("", 10, "google-1")
        self.assertEqual([b["id"] for b in mine], ["a2", "a1"])
        _, cursor = self.store.builds("", 1, "google-1")
        self.assertEqual([b["id"] for b in self.store.builds(cursor, 1, "google-1")[0]], ["a1"])
        self.assertEqual(len(self.store.builds("", 10)[0]), 4)
        item = self.store.table.get_item(Key={"pk": "BUILD#b1"})["Item"]
        self.assertEqual((item["userId"], item["userKind"]), ("google-2", "google-2#build"))
        self.assertNotIn("userKind", self.store.table.get_item(Key={"pk": "BUILD#shared"})["Item"])

    def test_gallery_lists_published_builds_newest_first_until_unpublished(self):
        for build_id, owner in (("a1", "google-1"), ("b1", "google-2")):
            directory = self.tmp / build_id
            directory.mkdir()
            self.store.publish(build_id, directory, {"id": build_id, "userId": owner})
        self.assertEqual(self.store.gallery("", 10), ([], None))
        self.assertIsNone(self.store.set_visibility("a1", "google-2", True, "Bob"))
        self.assertIsNone(self.store.set_visibility("missing", None, True, "Ada"))
        shared = self.store.set_visibility("a1", "google-1", True, "Ada")
        self.assertEqual((shared["visibility"], shared["authorName"]), ("public", "Ada"))
        time.sleep(0.002)
        self.store.set_visibility("b1", "google-2", True, "Bob")
        first, cursor = self.store.gallery("", 1)
        self.assertEqual([b["id"] for b in first], ["b1"])
        self.assertEqual([b["id"] for b in self.store.gallery(cursor, 1)[0]], ["a1"])

        hidden = self.store.set_visibility("b1", "google-2", False, "Bob")
        self.assertEqual(hidden["visibility"], "private")
        self.assertNotIn("publishedAt", hidden)
        self.assertNotIn("gallery", self.store.table.get_item(Key={"pk": "BUILD#b1"})["Item"])
        self.assertEqual([b["id"] for b in self.store.gallery("", 10)[0]], ["a1"])
        demo = self.tmp / "demo"
        demo.mkdir()
        metadata = {"id": "demo", "visibility": "public", "publishedAt": 0}
        self.store.publish("demo", demo, metadata)
        self.assertEqual([b["id"] for b in self.store.gallery("", 10)[0]], ["a1", "demo"])

    def test_users_and_sessions_round_trip_and_expire(self):
        ada = {"id": "google-1", "email": "ada@example.com", "name": "Ada", "picture": None}
        self.store.save_user(ada)
        joined = self.store.table.get_item(Key={"pk": "USER#google-1"})["Item"]["joinedAt"]
        time.sleep(0.002)
        self.store.save_user({**ada, "name": "Ada L."})
        item = self.store.table.get_item(Key={"pk": "USER#google-1"})["Item"]
        self.assertEqual(
            (item["name"], item["email"], item["joinedAt"]), ("Ada L.", ada["email"], joined)
        )

        user = {"id": "google-1", "name": "Ada", "picture": None}
        self.store.create_session("abc", user, 60)
        self.assertEqual(self.store.session_user("abc"), user)
        record = self.store.table.get_item(Key={"pk": "SESSION#abc"})["Item"]
        self.assertEqual(record["ttl"], record["expiresAt"] // 1000)
        self.store.delete_session("abc")
        self.assertIsNone(self.store.session_user("abc"))
        self.store.create_session("old", user, -1)
        self.assertIsNone(self.store.session_user("old"))
        self.assertIsNone(self.store.session_user("missing"))

    def test_from_env_requires_bucket_and_table(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError):
            AwsStore.from_env()
        with mock.patch.dict(
            os.environ, {**FAKE_AWS, "LEGOLIZER_BUCKET": "assets", "LEGOLIZER_TABLE": "legolizer"}
        ):
            store = AwsStore.from_env()
            self.assertEqual(store.bucket, "assets")
            self.assertIs(store.public_s3, store.s3)

    def test_from_env_reads_vercel_credentials_and_public_endpoint(self):
        env = {
            "LEGOLIZER_BUCKET": "assets",
            "LEGOLIZER_TABLE": "legolizer",
            "LEGOLIZER_AWS_ACCESS_KEY_ID": "vercel-key",
            "LEGOLIZER_AWS_SECRET_ACCESS_KEY": "vercel-secret",
            "LEGOLIZER_AWS_REGION": "us-west-2",
            "LEGOLIZER_S3_PUBLIC_ENDPOINT": "http://127.0.0.1:9090",
        }
        with mock.patch.dict(os.environ, env):
            store = AwsStore.from_env()
        self.assertEqual(store.session.get_credentials().access_key, "vercel-key")
        self.assertEqual(store.session.region_name, "us-west-2")
        self.assertEqual(store.public_s3.meta.endpoint_url, "http://127.0.0.1:9090")


class LocalStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "jobs").mkdir()
        self.store = LocalStore(self.root)

    def test_jobs_and_builds_use_the_existing_file_layout(self):
        self.store.create_job(job("a"))
        self.store.update_job("a", status="running")
        self.assertEqual(self.store.job("a")["status"], "running")
        self.assertIsNone(self.store.job("missing"))
        for build_id in ("one", "two"):
            directory = self.root / "models" / build_id
            directory.mkdir(parents=True)
            self.store.publish(build_id, directory, {"id": build_id})
        page, cursor = self.store.builds("", 1)
        self.assertEqual((len(page), cursor), (1, "1"))
        self.assertEqual(self.store.builds(cursor, 1)[1], None)
        with self.assertRaises(ValueError):
            self.store.builds("-1", 1)
        self.assertEqual(self.store.build("one"), {"id": "one"})
        self.assertIsNone(self.store.asset("one", "render.png"))
        self.store.save_upload("j2", "source.png", b"image")
        self.assertEqual((self.root / "models" / "j2" / "source.png").read_bytes(), b"image")

    def test_jobs_and_builds_filter_by_user(self):
        self.store.create_job(job("a", userId="google-1"))
        self.store.create_job(job("b", userId="google-2", status="succeeded"))
        self.assertEqual([j["id"] for j in self.store.jobs("google-1")], ["a"])
        self.assertEqual(self.store.pending(), 1)
        for build_id, owner in (("one", "google-1"), ("two", None)):
            directory = self.root / "models" / build_id
            directory.mkdir(parents=True)
            self.store.publish(build_id, directory, {"id": build_id, "userId": owner})
        self.assertEqual(
            self.store.builds("", 10, "google-1"), ([{"id": "one", "userId": "google-1"}], None)
        )
        self.assertEqual(len(self.store.builds("", 10)[0]), 2)

    def test_gallery_holds_published_builds_newest_first(self):
        for build_id, owner in (("one", "google-1"), ("two", None)):
            directory = self.root / "models" / build_id
            directory.mkdir(parents=True)
            self.store.publish(build_id, directory, {"id": build_id, "userId": owner})
        self.assertIsNone(self.store.set_visibility("one", "google-2", True, "Bob"))
        self.assertIsNone(self.store.set_visibility("missing", None, True, "Ada"))
        self.store.set_visibility("one", "google-1", True, "Ada")
        time.sleep(0.002)
        self.store.set_visibility("two", None, True, "Local workspace")
        page, cursor = self.store.gallery("", 1)
        self.assertEqual(([b["id"] for b in page], cursor), (["two"], "1"))
        self.store.set_visibility("two", None, False, "Local workspace")
        self.assertEqual([b["id"] for b in self.store.gallery("", 10)[0]], ["one"])
        self.assertNotIn("publishedAt", self.store.build("two"))
        with self.assertRaises(ValueError):
            self.store.gallery("-1", 10)

    def test_users_and_sessions_are_files_under_the_root(self):
        self.store.save_user({"id": "google-1", "email": "a@b.c", "name": "Ada", "picture": None})
        self.assertEqual(storage.read_json(self.root / "users" / "google-1.json")["name"], "Ada")
        user = {"id": "google-1", "name": "Ada", "picture": None}
        self.store.create_session("abc", user, 60)
        self.assertEqual(self.store.session_user("abc"), user)
        self.store.delete_session("abc")
        self.store.delete_session("abc")
        self.assertIsNone(self.store.session_user("abc"))
        self.store.create_session("old", user, -1)
        self.assertIsNone(self.store.session_user("old"))


if __name__ == "__main__":
    unittest.main()
