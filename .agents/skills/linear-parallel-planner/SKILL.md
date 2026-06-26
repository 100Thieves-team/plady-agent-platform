---
name: linear-parallel-planner
description: Plan Linear issues into safe parallel agent sessions with Symphony-style dispatch eligibility, state-machine routing, user-selected execution backend (claude/codex/cursor/opencode), Codex Workpad bootstrap/update plans, Jean worktree/session manifests, merge plans, and reconciliation sweeps. Use for Linear issue decomposition, daily In Progress planning, assigned issue boards, parent/sub-issue DAGs, cmux or Jean parallel launch plans, stalled active issue reconciliation, Rework/Human Review routing, and approved Jean MCP worktree/session launches.
---

# Linear Parallel Planner

Convert Linear work into **safe branch/worktree/PR/session execution units**. This is primarily a planning and orchestration skill, not an implementation skill.

## Core Rule

Split work into units that are independently testable and low-conflict, not into architecture layers.

Bad split:

```text
- Controller
- Service
- Repository
- Tests
```

Good split:

```text
- Job status model and status API contract
- Widget generation command and job creation flow
- Async worker execution flow
- Failure/retry/observability path
```

## Repository Workflow Contract

When `WORKFLOW.md` exists at repo root, treat it as the repo-owned execution contract. Use it to decide:

- dispatchable Linear states
- required labels such as `agent-ready` or `codex-ready`
- default concurrency
- validation commands
- prompt body requirements
- Workpad/check-in rules

If `WORKFLOW.md` conflicts with this skill, prefer `WORKFLOW.md` for repo policy and this skill for planning shape.

## Mode Selection

Choose one mode from the request:

- **Single parent planning**: split one parent issue into direct sub-issues / PR units.
- **Daily active planning**: list current `In Progress` or assigned dispatchable issues and produce today's phases, concise launch board, and generated-but-omitted launch artifacts (prompts, Workpad bootstraps, Jean manifest).
- **Execution update planning**: prepare Linear/Workpad/sub-issue updates after a plan is accepted. Do not apply updates unless explicitly asked.
- **Jean launch execution**: after approval, create/reuse Jean worktree/session pairs and send issue-local prompts.
- **Reconciliation sweep**: inspect active issues/sessions/PRs and propose `restart`, `rework`, `blocked`, `human review`, `merging`, or `done` actions.

Use Daily active planning for “today”, “In Progress”, “assigned issues”, “start the day”, or “work list”.
Use Reconciliation sweep for “reconcile”, “stalled”, “stale”, “sweep”, “agent health”, “check sessions”, or “what is stuck”.
Use Jean launch execution only for already-planned launchable items or direct launch requests.

## Symphony-Style Dispatch Eligibility

An issue is launchable only when all true:

1. State is dispatchable by `WORKFLOW.md` or by default: `Todo`, `In Progress`, `Rework`, `Human Review`, `Merging`.
2. State is not terminal: `Done`, `Closed`, `Cancelled`, `Canceled`, `Duplicate`.
3. Required label is present, default `agent-ready` unless repo uses `codex-ready`.
4. Non-terminal blockers are absent or explicitly waived.
5. It is not already owned by a live Jean/session run unless this is a continuation/reconciliation action.
6. Concurrency slots are available; default Plady limit is 1-2, with `2` as the initial cap.
7. Start condition is explicit: base branch, contract issue, merge state, or human decision.

## Linear State Machine

Use status to route work:

- `Backlog`: not dispatchable. Draft follow-up issues here; do not launch agents.
- `Todo`: eligible queue. Start by moving to `In Progress` only when direct Linear updates are approved.
- `In Progress`: implementation/validation active.
- `Human Review` / `In Review`: PR/evidence submitted; wait for human unless checks/review require `Rework`.
- `Rework`: reviewer requested changes; make a revised plan and relaunch/continue.
- `Merging`: approved; follow repo git/PR landing workflow.
- `Done` and other terminal states: no agent work.

## Workflow

1. Read relevant Linear issues.
   - Prefer Linear MCP for issue/comment/relation reads and writes.
   - If Jean exposes project/issue context, use it only to supplement Linear context.
   - If Linear tooling is unavailable, use user-provided issue text and record missing information.
