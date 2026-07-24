# Iteration iter17 - Workspace Chat Context

## Context

The task list identifies a gap between the existing personal library/research project surfaces and general Chat: Chat cannot select a bounded folder or project context. This iteration follows iter16 and implements only the first priority, Workspace, without changing the fixed Research Agent workflow.

The worktree already contains unrelated arXiv source-parser changes. Those changes are out of scope and must be preserved.

## Goals

- Add an owner-only Workspace abstraction.
- Allow a Workspace to bind exactly one existing research project or library folder.
- Allow general Chat threads to select a Workspace.
- Keep existing paper Chat and unscoped general Chat behavior compatible.
- Make the selected Workspace visible in the Chat UI and persisted with the thread.

## Scope

- Schema migration from v9 to v10.
- Workspace repository/service and API endpoints.
- General Chat thread creation and Chat request context binding.
- Frontend types, API helpers, query hooks, and Chat workspace selector.
- Targeted backend tests and iteration documentation.

## Acceptance Criteria

- Workspace CRUD is owner-scoped and rejects inaccessible projects/folders.
- A Workspace binds to exactly one project or one library folder.
- A general Chat thread can be created with a Workspace and returns its metadata.
- Chat route/run requests cannot use a Workspace that is not bound to the thread.
- Existing unscoped Chat threads continue to work.
- Backend tests and frontend build pass.

## Plan

1. Add iter17 tracking documents.
2. Implement schema and owner-scoped Workspace persistence.
3. Integrate Workspace selection into general Chat thread creation and context.
4. Add tests and UI/API wiring.
5. Run validation and close out the iteration.

## Risks And Questions

- Workspace access is intentionally owner-only in this iteration; sharing and ACLs are deferred.
- A Workspace references existing data and does not duplicate papers or files.
- Research Agent behavior and the 17-step workflow are explicitly out of scope.

## Progress Notes

- 2026-07-21: Confirmed scope with the user: implement Workspace only.
- 2026-07-21: Read AGENTS.md, handoff, iteration index, latest iteration, README, and 任务列表.pdf.

## Progress Notes

- 2026-07-21: Follow-up UI check found two existing general Chat rows persisted with literal `???` titles from the earlier encoding corruption. Repaired those rows to `???`; source defaults remain UTF-8 `???`/`???`.

## Progress Notes

- 2026-07-21: Added a separate active research-project Workspace creation flow to the Chat toolbar. Selecting a project creates and selects a project-bound Workspace without exposing arbitrary OS folders.


## Encoding Incident Follow-up (2026-07-22)

The Chat Workspace toolbar regressed to literal `???`/mojibake after a Windows shell-based rewrite of `src/features/chat/page.tsx`. The immediate cause was not React or the Workspace API: the source file was written with a code-page/escape conversion that damaged Chinese literals. The final repair restored the clean `HEAD` structure and used JavaScript `\uXXXX` escapes for every Chinese label in the affected toolbar, keeping that source block ASCII-only. `npm run build` passes.

For future agents: use explicit UTF-8 for all source/document reads and writes, never use a whole-file `unicode_escape` conversion, and run a post-edit scan for `???`, `?`, and common mojibake markers before declaring a UI encoding fix complete.

## Closeout

Implemented Workspace schema, owner-scoped CRUD, general Chat binding, bounded context injection, frontend API/query support, and Chat selector/new-conversation flow. Fixed the Workspace toolbar's corrupted labels and added an explicit empty state when no non-root library folders exist.

2026-07-22 follow-up: the Workspace creation card now stays single-column until the `xl` breakpoint and uses shrink-safe controls, preventing its name field from overflowing in a half-width window. Creating a Workspace now always honors the entered title: a project or library folder may back multiple explicitly named Workspaces, rather than silently selecting an earlier Workspace for the same source.
2026-07-22 Workspace prompt follow-up: the context was actually injected, but the base general-chat prompt incorrectly said that no paper library/files were connected, and an empty optional Workspace description was rendered as `none`. This caused the model to deny the supplied context. The prompt now explicitly identifies application-supplied Workspace items, distinguishes them from filesystem/database/tool access, and never treats an empty description as an empty Workspace. Added a regression test for a project-bound Workspace with an empty description and a supplied paper item.
2026-07-23 UI and diagnostics follow-up: Chat now separates the current thread's visible Workspace badge from the Workspace selector that applies only to a newly created conversation; Workspace creation is collapsed beneath an explicit follow-up label. Local health diagnosis showed `llm_available: false` after the backend restart, so the API/UI now report the actionable missing-key state instead of the misleading generic generation failure. The key is not stored in the repository or database and must be present in the backend process environment after every restart.
2026-07-23 thread-title follow-up: The literal `?` between a mobile thread title and Workspace name was a hard-coded separator in the responsive Chat header, not Workspace data. It is now removed. General Chat has a persisted owner-scoped title update endpoint and a visible title field with save action; the new-thread controls also accept an optional title before the Workspace selection is used. Existing `新对话` rows remain unchanged until the user renames them.

