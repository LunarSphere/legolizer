#!/usr/bin/env bash
# Push the locally validated image to ECR and deploy both CDK stacks.
#   src/infra/scripts/deploy.sh
# Optional: LEGOLIZER_IDLE_MINUTES (worker stops after this long without jobs, default 15),
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

npx cdk deploy LegolizerData --outputs-file "$OUT/Data-outputs.json"

SECRET_FILE="$(mktemp)"
trap 'rm -f "$SECRET_FILE"' EXIT
chmod 600 "$SECRET_FILE"
node -e '
  const e = process.env;
  const keys = {
    OPENAI_API_KEY: e.OPENAI_API_KEY || "",
    ANTHROPIC_API_KEY: e.ANTHROPIC_API_KEY || e.CLAUDE_API_KEY || "",
    GROK_API_KEY: e.GROK_API_KEY || e.XAI_API_KEY || "",
  };
  if (!Object.values(keys).some(Boolean)) console.error("No provider keys set: only shape-program jobs will run.");
  require("fs").writeFileSync(process.argv[1], JSON.stringify(keys));
' "$SECRET_FILE"
aws secretsmanager put-secret-value --secret-id "$(output Data SecretArn)" \
  --secret-string "file://$SECRET_FILE" >/dev/null

REPOSITORY="$(output Data RepositoryUri)"
TAG="$(git -C "$ROOT" rev-parse --short HEAD)-${IMAGE_ID:7:12}"
aws ecr get-login-password | docker login --username AWS --password-stdin "${REPOSITORY%%/*}"
docker tag legolizer:local "$REPOSITORY:$TAG"
docker push "$REPOSITORY:$TAG"

aws ecs put-account-setting --name dualStackIPv6 --value enabled >/dev/null
npx cdk deploy LegolizerWorker --outputs-file "$OUT/Worker-outputs.json" \
  -c imageTag="$TAG" -c idleMinutes="${LEGOLIZER_IDLE_MINUTES:-15}"

echo "Worker deployed (starts on demand). Next: src/infra/scripts/deploy-frontend.sh"
