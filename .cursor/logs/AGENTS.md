# AGENTS.md — `.cursor/logs/`

Run logs from review/check skills. Parent: [../AGENTS.md](../AGENTS.md).

## Layout

| Path | Role |
| --- | --- |
| `<skill>-<YYYYMMDD-HHMMSS>Z.md` | One file per skill invocation (UTC time) |

Skills that **must** write a log on every run:

- `code-quality-review`
- `check-github-actions`
- `review-new-changes`
- `explore-knowledge`

## Conventions

- Write the same report body shown in chat (plus a short header: skill, UTC
  time, branch, `HEAD` short SHA).
- No secrets, tokens, or `.env` values.
- Working artifacts: do not commit log files unless the user asks.
- Creating the log file is required; it is not a platform mutation.

## Agent backlog

_None yet._