2. Read `WORKFLOW.md` when present.
3. Inspect repo only enough to identify modules, contracts, file ownership, validation commands, and conflict risks.
4. Decide whether each issue should remain one PR/session, become direct sub-issues, or be promoted to a Project / multiple parents.
5. Put contracts first when downstream agents would otherwise guess API, DTO, DB, event, widget spec, or error shape.
6. Build complete mode-specific planning artifacts internally, including issue decomposition, Workpad drafts, session prompts, Jean manifest, merge order, and ASCII diagram.
7. Emit a concise user-facing CLI summary by default using `references/output-templates.md`. Do not dump full issue bodies, full Workpad drafts, or full session prompts unless explicitly requested or required for an approved update/launch.
8. Only update Linear, create Jean resources, launch agents, or edit code when the user explicitly asks for that execution step.
9. For approved Jean launches, read `references/jean-mcp-launch.md` before using Jean MCP tools.

## CLI Output Policy

Keep the planning process thorough, but keep the default CLI result short and decision-oriented.

- Answer the Planning Questions internally before deciding the plan; print only answers that change the recommendation.
- Default output should fit roughly within 40-70 lines and use at most two compact tables plus one ASCII diagram.
- Lead with: recommended next action, launchable items, blocked items, required user decisions, and validation/merge order.
- Summarize generated artifacts by count and issue key instead of pasting them: sub-issue bodies, Workpad drafts, session launch prompts, long acceptance criteria, and raw Linear comment details.
- Print full artifacts only when the user explicitly asks for details (for example, "전체", "상세", "full", "prompt", "Workpad draft"), when applying Linear updates, or when sending an approved Jean launch prompt.
- If information is missing, show only blocking questions and safe assumptions; avoid narrating all inspected context.
- For Plan mode responses, keep the native plan concise and put long operational artifacts behind a follow-up offer rather than in the CLI by default.

## Approval Gate

- Planning may propose Linear updates, Workpad bootstrap drafts, and Jean launch manifests.
- Do not call `mcp__jean.create_worktree`, `mcp__jean.create_session`, or `mcp__jean.send_chat_message` until the user approves launch or directly asks for it.
- Do not manually run `git worktree add` when Jean MCP is available.
- Launch only rows with satisfied start condition. Keep blocked rows in the manifest with the blocker.
- Before `create_worktree`, resolve the source branch/upstream for each row. Pass the branch the work should be created from as `baseBranch`; do not silently fall back to `origin/dev`.
- The execution backend is a user choice surfaced during planning, not a hardcoded default. Offer `claude`, `codex`, `cursor`, or `opencode`; propose `codex` by default, and call `mcp__jean.create_session` with the backend confirmed in the approved manifest row. Do not spawn a session with an unconfirmed backend.
- Default Jean chat `executionMode` is `plan`. Use `build` only when the user explicitly asks sessions to implement immediately.
- Always pass `executionMode` explicitly to `mcp__jean.send_chat_message`; never rely on Jean, MCP, SDK, or client defaults.
- Treat "바로 구현해", "build 모드로 보내", "즉시 구현 시작", or equivalent wording as explicit `build` approval. A launch approval alone is not `build` approval.

## ASCII Visualization

End every planning output with a compact ASCII-only diagram.

Requirements:

- Use fenced `text`.
- Use ASCII characters such as `+`, `-`, `|`, `>`, `/`, `\\`, `[`, `]`.
- Show contract-first work, parallel waves, blocked work, conflict-risk work, and merge/integration order when relevant.
- Prefer issue keys; otherwise use short stable labels.
- Keep the diagram compact: normally 10 lines or fewer, collapsing low-risk parallel items when needed.
- Do not use Unicode tree characters or arrows.

Example:

```text
[PLA-101 Parent]
      |
      v
[PLA-102 Contract]
      |
      +--> [PLA-103 Backend]
      +--> [PLA-104 Frontend]
      +--> [PLA-105 Blocked]
      |
      v
[Integration + Human Review]
```

## Daily Active Planning

Use this flow for daily In Progress/assigned work.

