# API and storage

## Summary
HTTP API for Studio and Vercel: jobs, builds, sessions, and assets. Local mode
uses an in-process worker and files; AWS mode uses DynamoDB, S3, and on-demand
Fargate. Auth can be off or Google with hashed session cookies.

## Key modules / paths
- `src/legolizer/server.py` — HTTP Handler, queue, access rules
- `src/legolizer/auth.py` — Google ID tokens, session cookies
- `src/legolizer/storage.py` — LocalStore / AwsStore
- `api/index.py` — thin Vercel adapter over `server.Handler` + AwsStore
- `src/frontend/api/openapi.json` — HTTP contract for the client

## Invariants
- Behavior stays in `server.py`; `api/index.py` stays thin
- Vercel uses `LEGOLIZER_AWS_*` (not reserved `AWS_*` names)
- With Google auth: users `google-<sub>`; other users’ jobs/builds are 404 not 403
- OpenAPI and `src/frontend/src/api.js` stay aligned with the API

## Last updated
2026-09-27 (#116)
