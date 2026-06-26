---
name: linear-issue-session
description: Plan, execute, and reconcile one Linear issue worker session using a single persistent ## Codex Workpad comment as progress source of truth. Use when starting, resuming, or ending a dedicated Linear issue session, especially from Jean worktree/session automation, daily parallel planning, Rework/Human Review loops, proof-of-work handoff, or local Workpad update draft generation.
---

# Linear Issue Session

Use this skill inside one issue worker session. One Linear issue owns one narrow outcome, one Jean worktree/session boundary, and one persistent Linear comment headed `## Codex Workpad`.

## Core Rule

Use the single `## Codex Workpad` comment as the progress SSOT. Do not scatter execution state across issue body edits, extra progress comments, and local notes. If Linear comment editing is unavailable, create a local `_workspace/linear-checkins/` Workpad update draft and say exactly what could not be written.

The `## Codex Workpad` header is a fixed progress-comment label, independent of which execution backend (`claude`, `codex`, `cursor`, or `opencode`) runs the session. Keep the header verbatim regardless of backend so tooling and the daily planner can match it.

## Jean Context Rule

When running inside Jean:

- Treat the current Jean worktree as the issue's workspace.
- Use `mcp__jean.get_current_context` when available to identify project, worktree, and session IDs.
- If unavailable, infer context from prompt, branch, path, and safe environment variables such as `JEAN_MCP_SESSION`, `JEAN_WORKTREE_ID`, `JEAN_PROJECT_ID`, and `LINEAR_ISSUE_KEY`.
- Do not call `mcp__jean.create_worktree` from inside an issue session. New worktrees are created by `$linear-parallel-planner` after human approval.
- Do not switch Jean workspaces to inspect unrelated issues unless explicitly asked.

## Status Map

Route by current Linear state before coding:

- `Backlog`: not dispatchable. Do not modify; ask human to move to `Todo` or `In Progress`.
- `Todo`: dispatchable only when required label exists and blockers are clear. Move to `In Progress` if the user approved direct Linear updates, then create/reuse Workpad.
- `In Progress`: active implementation. Continue from existing Workpad and workspace state.
- `Human Review` / `In Review`: review wait state. Do not code unless review feedback requires `Rework`; reconcile PR/check status and Workpad proof only.
- `Rework`: treat as a revised attempt. Re-read issue, comments, PR feedback, and Workpad; update plan before edits.
- `Merging`: merge/land state. Follow repo git/PR workflow; do not start new feature work.
- `Done`, `Closed`, `Cancelled`, `Canceled`, `Duplicate`: terminal. Stop.

## Session Start Workflow

1. Identify issue key from user prompt, Jean launch context, branch/worktree path, or `LINEAR_ISSUE_KEY`.
2. Capture Jean context if present: project ID/path, worktree ID/path, session ID, backend, execution mode.
3. Read Linear issue title, description, comments, state, labels, project, parent/sub-issues, blockers, PR links, and latest review/check signals.
4. Read the daily/session launch prompt if one exists. Treat it as the scope contract.
   - Jean launch prompts produced by `$linear-parallel-planner` should be Korean. Preserve Korean for session plan and Workpad notes unless the issue requires another language.
5. Route by Status Map.
6. Find or create the `## Codex Workpad` comment.
7. Inspect repo only enough to confirm scope, expected files, and validation commands.
8. Update the Workpad with a short plan before coding.

## Codex Workpad Rule

Find or create exactly one live progress comment:

- Search active/unresolved comments for the header `## Codex Workpad`.
- Reuse it if found; update that comment in place.
- If absent and direct Linear updates are approved/available, create one comment.
- If multiple Workpads exist, use the newest active one and note the duplicate in `### Confusions`.
- Do not edit the issue body to add `## Execution Plan`; put execution plan/checklists in the Workpad.
- Do not add separate progress, done, or blocker comments unless the Workpad cannot be edited.

Use this structure:

````markdown
## Codex Workpad
```text
Jean: <project/worktree/session or n/a>
Workspace: <path or n/a>
Branch: <branch or n/a>
Updated: <ISO timestamp>
```

### Plan
- [ ] 1. Confirm scope, dependencies, expected files, and validation.
- [ ] 2. Inspect current behavior and implementation.
- [ ] 3. Implement scoped change.
- [ ] 4. Run validation.
- [ ] 5. Prepare proof-of-work and handoff.

### Acceptance Criteria
- [ ] <issue-specific done state>

