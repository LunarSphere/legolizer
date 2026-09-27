#!/usr/bin/env bash
# Delete every CDK-managed AWS resource, including saved builds, images, and metadata.
#   src/infra/scripts/destroy.sh [--yes]
# The Vercel project is left alone; its API calls fail until the next deploy.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="$ROOT/builds/infra"
YES=0
for arg in "$@"; do
  case "$arg" in
    --yes) YES=1 ;;
    *) echo "usage: $0 [--yes]" >&2; exit 2 ;;
  esac
done

if [ "$YES" != 1 ]; then
  read -r -p "Permanently delete the Legolizer AWS stacks, S3 assets, and DynamoDB metadata? Type 'destroy': " answer
  [ "$answer" = destroy ] || { echo "Aborted."; exit 1; }
fi

aws sts get-caller-identity --query Account --output text >/dev/null
export CDK_DEFAULT_REGION="${AWS_REGION:-$(aws configure get region || echo us-east-1)}"

# CloudFormation cannot delete a cluster with a running task or a user with access keys.
if [ -f "$OUT/Worker-outputs.json" ]; then
  output() { node -p "require('$OUT/Worker-outputs.json').LegolizerWorker.$1"; }
  CLUSTER="$(output ClusterName)"
  TASKS="$(aws ecs list-tasks --cluster "$CLUSTER" --query 'taskArns[]' --output text 2>/dev/null || true)"
  if [ -n "$TASKS" ] && [ "$TASKS" != None ]; then
    for task in $TASKS; do aws ecs stop-task --cluster "$CLUSTER" --task "$task" >/dev/null; done
    # shellcheck disable=SC2086
    aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks $TASKS
  fi
  USER_NAME="$(output VercelUserName)"
  for key in $(aws iam list-access-keys --user-name "$USER_NAME" --query 'AccessKeyMetadata[].AccessKeyId' --output text 2>/dev/null); do
    aws iam delete-access-key --user-name "$USER_NAME" --access-key-id "$key"
  done
fi

cd "$ROOT/src/infra/cdk"
[ -d node_modules ] || npm ci
# imageTag only lets the worker stack synthesize so CDK can find it; nothing is built.
npx cdk destroy --all --force -c imageTag=destroy
rm -f "$OUT/Data-outputs.json" "$OUT/Worker-outputs.json"
echo "Destroyed the Legolizer AWS stacks."
