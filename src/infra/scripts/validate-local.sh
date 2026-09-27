#!/usr/bin/env bash
# Build the generation image, run it against DynamoDB Local + S3Mock, and smoke-test the
# queue and outputs. deploy.sh refuses to push an image this has not passed.
#   src/infra/scripts/validate-local.sh [--keep] [--live]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/src/infra/docker/compose.yaml")
[ -f "$ROOT/.env" ] && COMPOSE+=(--env-file "$ROOT/.env")
KEEP=0
SMOKE_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --keep) KEEP=1 ;;
    --live) SMOKE_ARGS+=(--live) ;;
    *) echo "usage: $0 [--keep] [--live]" >&2; exit 2 ;;
  esac
done

cleanup() { [ "$KEEP" = 1 ] || "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker build --platform linux/amd64 -f "$ROOT/src/infra/docker/Dockerfile" -t legolizer:local "$ROOT"
"${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
"${COMPOSE[@]}" up -d

cd "$ROOT"
uv run python src/infra/scripts/smoke_test.py \
  --api http://127.0.0.1:8000 \
  --table legolizer --bucket legolizer-assets \
  --dynamodb-endpoint http://127.0.0.1:8900 --s3-endpoint http://127.0.0.1:9090 \
  ${SMOKE_ARGS[@]+"${SMOKE_ARGS[@]}"}

mkdir -p "$ROOT/builds/infra"
cat > "$ROOT/builds/infra/validated.json" <<EOF
{"imageId": "$(docker image inspect legolizer:local --format '{{.Id}}')", "commit": "$(git rev-parse HEAD)", "dirty": $([ -n "$(git status --porcelain)" ] && echo true || echo false), "validatedAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
EOF
echo "Validated legolizer:local -> builds/infra/validated.json"
