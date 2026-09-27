---
name: plan-feature
description: >-
  Plan a new Legolizer feature by researching the codebase and writing a plan
  document for later implementation. Use when the user asks to plan a feature,
  write an implementation plan, scope work before coding, or produce a feature
  design doc. Does not implement the feature.
---

# Plan a feature

Produce a concrete plan document. Do **not** implement the feature under this
skill unless the user explicitly asks to proceed after the plan.

## Mandate

1. Clarify the goal if the request is ambiguous (one short question max, then draft).
2. Read the nearest relevant `AGENTS.md` files and skim the touch points.
3. Write a plan markdown file under `.cursor/plans/`.
4. Summarize the plan path and open questions in the chat reply.

Do not commit unless the user asks. Do not expand into unrelated refactors.

## Where to write

```
.cursor/plans/<slug>.md
```

- `<slug>`: lowercase kebab-case from the feature name (e.g. `region-refine-ui`)
- If the file exists, update it in place (keep a short revision note at the top)
- Never put secrets, `.env` values, or `TASKS.md` content in the plan

## Research (keep it light)

Before writing:

1. Map likely layers: `src/legolizer/`, `src/frontend/`, `api/`, `src/infra/`, `tests/`
2. Note contracts: OpenAPI (`src/frontend/api/openapi.json`), catalog whitelist,
   storage/schema if data changes
3. Skim existing issues (`gh issue list`) only if the feature might already be filed
4. Call out AGENTS invariants that constrain the design (cost, parity, no invented parts)

## Plan document template

Use this structure (fill every section; write `none` / `n/a` when empty):

```markdown
# Plan: <Feature title>

Date: YYYY-MM-DD
Status: draft | ready
Branch suggestion: feat/<slug>

## Goal
<1–3 sentences: user-visible outcome>

## Non-goals
- …

## Context
- Relevant paths / modules
- Related issues (links) or `none`

## Approach
<How it should work end-to-end; prefer extending existing modules>

## Touch points
| Area | Paths | Change |
| --- | --- | --- |
| Python | … | … |
| Frontend | … | … |
| API / OpenAPI | … | … |
| Infra | … | … |
| Tests | … | … |
| AGENTS / docs | … | … |

## Steps
1. …
2. …
3. …

## Risks and constraints
- AGENTS / product constraints
- Edge cases

## Test plan
- Unit / integration checks to add or run
- Manual smoke steps

## Open questions
- … or `none`

## Out of scope / follow-ups
- File as issues later; do not implement in the feature PR
```

## After writing

Reply briefly with:

- Path to the plan file
- One-sentence goal
- Open questions that block implementation (if any)

Stop. Wait for the user to approve or ask for implementation.
