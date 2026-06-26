# Jean MCP Launch Reference

Use this reference only after the user explicitly approves launching Jean worktrees/sessions from a Linear parallel plan.

## Intent

Jean owns the worktree/session lifecycle. For Linear work, create or reuse one Jean worktree and one chat session per launchable issue. Linear context is carried in the first chat message because Jean `issueNumber` / `prNumber` are GitHub-oriented inputs.

## Preconditions

- A reviewed plan exists with a `Jean MCP launch manifest`.
- Each row has `Issue`, `customName`, `baseBranch`, `backend`, `sessionName`, `executionMode`, start condition, and a full session launch prompt.
- Each `baseBranch` is the resolved source branch/upstream the worktree should be created from, not a guessed default.
- Each `backend` is the user-chosen execution engine (`claude`, `codex`, `cursor`, or `opencode`); do not assume one silently. The planner asks the user for the backend during planning and records the confirmed value per row. There is no default backend.
- Each row defaults `executionMode` to `plan`; do not leave it blank, implicit, or described as "default".
- Each launchable issue satisfies dispatch eligibility from `WORKFLOW.md`: active state, required label, clear blockers, and concurrency slot.
- Each full prompt is written in Korean. Keep skill names, issue keys, branch names, paths, commands, and API/tool names verbatim.
- The prompt tells the worker to use `$linear-issue-session` and the single `## Codex Workpad` comment before coding.
- The user approved launch. Do not infer approval from merely asking for a plan.
- Blocked rows remain blocked; do not create worktrees for them.

## Execution mode policy

- Always pass `executionMode` explicitly in every `mcp__jean.send_chat_message` payload. Do not rely on Jean, MCP, SDK, or client defaults.
- Default payload shape is:
  - `mcp__jean.send_chat_message({ sessionId, executionMode: "plan", message })`
- Use `executionMode: "build"` only when the user explicitly approved immediate implementation, for example: "바로 구현해", "build 모드로 보내", "즉시 구현 시작", or an equivalent instruction.
- Never use `build` merely because the issue is launchable, the plan was approved, or the manifest row omitted `executionMode`.
- Do not use `yolo` unless the user explicitly requested that exact execution mode.

## Backend policy

- The execution backend is a user decision made during planning, not a fixed default. Valid values are `claude`, `codex`, `cursor`, and `opencode` (the `mcp__jean.create_session` `backend` enum).
- Pass the exact `backend` confirmed in the approved manifest row to `mcp__jean.create_session`.
- There is no default backend. Always ask the user and use only the confirmed value. The `codex-ready` / `agent-ready` label gates dispatch eligibility, not backend choice — never read a label, a prior session, or a skill-reference example as an implied backend.
- Do not launch a session with a backend the user has not chosen or confirmed. If a launchable row lacks a confirmed `backend`, ask before creating the session.

## Launch checklist

Before sending any Jean chat message:

- [ ] Every launchable manifest row has a user-confirmed `backend` (`claude`/`codex`/`cursor`/`opencode`).
- [ ] Every launchable manifest row has an explicit `executionMode`.
- [ ] Every default row uses `executionMode: "plan"`.
- [ ] Every `mcp__jean.send_chat_message` payload explicitly includes `executionMode`.
- [ ] No row uses `build` unless the user explicitly approved immediate implementation.
- [ ] No row uses `yolo` unless the user explicitly requested `yolo`.

## Resolve the Jean project

1. If inside a Jean-spawned session, call `mcp__jean.get_current_context` and use its `projectId`.
2. If there is no Jean session context, call `mcp__jean.list_projects`.
3. Match the current repository by exact or resolved path against Jean project `path` / `projectPath`.
4. If multiple projects match or none match, ask the user to choose. Do not guess.

## Duplicate check

Before creating anything:

1. Call `mcp__jean.list_worktrees({ projectId })`.
2. Treat a worktree as existing when its name, branch, path, or metadata contains the target Linear issue key or planned `customName`.
3. For an existing worktree, call `mcp__jean.list_sessions({ worktreeId, includeArchived: false })`.
4. Reuse an idle issue-matching session when present. Create a new session only when no suitable active session exists.
5. If an existing target branch/worktree appears to have a different base/upstream than the launch manifest, do not create a duplicate from a guessed base. Stop and reconcile or ask the user.

## Resolve base/upstream

Before `create_worktree`, determine the branch Jean must use as the creation source:

- Independent new work: repo integration branch, normally `origin/dev`.
- Dependent implementation: the pushed contract/parent branch that contains the required committed contract.
- Rework or continuation: the existing PR/head branch being continued.
- Split/follow-up from the current feature branch: the current feature/contract branch, not `origin/dev`, when the issue depends on that branch's commits.

If that source branch is local-only, missing from Jean's project, or ambiguous, skip the row as `manual-only`/blocked until the branch is pushed or the user chooses a source. Never replace an unknown source with `origin/dev` just to create the worktree.

## Create or reuse worktree/session

For each launchable row:

1. Create the worktree when no matching worktree exists:
   - `mcp__jean.create_worktree({ projectId, customName, baseBranch })`
   - Pass the exact resolved source branch/upstream from the manifest as `baseBranch`.
2. Do not pass a Linear issue key to `issueNumber`.
   - `issueNumber` is for GitHub issues.
   - Use `issueNumber` or `prNumber` only when the plan is explicitly based on a GitHub issue/PR.
3. Create a chat session when no matching session exists:
   - `mcp__jean.create_session({ worktreeId, backend, name: sessionName })`
   - Pass the `backend` the user chose for this row in the approved manifest (`claude`/`codex`/`cursor`/`opencode`).
   - If the row has no confirmed backend, stop and ask; do not silently default to `codex`.
4. Send the full Korean launch prompt:
   - `mcp__jean.send_chat_message({ sessionId, executionMode: "plan", message })`
   - If the manifest row has an approved non-default mode, pass that explicit value instead of `"plan"`.
   - Never omit `executionMode`.
   - Use `build` only when the user explicitly approved immediate implementation.
   - If the planned message is not already Korean, translate it before sending.

## First message requirements

The message must include:

- Instruction to use `$linear-issue-session` before coding.
- Instruction to find/create/update exactly one `## Codex Workpad` comment and avoid separate progress comments.
- Linear issue key, title, URL if known, state, labels, parent/relations, blockers, and Workpad status.
- Scope, expected files/modules, non-goals, dependencies, validation commands.
- Proof-of-work expectations: tests/checks, changed files, PR/branch, risk notes, media for UI, concept-alignment evidence for AI/widget work.
- Jean boundary: this worktree/session is dedicated to the issue; do not create another worktree.
- End-of-session requirement: update Workpad in place, or create `_workspace/linear-checkins/` Workpad draft if Linear write is unavailable.

## Reporting after launch

Return a concise table:

| Issue | Worktree | Session | Action | Execution mode | Next check |
|---|---|---|---|---|---|

Use `Action` values:

- `created worktree + session`
- `reused worktree + created session`
- `reused worktree + reused session`
- `skipped: blocked`
- `failed: <reason>`

Do not poll indefinitely. If the user asks for progress, use `mcp__jean.get_session_status` and optionally `mcp__jean.read_session_messages` with a small limit.

## Fallback

If Jean MCP is unavailable:

- Do not run raw git worktree commands automatically.
- Present the manifest as a manual fallback and ask whether to proceed outside Jean.
- Prefer Jean once it becomes available because Jean preserves the worktree:session mapping and session context.
