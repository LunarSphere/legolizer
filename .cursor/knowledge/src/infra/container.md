# src/infra/container.env

## Role
Shared runtime env for compose, Fargate worker, and Vercel function copy.

## Key responsibilities
- LEGOLIZER_BACKEND and queue knobs
- IMAGE_PROVIDER=grok
- No secrets in this file

## Related
- src/infra/scripts/deploy.sh
- src/infra/docker/compose.yaml

## Last updated
2026-09-27 (#116)