### Validation
- [ ] `<command>`: <pending/pass/fail/not run + brief evidence>

### Notes
- <reproduction, decisions, changed files, PR/check evidence>

### Confusions
- <none or concise ambiguity/blocker>
````

Mark only items that were completed or verified from evidence.

## Local Plan Shape

Before implementation, write/update this in the Workpad and optionally echo it in chat:

```markdown
### Plan
- [ ] Goal: <one sentence>
- [ ] Scope: <allowed modules/files>
- [ ] Out of scope: <what not to touch>
- [ ] Dependencies: <contract/issue/base branch>
- [ ] Expected edits: <specific files/modules>
- [ ] Validation: <commands/manual checks>
- [ ] Handoff: <proof-of-work target>
```

Keep this issue-local. Do not redesign the whole feature unless the issue asks for planning.

## Implementation Guardrails

- Follow the launch prompt and Workpad before broader repo instincts.
- Ask or stop if a required API, DTO, DB, event, widget spec, or error contract is missing.
- Avoid broad refactors and cross-issue cleanup.
- Do not modify out-of-scope files unless required; record any scope expansion in Workpad `Notes`.
- If a dependency is blocked, update Workpad `Confusions`/`Notes` with facts instead of guessing.
- Keep `_workspace/` handoffs when the issue belongs to a Plady feature flow.

## Out-of-Scope Follow-Up Rule

When meaningful performance, refactor, architecture, UX, test, or docs work is discovered outside the current issue:

1. Do not expand the current issue.
2. Draft a separate Linear issue in `Backlog` with title, context, acceptance criteria, and validation.
3. Link it as `related` to the current issue when writing to Linear is approved.
4. Add `blockedBy` only if the follow-up depends on the current issue landing.
5. Record the draft/link in Workpad `Notes`.

## Proof-of-Work Bar

Before moving to `Human Review` / `In Review` or ending as complete, record evidence in the Workpad:

- Backend: `ktlintCheck`, `unitTest`, changed module tests, or REST Docs result as applicable.
- API contract: `compileKotlin restDocsTest`, documented request/response/error shape, and generated docs impact.
- Frontend: `pnpm lint`, `pnpm format:check`, `pnpm build`, plus screenshot/video or exact UI flow for user-facing changes.
- AI/widget: concept-alignment result, generated widget spec shape, validation fixtures, and teaching-risk notes.
- PR/handoff: PR link if available, changed-file summary, risk notes, unresolved comments/checks, and next state.

If validation cannot run, record the exact blocker and why the work cannot be trusted yet.

## Session End Workflow

Before ending a session:

1. Review `git status`, changed files, commits if any, validation commands, PR/check status, unresolved TODOs, and Workpad checklist.
2. Update the Workpad in place with completed items, remaining items, blockers/questions, validation result, branch/worktree/session/PR, risk notes, and next action.
3. Move status only when the matching quality bar is met and the user approved direct Linear updates.
4. If direct Linear updates are unavailable or not requested, leave a Workpad update draft in `_workspace/linear-checkins/`.
5. Keep the final chat concise: completed work, blockers, validation, and where the Workpad/draft lives.

## Hook Draft Script

Use `scripts/session_checkin.py` to generate a no-network Workpad update draft from a Stop/SessionEnd hook or manual command:

```bash
python3 .agents/skills/linear-issue-session/scripts/session_checkin.py --root .
python3 .agents/skills/linear-issue-session/scripts/session_checkin.py --root . --issue PLA-123
```

The script never writes to Linear. It creates `_workspace/linear-checkins/{ISSUE}-{timestamp}.md` and exits 0 when no issue key can be found. When Jean environment metadata is present, it records only safe IDs/paths/mode fields in the draft.

## Linear Update Policy

- Prefer Linear MCP for issue/comment reads and Workpad comment updates when available.
- Use local Linear CLI/helper scripts only when MCP is unavailable.
- Do not auto-write from hooks.
- Preserve existing issue descriptions; do not replace issue body sections for progress tracking.
- Prefer editing the existing Workpad comment over creating new comments.
- If a session is blocked, update Workpad `Confusions`/`Notes`; leave the issue `In Progress` unless the user requests a state change.
- Include Jean worktree/session metadata in the Workpad so the daily planner can reconcile parallel sessions.

## Workpad Update Template

Use `references/checkin-template.md` when drafting manual Workpad updates or reviewing hook-generated drafts.