Validation:
- `python -m py_compile backend/app/services/conversations.py` passed after repairing the Workspace-context syntax join.
- `npm run build` passed (TypeScript and Vite production build).
- `.venv\Scripts\python.exe -m pytest backend\tests -q --basetemp=D:\tmp\paperwiki-pytest-project-workspace` passed: 153 tests.
- `.venv\Scripts\python.exe -m pytest backend\tests\test_core.py -q --basetemp=D:\tmp\paperwiki-pytest-thread-titles` passed: 98 tests.
- `git diff --check` passed.
- Backend `GET /api/health` returned 200; frontend root returned 200 after restarting Vite on `127.0.0.1:5173`.

Review:
- Workspace references existing research projects/library folders and does not duplicate papers/files.
- Paper Chat rejects Workspace binding.
- Deleted/inaccessible Workspace-bound threads are hidden by owner/access checks.
- The current Workspace selector binds to application-managed library folders, not arbitrary OS folders.
- General Chat rename is owner-scoped, rejects blank titles, and does not alter the thread's Workspace binding.

Follow-ups:
- Add dedicated `backend/tests/test_workspaces.py` coverage in the next pass.
- If arbitrary local folders are required, design an explicit browser directory-picker/import flow with strict security controls; do not expose server filesystem paths directly.
- Consider a richer Workspace management UI; current UI supports selecting an existing Workspace and starting a new bound conversation.
2026-07-23 sidebar rename follow-up: Recent Chats now has an inline pencil for each row. It opens a row-local name editor with save/cancel and Enter/Escape keyboard support.
2026-07-23 product simplification: removed manual new-thread naming and the Chat-page current-title editor. General Chat now derives a concise title from the first user message while preserving an explicitly renamed title. Workspace creation moved to a dedicated `/workspaces` page reachable from the left navigation; Chat retains only an existing-Workspace selector and a direct creation link.

2026-07-23 product-simplification validation follow-up: consolidated the default thread-title sentinel into `DEFAULT_THREAD_TITLE` so title generation cannot depend on a corrupted literal. Added backend coverage that verifies first-message title generation (first nonblank line, whitespace normalized) and that an explicitly named thread is preserved. The Workspace page also has its own shell header. Validation: `py_compile` passed, targeted `test_core.py` passed (100 tests), frontend build passed, and `git diff --check` passed.

2026-07-23 composer binding follow-up: moved Workspace selection out of the Chat-page header and into the composer beside route mode. A general Chat may select or clear its Workspace only before its first message; the server enforces that lock and the composer disables Send while the binding PATCH is pending. Added regression coverage for the lock. Validation: `py_compile` passed, `backend/tests/test_core.py` passed (101 tests), frontend build passed, and `git diff --check` passed.

2026-07-23 loading-reliability follow-up: repaired the v11 migration bridge so local databases created by the earlier pre-rebase Workspace schema can upgrade alongside Iter17's v10 paper-processing tables without failing startup. The Recent Chats sidebar no longer truncates to 12 threads and the composer no longer duplicates the selected route icon. The library now starts the root-paper request immediately rather than waiting for folder metadata, only requests the currently visible project status, and disables automatic retry for failed private library/project queries. Explicit retry controls make a failed request recoverable instead of presenting an empty collection. The actual local SQLite list operations were sub-millisecond; observed delays were frontend request sequencing plus expected 401s after an in-memory-session backend restart.

2026-07-23 loading-reliability validation follow-up: `npm.cmd run build` passed. `backend/tests/test_core.py` passed with 92 tests using a repository-local pytest base temp directory. `git diff --check` passed. The earlier attempt to use `D:\tmp\paperwiki-pytest-workspace-followup` was blocked by filesystem permissions rather than test failures.
