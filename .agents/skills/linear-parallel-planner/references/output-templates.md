# Linear Parallel Planner Output Templates

Use this reference when producing Jean session launch prompts or final planner outputs. Keep Korean launch prompts Korean.

## Default CLI Principle

The planner still performs the full analysis, but the user-facing CLI output should be a compact operating view.

- Show conclusions, launchability, blockers, order, and next decisions first.
- Do not paste full sub-issue bodies, Workpad drafts, or session launch prompts by default.
- Summarize omitted artifacts by issue key and count, then offer to print/apply them if the user asks.
- Use detailed artifacts only for explicit full-detail requests, Linear writes, or approved Jean launch messages.

## Session Launch Prompt Template

Generate Korean prompts. Use this full prompt only when sending an approved Jean launch or when the user explicitly asks to see the prompt:

```markdown
Linear 이슈 {ISSUE_KEY}: {TITLE} 작업 세션입니다.

코딩을 시작하기 전에 반드시 $linear-issue-session 스킬을 사용하세요.
진행 상태는 Linear 이슈의 단일 `## Codex Workpad` 댓글에만 업데이트하세요. 새 진행 댓글을 남발하지 마세요.

## Jean 실행 컨텍스트
- Worktree/session 경계: 이 Jean worktree는 {ISSUE_KEY} 전용입니다.
- 이 worktree 안에서만 작업하세요. 다른 worktree를 만들지 마세요.
- 이 세션은 Plan mode로 시작합니다.
- 사람이 "바로 구현해", "build 모드로 보내"처럼 Build mode를 명시적으로 승인한 경우에만 Build mode로 전환할 수 있습니다.

## Linear 컨텍스트
- 이슈: {ISSUE_KEY}
- 제목: {TITLE}
- URL: {LINEAR_URL_OR_UNKNOWN}
- 상태: {STATE}
- 라벨: {LABELS}
- 상위/관련 이슈: {PARENT_OR_RELATIONS}
- Workpad 상태: {WORKPAD_STATUS}

## 목표
{완료 상태를 한 문장으로 작성}

## 범위
{수정 가능한 repo / modules / packages}

## 수정하지 말 것
- {비목표 또는 금지 범위}

## 의존성
{필요한 contract, issue state, base branch, 또는 merge state}

## 예상 변경
- {구체적인 산출물}

## 검증
실행:
- {commands}

## Proof of work
- Workpad의 Plan/Acceptance Criteria/Validation을 증거 기반으로 체크하세요.
- PR/branch, 변경 파일, 리스크, 테스트 결과, UI screenshot/video 또는 AI/widget 개념 정합성 증거를 기록하세요.

## 세션 종료 전
기존 `## Codex Workpad`를 업데이트하거나, Linear 쓰기가 불가하면 `_workspace/linear-checkins/`에 Workpad 업데이트 draft를 남기세요.
```

Keep prompts issue-local and Korean. Do not paste unrelated repo-wide guidance.

## Jean MCP Launch Manifest Rules

- Every launchable row must include an explicit `executionMode`.
- Every launchable row must include a resolved `baseBranch` that is the branch/upstream Jean should create the worktree from.
- Do not substitute `origin/dev` when the issue depends on a contract, parent, PR head, or current feature branch.
- Default every launchable row to `plan`; do not leave the value blank, implicit, or described as "default".
- Use `build` only when the user explicitly approved immediate implementation, for example: "바로 구현해", "build 모드로 보내", "즉시 구현 시작", or an equivalent instruction.
- Do not use `yolo` unless the user explicitly requested `yolo`.
- The launcher must pass `executionMode` explicitly in every `mcp__jean.send_chat_message` payload, normally as `executionMode: "plan"`.

## Final Output: Single Parent Planning (Concise Default)

Produce:

````markdown
# Parallel Planning Result

## 1. 핵심 결론
- 추천:
- 바로 실행 가능:
- 먼저 풀어야 할 것:

## 2. 실행 보드
| Unit | Type | Launch? | Scope | Start condition | Risk/validation |
|---|---|---|---|---|---|

## 3. 실행 순서
- Phase 0:
- Phase 1:
- Phase 2:
- Integration:

## 4. Jean launch summary
| Issue | Launch? | customName | baseBranch | executionMode | Start condition |
|---|---|---|---|---|---|


## 5. 필요한 사용자 결정 / 누락 정보
- Blocking questions:
- Safe assumptions:

## 6. 생략한 상세 산출물
- Sub-issue bodies: {count or issue keys}
- Workpad drafts: {count or issue keys}
- Session prompts: {count or issue keys}
- 필요하면 "상세 출력" 또는 "Linear 업데이트" 또는 "Jean launch"라고 요청하세요.

## 7. ASCII execution diagram
```text
[PLA-101 Parent]
      |
      v
[PLA-102 Contract]
      |
      +--> [PLA-103]
      +--> [PLA-104]
      |
      v
[Integration + Human Review]
```
````

## Final Output: Daily Active Planning (Concise Default)

Produce:

````markdown
# Daily Linear Execution Plan

## 1. 오늘의 결론
- 우선순위:
- 지금 시작:
- 대기/차단:
- 종료 전 확인:

## 2. Active board
| Issue | State | Type | Next action | Start condition | Risk |
|---|---|---|---|---|---|

## 3. Today execution order
- Phase 0:
- Phase 1:
- Phase 2:
- End-of-day sweep:

## 4. Jean launch summary
| Issue | Launch? | customName | baseBranch | executionMode | Start condition |
|---|---|---|---|---|---|


## 5. 필요한 사용자 결정 / 생략한 상세 산출물
- Decisions:
- Workpad drafts ready for: {issue keys or none}
- Session prompts ready for: {issue keys or none}
- 필요하면 "상세 출력" 또는 "Jean launch"라고 요청하세요.

## 6. ASCII execution diagram
```text
Phase 0: [Contract / Workpad setup]
              |
              v
Phase 1: [Issue A]   [Issue B]   [Issue C blocked]
              \\         /
               v       v
Phase 2:     [Merge + EOD sweep]
```
````

## Final Output: Reconciliation Sweep (Concise Default)

Produce:

````markdown
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
````

If the user asks to directly update Linear, apply the plan after presenting or confirming it. If the user asks only for planning, stop at the concise plan. If the user approves Jean launch, follow `references/jean-mcp-launch.md` and report created/reused worktree IDs and session IDs.
