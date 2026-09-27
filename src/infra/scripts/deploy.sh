#!/usr/bin/env bash
# Push the locally validated image to ECR and deploy both CDK stacks.
#   src/infra/scripts/deploy.sh
# Optional: LEGOLIZER_IDLE_MINUTES (worker stops after this long without jobs, default 15),
# LEGOLIZER_SKIP_SECRETS=1 (leave the stored provider keys alone; set by CD),
# AWS_PROFILE / AWS_REGION. Then run deploy-frontend.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="$ROOT/builds/infra"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

IMAGE_ID="$(docker image inspect legolizer:local --format '{{.Id}}' 2>/dev/null || true)"
VALIDATED_ID="$(node -p "require('$OUT/validated.json').imageId" 2>/dev/null || true)"
if [ -z "$IMAGE_ID" ] || [ "$IMAGE_ID" != "$VALIDATED_ID" ]; then
  echo "legolizer:local has not passed src/infra/scripts/validate-local.sh; run it first." >&2
  exit 1
fi

aws sts get-caller-identity --query Account --output text >/dev/null
export AWS_REGION="${AWS_REGION:-$(aws configure get region || echo us-east-1)}"
export CDK_DEFAULT_REGION="$AWS_REGION"
mkdir -p "$OUT"
cd "$ROOT/src/infra/cdk"
[ -d node_modules ] || npm ci
output() { node -p "require('$OUT/$1-outputs.json').Legolizer$1.$2"; }
TAG="$(git -C "$ROOT" rev-parse --short HEAD)-${IMAGE_ID:7:12}"
# Synthesize the worker too, or CDK drops the data exports the deployed worker imports
# and CloudFormation rolls the data stack back.
CONTEXT=(-c imageTag="$TAG" -c idleMinutes="${LEGOLIZER_IDLE_MINUTES:-15}")

npx cdk deploy LegolizerData --require-approval never --outputs-file "$OUT/Data-outputs.json" \
  "${CONTEXT[@]}"

SECRET_FILE="$(mktemp)"
trap 'rm -f "$SECRET_FILE"' EXIT
chmod 600 "$SECRET_FILE"
if [ "${LEGOLIZER_SKIP_SECRETS:-0}" = 1 ]; then
  echo "LEGOLIZER_SKIP_SECRETS=1: keeping the stored provider keys."
elif node -e '
  const e = process.env;
  const keys = {
    OPENAI_API_KEY: e.OPENAI_API_KEY || "",
    GROK_API_KEY: e.GROK_API_KEY || e.XAI_API_KEY || "",
  };
  if (!Object.values(keys).some(Boolean)) process.exit(1);
  require("fs").writeFileSync(process.argv[1], JSON.stringify(keys));
' "$SECRET_FILE"; then
  aws secretsmanager put-secret-value --secret-id "$(output Data SecretArn)" \
    --secret-string "file://$SECRET_FILE" >/dev/null
else
  echo "No provider keys set: keeping the stored provider keys." >&2
fi

REPOSITORY="$(output Data RepositoryUri)"
aws ecr get-login-password | docker login --username AWS --password-stdin "${REPOSITORY%%/*}"
docker tag legolizer:local "$REPOSITORY:$TAG"
docker push "$REPOSITORY:$TAG"

DUAL_STACK="$(aws ecs list-account-settings --name dualStackIPv6 --effective-settings \
  --query 'settings[0].value' --output text)"
[ "$DUAL_STACK" = enabled ] || aws ecs put-account-setting --name dualStackIPv6 --value enabled >/dev/null
npx cdk deploy LegolizerWorker --require-approval never --outputs-file "$OUT/Worker-outputs.json" \
  "${CONTEXT[@]}"

echo "Worker deployed (starts on demand). Next: src/infra/scripts/deploy-frontend.sh"
