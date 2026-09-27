# AGENTS.md — `.cursor/skills/`

Project Agent Skills for Legolizer. Each skill is a directory with `SKILL.md`
(YAML frontmatter + instructions). Parent: [../AGENTS.md](../AGENTS.md).
Root: [../../AGENTS.md](../../AGENTS.md).

Authoring rules: Cursor create-skill guidance (concise, third-person
`description` with WHAT + WHEN, progressive disclosure).

## Skills

| Skill | Use when |
| --- | --- |
| [`debug/`](debug/SKILL.md) | Evaluate correctness, fix bugs, report every change |
| [`code-quality-review/`](code-quality-review/SKILL.md) | PR or change review vs AGENTS + tooling |
| [`check-github-actions/`](check-github-actions/SKILL.md) | Read-only GitHub Actions / CI-CD status |
| [`plan-feature/`](plan-feature/SKILL.md) | Write a feature plan doc under `.cursor/plans/` (no impl) |
| [`open-ticket/`](open-ticket/SKILL.md) | File issue, assign @me, branch, then implement (needs feature) |
| [`review-new-changes/`](review-new-changes/SKILL.md) | Summarize diff vs main (no commit/push) |

## Conventions

- Keep each `SKILL.md` under ~500 lines; link out to nested `AGENTS.md` and
  workflow files instead of duplicating runbooks.
- Never instruct the agent to print secrets or weaken cost/parity invariants.
- `check-github-actions` is **read-only**: list/view runs and logs only; never
  re-run, dispatch, or mutate GitHub/Actions settings.
- `review-new-changes` is **read-only**: summarize vs `main`; never commit or push.
- Review/check skills (`code-quality-review`, `check-github-actions`,
  `review-new-changes`) must save a run log under `.cursor/logs/` every
  invocation (see [../logs/AGENTS.md](../logs/AGENTS.md)).
- When adding a skill, update this table in the **same** change and link from
  root [AGENTS.md](../../AGENTS.md) if the skills map changes.

## Agent backlog

_None yet._
