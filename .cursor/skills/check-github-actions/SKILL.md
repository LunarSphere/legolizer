---
name: check-github-actions
description: >-
  Read-only GitHub Actions status for Legolizer (ci.yml, infra.yml, deploy.yml).
  Use when the user asks about CI/CD health, failing checks, workflow runs, or
  Actions status. Never trigger workflows, re-run jobs, or change GitHub/AWS/
  Vercel settings.
---

# Check GitHub Actions (read-only)

Repo workflows: `.github/workflows/ci.yml`, `infra.yml`, `deploy.yml`. Guide:
`.github/AGENTS.md`.

## Hard rule — observe only

This skill **views and reports** Actions status. It must **not** change anything.

**Forbidden:**

- `gh workflow run`, re-run failed jobs, cancel runs, or empty commits to trigger CI
- Editing workflow files, secrets, variables, or environments “to fix” a run
- Deploy scripts, AWS/Vercel CLI, or any platform mutation

**Allowed:**

- `gh run list`, `gh run view`, `gh run view --log-failed` (read logs only)
- `gh pr checks` when a PR is in scope
- Reading workflow YAML in the repo for context

## Workflows (what each means)

| Workflow | File | Typical trigger | Role |
| --- | --- | --- | --- |
| CI | `ci.yml` | PR + push to `main` | Ruff, unittest + coverage/diff-cover, frontend lint/build |
| Infra | `infra.yml` | Path-filtered PR/`main` | CDK synth + `validate-local.sh` |
| Deploy | `deploy.yml` | Path-filtered push to `main`, `workflow_dispatch` | Fargate worker CD; optional Vercel job |

## Investigation order

### 1. Recent runs

```sh
gh run list --limit 15
gh run list --workflow=ci.yml --limit 10
gh run list --workflow=infra.yml --limit 10
gh run list --workflow=deploy.yml --limit 10
```

### 2. Failed or interesting run

```sh
gh run view <id>
gh run view <id> --json conclusion,status,jobs,displayTitle,url,event,headBranch
gh run view <id> --log-failed
```

### 3. PR checks (if reviewing a PR)

```sh
gh pr checks <number>
```

### 4. Interpret (do not change)

- **success** — green for that workflow/job
- **failure** — report failing job/step from `--log-failed`; do not re-run
- **cancelled** — often superseded by a newer run on the same concurrency group
- **skipped** — job `if:` false (e.g. missing `AWS_DEPLOY_ROLE_ARN`, path filter, or `VERCEL_DEPLOY`)
- Deploy `worker` needs `vars.AWS_DEPLOY_ROLE_ARN`; Deploy `vercel` needs prior worker success and `vars.VERCEL_DEPLOY == 'true'`

## Output format

```markdown
## Status
Healthy / Degraded / Broken / Unknown

## How Actions are operating
(recent CI / Infra / Deploy conclusions; notable skips or cancels)

## Evidence
(run ids, URLs, failing job/step summaries — no secrets)

## Likely cause (if degraded/broken)
## Recommendations (do not apply)
```
