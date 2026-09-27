# AGENTS.md — `src/infra/`

Deployment: generation container, local compose stack, AWS CDK app, and the
validate → deploy → destroy scripts. The Vercel API entry point lives at the
repo root (`api/index.py`, `vercel.json`). Architecture, costs, runbook:
[README.md](README.md). Setup steps: [instructions.md](../../instructions.md) §8–9.

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../AGENTS.md](../../AGENTS.md)

## Map

| Path | Role |
| --- | --- |
| `docker/` | `Dockerfile` (+ allowlist `.dockerignore`), `compose.yaml`, `lpub3d-headless` |
| `container.env` | Runtime env shared by compose, the Fargate task, and Vercel (`deploy-frontend.sh`) |
| `table-schema.json` | DynamoDB schema shared by CDK, compose init, and `tests/test_storage.py` |
| `cdk/` | TypeScript CDK app (`tsx`, no build output); `LegolizerData`, `LegolizerWorker` |
| `scripts/` | `validate-local.sh`, `smoke_test.py`, `deploy.sh`, `deploy-frontend.sh`, `destroy.sh` |

## Invariants

- **Cost.** This is a hackathon demo: no NAT gateway, load balancer, VPC
  endpoints, public IPv4, or always-on compute. The worker is IPv6-only and
  runs only while jobs exist. Anything that adds a fixed monthly charge needs
  a human decision.
- **One worker.** At most one Fargate task, enforced by the DynamoDB `WORKER`
  lease (`server.ensure_worker` / `run_workers`). Keep the ordering: the API
  queues then reserves; the worker releases then re-checks the queue.
- **Parity.** Do not add AWS-only runtime fixes. New runtime settings go in
  `container.env` (or the image). Local and AWS differ only in endpoints,
  credentials, the dual-stack flag, and the idle timeout. Keep the container
  at 12 GB or more (`MIN_MEMORY_MIB`).
- **Gate.** `deploy.sh` pushes only the image ID recorded by a passing
  `validate-local.sh`. Keep that check.
- **Secrets.** Provider keys go to Secrets Manager via a temp file. The Vercel
  function's AWS key is created by `deploy-frontend.sh` and piped straight into
  `vercel env add`. Never echo either, bake them into the image, or put them in
  CDK context or `VITE_*`.
- **Vercel limits.** The function has 4.5 MB request and response limits, so
  assets are presigned redirects and images are capped at 3 MB.
- **Schema changes.** Edit `table-schema.json` only; `storage.AwsStore` must
  match the keys and index names.
- Renderer versions are pinned (LPub3D deb URL + SHA-512, LDView from that
  package, uv image tag). Bump them together and rerun `validate-local.sh`.
- CI: `.github/workflows/infra.yml` (path-filtered) runs CDK synth and
  `validate-local.sh`. `ci.yml` is unchanged.

## Agent backlog

_None yet._
