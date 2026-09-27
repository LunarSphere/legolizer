# src/legolizer/storage.py

## Role
LocalStore and AwsStore for jobs, builds, users, sessions, and S3 assets.

## Key responsibilities
- DynamoDB conditional claims and worker lease
- Presigned URLs; ecs:RunTask wiring
- byUser / byGallery indexes

## Related
- src/legolizer/server.py
- src/infra/table-schema.json

## Last updated
2026-09-27 (#116)
