#!/usr/bin/env bash
# Deploy Legolizer Studio and its API function to Vercel, wired to the AWS stacks.
#   src/infra/scripts/deploy-frontend.sh [--smoke]
# Needs builds/infra/{Data,Worker}-outputs.json from deploy.sh, `vercel login`, and
# LEGOLIZER_GOOGLE_CLIENT_ID (or LEGOLIZER_AUTH=off).
# Rotates the Vercel function's AWS access key on every run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="$ROOT/builds/infra"
SMOKE=0
for arg in "$@"; do
  case "$arg" in
    --smoke) SMOKE=1 ;;
    *) echo "usage: $0 [--smoke]" >&2; exit 2 ;;
  esac
done
for stack in Data Worker; do
  [ -f "$OUT/$stack-outputs.json" ] || { echo "Run src/infra/scripts/deploy.sh first." >&2; exit 1; }
done
AUTH="${LEGOLIZER_AUTH:-google}"
if [ "$AUTH" = google ] && [ -z "${LEGOLIZER_GOOGLE_CLIENT_ID:-}" ]; then
  echo "Export LEGOLIZER_GOOGLE_CLIENT_ID (instructions.md §9), or LEGOLIZER_AUTH=off to deploy without accounts." >&2
  exit 1
fi
output() { node -p "require('$OUT/$1-outputs.json').Legolizer$1.$2"; }
vercel() { npx --yes vercel@60 "$@"; }
export AWS_REGION="${AWS_REGION:-$(aws configure get region || echo us-east-1)}"

cd "$ROOT"
[ -f .vercel/project.json ] || vercel link --yes --project "${VERCEL_PROJECT:-legolizer}"

set_env() {
  vercel env rm "$1" production --yes >/dev/null 2>&1 || true
  printf '%s' "$2" | vercel env add "$1" production ${3:+"$3"} >/dev/null
  echo "set $1"
}

while IFS='=' read -r name value; do
  case "$name" in ''|'#'*) continue ;; esac
  set_env "$name" "$value"
done < src/infra/container.env
set_env LEGOLIZER_AUTH "$AUTH"
if [ "$AUTH" = google ]; then
  set_env LEGOLIZER_GOOGLE_CLIENT_ID "$LEGOLIZER_GOOGLE_CLIENT_ID"
fi
set_env LEGOLIZER_AWS_REGION "$AWS_REGION"
set_env LEGOLIZER_BUCKET "$(output Data BucketName)"
set_env LEGOLIZER_TABLE "$(output Data TableName)"
set_env LEGOLIZER_WORKER_CLUSTER "$(output Worker ClusterName)"
set_env LEGOLIZER_WORKER_TASK_DEFINITION "$(output Worker TaskDefinitionFamily)"
set_env LEGOLIZER_WORKER_SUBNETS "$(output Worker Subnets)"
set_env LEGOLIZER_WORKER_SECURITY_GROUPS "$(output Worker SecurityGroup)"

USER_NAME="$(output Worker VercelUserName)"
for key in $(aws iam list-access-keys --user-name "$USER_NAME" --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
  aws iam delete-access-key --user-name "$USER_NAME" --access-key-id "$key"
done
KEY_JSON="$(aws iam create-access-key --user-name "$USER_NAME" --output json)"
set_env LEGOLIZER_AWS_ACCESS_KEY_ID "$(node -p 'JSON.parse(process.argv[1]).AccessKey.AccessKeyId' "$KEY_JSON")"
set_env LEGOLIZER_AWS_SECRET_ACCESS_KEY "$(node -p 'JSON.parse(process.argv[1]).AccessKey.SecretAccessKey' "$KEY_JSON")" --sensitive
unset KEY_JSON

vercel deploy --prod --yes
if [ "$SMOKE" = 1 ]; then
  # Deployment-specific URLs sit behind Vercel Authentication; test the production domain.
  SITE="${LEGOLIZER_STUDIO_URL:?Set LEGOLIZER_STUDIO_URL to the production domain, e.g. https://legolizer.vercel.app}"
  uv run python src/infra/scripts/smoke_test.py --api "$SITE" --origin "$SITE" --remote-worker
fi
