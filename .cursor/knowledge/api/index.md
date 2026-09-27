# api/index.py

## Role
Vercel Python function adapter exposing legolizer.server.Handler with AwsStore.

## Key responsibilities
- Thin wrapper; behavior lives in server.py
- Sets allowed hosts/origins from Vercel URLs
- LEGOLIZER_AWS_* credentials

## Related
- src/legolizer/server.py
- vercel.json

## Last updated
2026-09-27 (#116)
