---
name: iter-start
description: Start a new project iteration, sprint, milestone, or focused work cycle by discovering the repository's existing planning conventions, creating or updating an iteration tracking document, seeding scope/acceptance criteria, and preparing a commit-message draft. Use when the user says to start/open/begin an iteration, create an iteration plan, prepare a sprint/milestone work record, or invokes iter-start.
---

# Iter Start

Use this skill to turn a vague "start the next iteration" request into a durable project record that future work can continue from.

## Workflow

### 1. Discover Local Conventions

Before creating files, inspect the repository for existing iteration or planning patterns:

- Agent or contributor instructions: `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `README.md`.
- Existing planning docs: `docs/iterations/`, `docs/iteration*`, `docs/sprints/`, `docs/milestones/`, `CHANGELOG.md`, `ROADMAP.md`, `docs/AGENT_HANDOFF.md`, `.github/ISSUE_TEMPLATE/`.
- Existing naming patterns: `iteration_###_*.md`, `iter###`, `sprint-##`, milestone folders, issue references, branch names.
- Existing validation expectations: test commands, CI config, scripts, package manager commands, Makefile targets.

Follow the strongest local convention. If multiple incompatible conventions exist and the user's request does not disambiguate, ask one concise question before writing.

### 2. Resolve Inputs

Use user-provided values when present:

```text
iteration id / number
title or theme
scope items, issues, tickets, files, or goals
deadline or release target
```

If the iteration id is missing, infer it from the latest existing iteration record or index. Preserve the local style: `007`, `7`, `2026-07`, `sprint-12`, etc.

If the title is missing but the user gave clear scope, derive a short title from the scope. If neither title nor scope is clear, ask for the missing intent instead of inventing a plan.

### 3. Choose the Tracking Location

Use the repository's existing location when one exists.

If there is no convention, create:

```text
docs/iterations/
docs/iterations/README.md
docs/iterations/iteration_<id>_<slug>.md
```

Generate `<slug>` from the title with lowercase ASCII words joined by hyphens. If the title is non-English or does not slug cleanly, use a compact neutral slug such as `plan`, `scope`, or `release`.

### 4. Create the Iteration Record

Prefer the project's existing template. If no template exists, use this compact structure and adapt headings to the project's language:

```markdown
# Iteration <id> - <title>

## Context
Why this work matters now, what prior work it continues, and what constraints shape it.

## Goals
- Concrete outcomes expected by the end of the iteration.

## Scope
- Planned tasks, issues, or areas of code/docs.

## Acceptance Criteria
- Verifiable checks, tests, demos, review expectations, or user-visible outcomes.

## Plan
- Ordered implementation or investigation steps.

## Risks And Questions
- Known unknowns, risky dependencies, or decisions to confirm.

## Progress Notes
- Running notes for discoveries, deviations, and important decisions.

## Closeout
- Leave for iter-finish: validation results, review notes, final summary, follow-ups.
```

Keep the initial record useful but not overbuilt. Seed enough context for another agent to continue, and leave result-oriented sections for the finish pass.

### 5. Update Indexes Or Trackers

If an iteration index, roadmap, README status table, changelog, or handoff doc already tracks iteration state, add the minimal starting entry. Preserve ordering, formatting, links, and date style.

If no such index exists and you created `docs/iterations/`, create a short `docs/iterations/README.md` with an index table or list.

Do not modify broad project status, release notes, or handoff sections unless the local convention clearly expects a start-time entry.

### 6. Guardrails

- Do not run expensive, destructive, production, deployment, or external-service commands just to start an iteration.
- Do not touch secrets, `.env` files, generated outputs, datasets, or large artifacts unless the user explicitly included them in scope.
- Do not commit or push unless the user explicitly asks. Provide a commit-message draft instead.
- If the worktree is dirty, avoid overwriting unrelated user changes; mention relevant pre-existing changes if they affect the iteration record.

### 7. Final Response

Report:

- The iteration id and title.
- Files created or updated.
- Any local convention you followed.
- Any missing information or open questions.
- A commit-message draft, for example:

```text
docs(iter<id>): start <title> iteration
```

End by telling the user that `$iter-finish` can be used when the implementation is ready to close out.
