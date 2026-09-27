# src/infra/scripts/validate-local.sh

## Role
Build the worker image and run the local queue smoke test; gate for deploy.

## Key responsibilities
- Records validated image id
- Required before deploy.sh push

## Related
- src/infra/scripts/deploy.sh
- src/infra/scripts/smoke_test.py

## Last updated
2026-09-27 (#116)
