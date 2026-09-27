# Infra and deploy

## Summary
Docker image, local compose, AWS CDK (data/worker/deploy), and scripts to
validate then deploy. CD runs path-filtered on `main` via GitHub Actions; Vercel
hosts the Studio static site and API function.

## Key modules / paths
- `src/infra/container.env` — shared runtime knobs (compose / Fargate / Vercel)
- `src/infra/table-schema.json` — DynamoDB schema for AwsStore
- `src/infra/cdk/` — LegolizerData, LegolizerWorker, LegolizerDeploy
- `src/infra/scripts/validate-local.sh` — image + smoke gate
- `src/infra/scripts/deploy.sh` — stacks + image; `LEGOLIZER_SKIP_SECRETS` for CD
- `src/infra/scripts/deploy-frontend.sh` — Vercel env wiring
- `vercel.json` — frontend build + `/api/v1` rewrite
- `.github/workflows/{ci,infra,deploy}.yml` — CI / synth+smoke / CD

## Invariants
- Cost: no NAT/ALB/always-on without human decision
- Parity: runtime settings in `container.env`, not AWS-only hacks
- Never echo provider keys; CD keeps secrets with `LEGOLIZER_SKIP_SECRETS=1`

## Last updated
2026-09-27 (#116)
