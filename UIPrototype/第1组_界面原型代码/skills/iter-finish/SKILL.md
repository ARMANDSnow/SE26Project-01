---
name: iter-finish
description: Finish or close out a project iteration, sprint, milestone, or focused work cycle by discovering the repository's closeout conventions, running appropriate validation, reviewing changes, updating iteration/status/handoff documentation, recording follow-ups, and preparing a commit-message draft. Use when the user says to finish/close/wrap an iteration, complete a sprint/milestone, summarize validation, or invokes iter-finish.
---

# Iter Finish

Use this skill to make an iteration end cleanly: verified, documented, and easy for the next person or agent to resume from.

## Workflow

### 1. Locate The Iteration

Read the repository's local guidance first: `AGENTS.md`, `README.md`, `CONTRIBUTING.md`, project docs, and existing iteration records.

Resolve the target iteration from the user's id/title when provided. If omitted, infer the current or latest open iteration from:

- `docs/iterations/README.md`, `docs/iterations/`, `docs/sprints/`, `docs/milestones/`.
- Open sections named "Progress", "Closeout", "Acceptance Result", "Current Iteration", or similar.
- Branch name, issue title, milestone, or recent modified iteration doc.

If more than one iteration could be current, ask one concise question before editing closeout docs.

### 2. Inspect The Work

Review the diff and project state before running checks:

- Check `git status` and identify unrelated pre-existing changes.
- Inspect touched files and summarize the actual change set.
- Compare implementation against the iteration goals and acceptance criteria.
- Note user changes separately and do not revert them.

### 3. Run Appropriate Validation

Discover validation commands from local conventions:

- `README.md`, `AGENTS.md`, `CONTRIBUTING.md`.
- `package.json`, `pyproject.toml`, `Makefile`, `justfile`, `Taskfile.yml`, CI workflow files.
- Existing iteration records and scripts.

Run the smallest meaningful validation set that matches the change risk:

- Unit tests or targeted tests for narrow code changes.
- Lint/typecheck/build when the project normally requires them.
- Smoke tests or browser checks for user-facing workflows.
- Documentation/render checks for document-only or generated artifacts.

Do not run commands that deploy, mutate production data, call paid/real external services, or require secrets unless the user explicitly authorized them.

If validation fails, stop before marking the iteration complete. Report the failure, keep any factual notes already gathered, and do not write "complete" status unless the user explicitly asks to record a failed closeout.

### 4. Review For Risks

Do a focused closeout review:

- Correctness: regressions, edge cases, error handling, missing tests.
- Integration: changed contracts, migrations, config, docs, release notes.
- Security and privacy: secrets, credentials, unsafe logging, permission changes, data exposure.
- Operations: deployment risk, performance, backwards compatibility, rollback concerns.

For high-risk changes, broaden the review with available review tools, subagents, or a second pass. Keep the review read-only unless fixing issues is part of the user's request.

### 5. Update Closeout Documentation

Follow existing project format. Common updates include:

- Iteration record: final summary, validation commands and results, review findings, files changed, acceptance status, follow-up items.
- Iteration index: status/date/checkmark/link updates.
- README or roadmap: current status, latest completed iteration, user-visible progress.
- Changelog or release notes: externally meaningful changes only.
- Handoff doc: next steps, known risks, useful commands, unresolved decisions.

Use the real current date from the environment and preserve the repository's date format. Avoid rewriting unrelated prose.

If the project has no closeout structure, append or fill a `Closeout` section in the iteration record:

```markdown
## Closeout

### Summary
- What shipped or changed.

### Validation
- `<command>`: passed/failed/skipped with key output.

### Review
- Main risks checked and findings.

### Follow-ups
- Items intentionally deferred.
```

### 6. Commit And Push Guardrails

Do not commit or push unless the user explicitly asks. Provide one or more commit-message drafts based on the actual change set.

For a docs-only closeout, use a message like:

```text
docs(iter<id>): close out <title> iteration
```

If code changes are still unstaged or uncommitted, call that out and suggest separating implementation commits from the final documentation closeout when the project convention favors it.

### 7. Final Response

Report:

- Iteration closed and files updated.
- Validation commands run and pass/fail/skipped status.
- Review findings or "no blocking findings".
- Follow-ups or residual risks.
- Commit-message draft.

If validation could not be run, explain why and whether docs were left unmarked or marked as partial.