1. Query `state in dispatchable states` and `assignee=me` unless the user specifies another assignee/team/project.
2. Inspect title, description, active Workpad comment, latest comments, labels, parent/sub-issues, project, blockers, PR links, updated time, and Jean/session hints.
3. Classify each issue:
   - `Ready`: can start now.
   - `Needs Workpad`: missing or stale `## Codex Workpad` plan.
   - `Contract-first`: must establish API/type/schema/event/widget/error contract first.
   - `Blocked`: waiting on another issue, decision, or merge.
   - `Conflict-risk`: file/module overlap needs stricter scope or merge order.
   - `Review-only`: Human Review/In Review; no coding unless checks/review fail.
4. Build same-day execution board:
   - Phase 0: setup, contract work, Workpad bootstraps.
   - Phase 1: parallel ready sessions within concurrency limit.
   - Phase 2: follow-ups, blocked continuations, Rework.
   - End-of-day: integration, Workpad/Linear state sweep.
5. Generate one Korean session launch prompt per launchable issue. Tell workers to use `$linear-issue-session` before coding.
6. Generate Workpad bootstrap/update drafts for issues missing a current Workpad.
7. Generate Jean MCP launch manifest with `customName`, `baseBranch`, `backend`, `sessionName`, `executionMode`, and start condition.
8. In the default CLI output, show only prompt/workpad/manifest summaries. Paste full prompts or Workpad drafts only on explicit request, Linear update, or approved Jean launch.

## Reconciliation Sweep Mode

Use this mode to detect drift between Linear, Jean sessions, branches, PRs, checks, and Workpads.

Inspect active states from `WORKFLOW.md` plus `Rework`, `Human Review`/`In Review`, and `Merging`. For each issue, check:

- Workpad missing, duplicate, or not updated recently.
- Jean worktree/session missing, archived, dead, or no longer matching the issue.
- Branch or PR closed/merged while Linear remains active.
- Blocker present but issue still `In Progress`.
- Issue in `Human Review`/`In Review` with failing PR checks or unresolved review comments.
- Issue in `Rework` without a revised plan.
- Issue apparently complete with green validation but state not advanced.
- Concurrency slots held by stalled sessions.

Recommend exactly one action per issue:

```text
restart       - relaunch/continue in same issue workspace when safe.
rework        - move/keep in Rework and address review/check failures.
blocked       - record blocker and stop dispatch until dependency clears.
human review  - proof-of-work complete; ask human review.
merging       - approved and green; land according to git workflow.
done          - merged/accepted and terminal criteria met.
no-op         - state/session/workpad are consistent.
```

Output for sweep should use the concise template from `references/output-templates.md`:

```markdown
# Linear Reconciliation Sweep

## 1. 핵심 결론
- 정상:
- 조치 필요:
- 멈춰야 할 것:

## 2. Findings
| Issue | State | Diagnosis | Recommended action | Evidence/next check |
|---|---|---|---|---|

## 3. Proposed updates summary
- Workpad updates:
- State changes:
- Relaunch candidates:
- Human review / blocker notes:

## 4. ASCII execution diagram
```text
[Stale In Progress] --> [restart]
[Review check fail] --> [rework]
[Green PR]          --> [human review / merging]
```
```

## Linear Depth Policy

Use only:

```text
Parent issue
-> Sub-issue: agent execution unit / PR unit
```

Do not create sub-sub-issues. Smaller steps go into the sub-issue body or the Workpad checklist.
If direct sub-issues are insufficient, recommend a Linear Project or multiple parent issues.

## Planning Questions

Answer before proposing sub-issues or sessions. These are internal planning checks; do not print the full checklist unless the user explicitly asks for the detailed reasoning:

1. What is the true completed state?
2. Is one PR/session safer than multiple PRs/sessions?
3. Which contracts must be fixed first?
4. Which parts can run independently after contracts land?
5. Which parts are sequential or blocked?
6. Which agents would touch the same files/modules?
7. Is each proposed issue/session testable on its own?
8. Does each issue/session have explicit non-goals?
9. Does the plan stay within 2-depth Linear policy?
10. Does this need an ADR/tech spec before implementation?
11. Which items are safe to launch now, and which must wait for a contract branch/merge?
12. Does each launchable issue have or need a `## Codex Workpad`?
13. Which execution backend should each session use (`claude`/`codex`/`cursor`/`opencode`), and has the user confirmed it?

