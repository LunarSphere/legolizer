# src/legolizer/server.py

## Role
HTTP API, job queue, sessions, and asset serving for Studio and Vercel.

## Key responsibilities
- Local ThreadPool worker or AWS DynamoDB queue + Fargate
- Auth-gated generation when google
- Owns/readable/public_build access rules

## Related
- src/legolizer/storage.py
- src/legolizer/auth.py
- api/index.py

## Last updated
2026-09-27 (#116)
