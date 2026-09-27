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

## Conventions

- Keep each `SKILL.md` under ~500 lines; link out to nested `AGENTS.md` and
  workflow files instead of duplicating runbooks.
- Never instruct the agent to print secrets or weaken cost/parity invariants.
- `check-github-actions` is **read-only**: list/view runs and logs only; never
  re-run, dispatch, or mutate GitHub/Actions settings.
- When adding a skill, update this table in the **same** change and link from
  root [AGENTS.md](../../AGENTS.md) if the skills map changes.

## Agent backlog

_None yet._