## Decomposition Rules

Prefer split axes:

- Different bounded contexts.
- Different API endpoints after contract is fixed.
- Different worker/job flows.
- Different infrastructure components.
- Low-overlap tests/docs/observability/runbooks.
- Producer/consumer work only after shared contract exists.

Avoid split axes:

- Controller / Service / Repository by layer.
- DTO / Entity / Test by artifact type.
- Multiple agents editing the same shared abstraction concurrently.
- DB schema and business logic in parallel without fixed schema.
- Frontend/backend in parallel while response shapes are unknown.

## Dependency Types

Classify every issue/session:

```text
Independent
- Can start now in parallel.

Contract-first
- Must establish API/type/schema/event/widget/error contract before dependents.

Blocked
- Must wait for another issue, decision, merge, or contract.

Conflict-risk
- Can run, but touches overlapping files/modules; needs strict scope or sequential merge.

Review-only
- In Human Review/In Review or Merging; no implementation until review/check state changes.
```

Reflect `Blocked` / `blocking` relations in Linear update plans when updates are requested.

## Sub-Issue Quality Bar

Each sub-issue must satisfy:

1. Done state fits in one sentence.
2. It can own a branch, Jean worktree, PR, Workpad, and issue-local prompt.
3. Expected files/modules are predictable.
4. Dependencies and start condition are clear.
5. Validation is executable or manually checkable.
6. Non-goals say what not to touch.
7. Blocking questions are separated from safe assumptions.
8. Proof-of-work expectation is explicit.

Use this body shape:

