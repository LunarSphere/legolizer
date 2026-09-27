# AGENTS.md — `api/`

Vercel function entry point. `index.py` exposes `legolizer.server.Handler` as
`handler` with `LEGOLIZER_BACKEND=aws` semantics (DynamoDB + S3 + on-demand
Fargate worker). Routing and bundle exclusions: [`../vercel.json`](../vercel.json).
Deployment details: [`../src/infra/README.md`](../src/infra/README.md).

Parent / root: [../AGENTS.md](../AGENTS.md)

- Keep this file a thin adapter. API behavior belongs in `src/legolizer/server.py`
  so the container and Vercel serve the same code.
- The function has no renderers or provider keys; jobs run on the worker.
- Vercel reserves `AWS_*` env names, so credentials arrive as `LEGOLIZER_AWS_*`
  (read by `AwsStore.from_env`).
- Covered by `tests/test_server.py` (`test_vercel_entry_point_…`).

## Agent backlog

_None yet._
