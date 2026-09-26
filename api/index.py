"""Vercel function: the container's request handler, backed by DynamoDB, S3, and on-demand workers."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("LEGOLIZER_DATA_DIR", "/tmp/legolizer")
_hosts = [
    os.environ[name]
    for name in ("VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_BRANCH_URL", "VERCEL_URL")
    if os.getenv(name)
]
os.environ.setdefault("LEGOLIZER_ALLOWED_HOSTS", ",".join(_hosts))
os.environ.setdefault("LEGOLIZER_ALLOWED_ORIGINS", ",".join(f"https://{h}" for h in _hosts))

from legolizer import server  # noqa: E402
from legolizer.storage import AwsStore  # noqa: E402

server.REMOTE = AwsStore.from_env()
try:
    server.initialize()
except Exception as exc:
    print(f"Demo build seeding skipped: {type(exc).__name__}: {exc}", flush=True)


class handler(server.Handler):
    pass