```markdown
## Goal
What becomes possible when this issue is done?

## Context
Why this exists and how it relates to the parent issue.

## Scope
Allowed write areas and affected product surface.

## Expected files/modules
- ...

## Inputs
- Issue / docs / ADR / existing code paths to read.

## Output
What the PR/session must contain.

## Dependencies
Required preceding issue, contract, or merge state.

## Non-goals
- ...

## Acceptance criteria
- [ ] ...

## Validation
- Commands or manual checks.

## Proof of work
- Tests/checks/media/PR evidence required before Human Review.

## Agent instructions
- Use $linear-issue-session before coding.
- Use the single `## Codex Workpad` comment as progress SSOT.
- If launched by Jean, stay inside the assigned Jean worktree/session.
- Do not create another worktree from inside the issue session.
- Do not perform broad refactors.
- Do not modify out-of-scope files unless required and explained in the Workpad.
```

## Workpad Bootstrap Draft

When an issue lacks a concrete Workpad, draft this comment. Do not put it in the issue body. In default CLI planning output, list the issue key and one-line intent instead of pasting the full draft.

````markdown
## Codex Workpad
```text
Jean: n/a
Workspace: n/a
Branch: n/a
Updated: <ISO timestamp>
```

### Plan
- [ ] Confirm scope, dependencies, expected files, and validation.
- [ ] Inspect existing implementation and reproduce/confirm current behavior.
- [ ] Implement the scoped change.
- [ ] Run issue-specific validation.
- [ ] Prepare proof-of-work and handoff.

### Acceptance Criteria
- [ ] <issue-specific done state>

### Validation
- [ ] `<command>`: pending

### Notes
- Created by `$linear-parallel-planner` as a launch bootstrap.

### Confusions
- None yet.
````

If the user asks to update Linear, create or update only this Workpad comment unless issue description changes are explicitly requested.

## Out-of-Scope Follow-Up Issue Rule

When planning or executing reveals meaningful out-of-scope work:

- Keep current issue scope unchanged.
- Draft a new Linear issue in `Backlog` with title, context, acceptance criteria, and validation.
- Link current issue as `related` if updates are requested.
- Add `blockedBy` only when the follow-up depends on current issue completion.
- Mention the follow-up in current Workpad `Notes`.

## Jean Worktree And Session Plan

For same-repository parallel work:

- Use one Jean worktree/session per sub-issue or daily issue session.
- Include Linear issue key in `customName`, branch/worktree label, session name, and first message.
- Write every Jean first message and full session launch prompt in Korean. Keep skill names, issue keys, branch names, paths, commands, and API/tool names verbatim.
- Do not create a parent issue worktree by default.
- Merge or base on contract-first work before dependent implementation starts.
- If Jean MCP is available, present Jean MCP launch manifest instead of raw `git worktree add` commands.
- If Jean MCP is unavailable, provide manual fallback but do not execute without explicit approval.

Suggested naming:

```text
customName: feat/PLA-102-create-widget-job-api
sessionName: PLA-102 create widget job API
baseBranch: origin/dev, dev, or approved contract branch
```

### Jean base/upstream selection

Treat `baseBranch` as the exact source branch/upstream Jean should branch from when it creates the worktree. It is not a decorative label.

- Independent new work defaults to the repo integration branch, normally `origin/dev`.
- Dependent implementation uses the committed contract/parent branch as `baseBranch`, not `origin/dev`, after that branch is pushed or otherwise available to Jean.
- Follow-up, rework, or continuation sessions use the existing PR/head branch they are continuing from.
- If the user is launching from a branch that was created off another feature/contract branch, preserve that source branch/upstream in the manifest and in `create_worktree`.
- If the intended source branch is local-only, missing, or ambiguous, mark the row blocked/manual-only until the branch is pushed or the user chooses the source branch.
- If a target branch/worktree already exists with a different upstream/base than the plan expects, do not create another worktree from a guessed base; reuse the matching worktree or stop for reconciliation.

Only use a contract-first branch as base after it has a committed contract. Otherwise mark dependents blocked/draft until the base is ready.

## Jean MCP Launch Manifest

Every launchable plan must carry a Jean launch manifest. In default CLI output, show the compact form below; keep `sessionName` and the full Korean first prompt available internally for launch execution.

| Issue | Launch? | backend | customName | baseBranch | executionMode | Start condition |
|---|---|---|---|---|---|---|

Rules:

- `Launch?` is `yes`, `blocked`, or `manual-only`.
- Every launchable row must include a user-confirmed `backend` (`claude`/`codex`/`cursor`/`opencode`); propose `codex` by default and surface it as a user decision rather than spawning silently.
- Every launchable row must include `executionMode`; default every row to `plan`.
- Every launchable row must include the resolved creation source in `baseBranch`; it must match the branch/upstream the work should be created from.
- When approved for Jean execution, pass that exact `baseBranch` to `mcp__jean.create_worktree({ projectId, customName, baseBranch })`.
- Pass the confirmed `backend` to `mcp__jean.create_session({ worktreeId, backend, name: sessionName })`; do not hardcode `codex`.
- Do not leave `executionMode` blank, implicit, or described as "default".
- Use `build` only when the user explicitly approved immediate implementation.
- Before launch, verify every `mcp__jean.send_chat_message` payload explicitly includes `executionMode`, normally `executionMode: "plan"`.
- `First message` is a short Korean label kept with the full session prompt; do not paste full prompts in default CLI output.
- Do not pass Linear issue keys to Jean `issueNumber`; that field is for GitHub issues.
- For approved execution, read `references/jean-mcp-launch.md` and follow it exactly.

## Output And Prompt Templates

When producing Jean session launch prompts or final planning output, read `references/output-templates.md` and use the matching concise template by default. Keep launch prompts issue-local and Korean. Use the detailed artifact shape only when the user asks for full details or when writing/updating Linear/Jean.

## Merge Rules

1. Merge contract-first issues before dependent PRs.
2. Keep dependent PRs Draft until required contract is merged or available as base.
3. Merge independent PRs in parallel only when file overlap is low.
4. Do not merge overlapping shared files without explicit integration order.
5. After sub-issues merge, run integration verification on parent base.
6. Mark parent Done only after all sub-issues are Done and integration verification passes.


If the user asks to directly update Linear, apply the plan after presenting or confirming it. If the user asks only for planning, stop at the plan. If the user approves Jean launch, follow `references/jean-mcp-launch.md` and report created/reused worktree IDs and session IDs.
