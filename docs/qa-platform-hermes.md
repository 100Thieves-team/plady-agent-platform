# QA 플랫폼 P4 설계 — Hermes 와 대화하며 QA 하기

- 이슈: [MOI-483](https://linear.app/100-thieves/issue/MOI-483/qa-자동화-플랫폼-구축) 후속 (P4)
- 선행: [`qa-platform.md`](qa-platform.md) (P0·P1), [`qa-platform-tc.md`](qa-platform-tc.md) (P2·P3)
- 상태: **검토 대기** (구현 전). 결정이 필요한 항목은 §8.
- 작성: 2026-09-21

## 0. 한 줄 요약

UI 안에 Hermes 채팅창을 둔다. Hermes 는 플랫폼이 내주는 **QA 도구(MCP)** 로 기준·케이스·런·커버리지를 읽고, 케이스를 새로 쓰거나 고쳐 **케이스 초안**으로 낸다. 초안은 지금과 같은 결정론 검증과 사람 승인을 거쳐야 케이스가 된다. **실행·전송·발행·승인 버튼은 여전히 사람만** 누른다. 같이 넣는 것: 기준이 바뀐 케이스를 Hermes 가 새 기준에 맞게 다시 쓰는 버튼.

## 1. 전제 — 확인한 사실

| # | 사실 | 영향 |
| --- | --- | --- |
| 1 | `hermes-gateway:8642` 는 OpenAI 호환 `/v1/chat/completions` + `X-Hermes-Session-Key`(세션 스코프, 응답에 echo). 플랫폼은 이미 진단·초안에 이 경로를 쓴다 | 채팅창은 같은 경로. 대화 하나 = 세션 키 하나 |
| 2 | Hermes 의 도구는 `~/.hermes/config.yaml` 의 `mcp_servers` 로 들어간다(평면 스키마 `url`/`headers`/`tools.include`). `hermes-config-init` 가 compose 에서 `yq` 로 병합하고, **include 목록의 SSOT 는 compose** 다 | 플랫폼이 MCP 서버를 내주고 compose 에 등록하면 Hermes 가 QA 도구를 갖는다. 클라이언트가 요청마다 도구를 정의하는 방식(OpenAI `tools` 파라미터)은 hermes-agent 가 받는지 확인되지 않았다 → 쓰지 않는다 |
| 3 | Hermes 에는 MCP 도구 호출을 막는 **승인 게이트가 없다**. `wiki_apply` 가 include 에 들어 있고, Slack 쪽 allowlist 는 Slack 플랫폼 층에만 있다 | API 경로(=채팅창)에서는 팀 세션만 있으면 누구나 Hermes 에게 위키 쓰기를 시킬 수 있다 → §8-1 결정 |
| 4 | 플랫폼은 MCP **클라이언트**(`qa/mcp.py`, 발행용)만 있고 **서버**는 없다. llm-wiki 의 서버는 Rust(rmcp streamable HTTP) | 플랫폼에 최소 MCP 서버(JSON-RPC over HTTP, 표준 라이브러리)를 얹는다. initialize / tools/list / tools/call 세 메서드면 된다 |
| 5 | Hermes API 응답이 도구 호출 트레이스를 어떤 형식으로 담는지 **미확인** | 구현 전 확인 항목. 못 받으면 플랫폼 쪽 도구 호출 로그(events)로 대신 보여 준다 |
| 6 | Hermes 는 위키 read 도구 16개를 이미 갖는다 | 채팅에서는 Hermes 가 PRD·SSOT 를 스스로 읽을 수 있다. §13-8(초안 생성 버튼은 플랫폼이 근거를 넣어 준다)은 **버튼 경로에 한해** 유지 |

## 2. 원칙 (기존 것에 더한다)

| 원칙 | 뜻 |
| --- | --- |
| **실행은 사람 버튼** (사용자 결정 ①) | Hermes 도구에는 런 생성·탐색기 전송·위키 발행·초안 승인·반려가 **없다**. "돌려 줘" 라고 하면 Hermes 는 대시보드 링크를 준다 |
| **케이스로 들어가는 문은 하나** | 채팅에서 만든 것도 케이스 초안 → 결정론 검증 → 사람 승인 → PR. 문을 더 만들지 않는다 |
| **TC 정본은 Hermes 가 못 고친다** | SSOT·OpenAPI 는 읽기만. 서술 TC(`manual-tc.yaml`)도 "제안" 초안까지. 기준을 고치려면 위키를 고친다 |
| **근거는 남는다** | 버튼 경로 = 재현 가능한 프롬프트(해시). 채팅 경로 = 대화 기록 + 도구 호출 로그. 둘 다 감사 로그에 운영자와 함께 |
| **Hermes 가 하는 일은 읽기·제안·설명** | 커버리지 공백 설명, 실패 원인 해석, 케이스 작성·수정 제안, 기준 변경 영향 설명 |

## 3. 기능 트리

```text
P4 Hermes 연동
├─ 1. QA MCP 서버 (플랫폼 내장 /mcp, 내부 전용)
│   ├─ 읽기  qa_catalog_search · qa_tc_get · qa_coverage · qa_changes
│   │        qa_case_list · qa_case_get · qa_run_list · qa_run_get · qa_spec_op · qa_prd_section
│   └─ 제안  qa_draft_create · qa_draft_update · qa_manual_tc_propose   (전부 초안함으로만)
├─ 2. 채팅창 /chat
│   ├─ 2.1 대화 목록 · 새 대화 · 운영자 필수
│   ├─ 2.2 컨텍스트 첨부  런 상세·케이스 상세·TC 상세에 [Hermes 와 이야기] → 그 객체를 첫 메시지에 붙인다
│   ├─ 2.3 메시지 기록(sqlite) · 도구 호출 표시 · 초안이 만들어지면 링크
│   └─ 2.4 감사 로그  chat.create · chat.send · mcp.call
├─ 3. [바뀐 기준으로 초안 다시 쓰기]  케이스 상세, 근거 변경 배지 옆
│   └─ 현재 YAML + 바뀐 TC 전/후 + 새 PRD 절 → Hermes → 검증 → 초안(원 케이스 링크)
└─ 4. [PRD 절에서 서술 TC 제안]  기준 화면 서술 층
    └─ PRD 절 본문 → Hermes → TC 제안 초안(kind=tc) → 사람이 manual-tc.yaml 에 붙여 PR
```

### 3.1 QA MCP 도구

| 도구 | 인자 | 하는 일 | 쓰기 |
| --- | --- | --- | --- |
| `qa_catalog_search` | domain?, layer?, only?(uncovered\|covered\|warn), q?, limit | TC 목록(제목·바인딩·덮는 케이스·마지막 판정) | – |
| `qa_tc_get` | id | 레코드 전문 + PRD 절 본문 + 덮는 케이스 | – |
| `qa_coverage` | – | 도메인×층 매트릭스, 제외 수, 기준 버전 | – |
| `qa_changes` | since? | 최근 바뀐 TC 와 영향 케이스 | – |
| `qa_case_list` / `qa_case_get` | domain?, suite? / id | 케이스 목록 / YAML·covers·대조 상태·실행 이력 | – |
| `qa_run_list` / `qa_run_get` | trigger?, limit / id, with_steps? | 런 목록 / 런 상세(단계 요청·응답·단언, 마스킹된 그대로) | – |
| `qa_spec_op` | operationId | OpenAPI 발췌(요청 예시·성공·에러 코드) | – |
| `qa_prd_section` | doc, section | PRD 절 본문(볼륨에서) | – |
| `qa_draft_create` | yaml, reason | §7.2 검증 → 통과하면 케이스 초안(source `hermes-chat`), 실패하면 사유를 돌려준다 | 초안만 |
| `qa_draft_update` | id, yaml | 결정되지 않은 초안만 재검증·갱신 | 초안만 |
| `qa_manual_tc_propose` | doc, section, items[] | 서술 TC 제안을 초안(kind `tc`)으로. 파일에는 사람이 옮긴다 | 초안만 |

없는 것(의도): 런 생성, 탐색기 전송, 위키 발행, 초안 승인·반려, 케이스 파일 쓰기, 바인딩·제외 파일 쓰기.

인증: 내부 네트워크 + 정적 bearer `QA_MCP_TOKEN`. Caddy `@qa` 블록은 `/mcp` 를 **거부**한다(공개 경로 아님). Hermes 쪽 등록은 `hermes-config-init` 에 `mcp_servers.qa-platform` 을 더한다(`url: http://qa-platform:8800/mcp`, `headers.Authorization: Bearer ${QA_MCP_TOKEN}`, `tools.include` = 위 표). llm-wiki 와 같은 방식이라 문서 [`hermes-gateway.md`](hermes-gateway.md) 의 규칙(include 가 SSOT, 손으로 고친 건 다음 배포에 사라짐)이 그대로 적용된다.

### 3.2 채팅창

- `/chat`: 대화 목록(운영자·제목·시각·초안 수). [새 대화]. `/chat/{id}`: 메시지 스레드 + 입력창. 서버 렌더, 전송은 POST, 응답은 동기(스트리밍 없음 — Hermes 가 도구를 여러 번 부르면 수십 초 걸릴 수 있어 화면에 "Hermes 가 도구를 쓰는 중" 표시와 타임아웃 180초).
- 대화 = `X-Hermes-Session-Key: qa-chat-<id>`. Hermes 가 세션 메모리를 갖고 있으니 플랫폼은 매 턴 전체 대화를 다시 보내지 않고 **새 메시지만** 보낸다. 시스템 프롬프트는 첫 턴에 넣는다(§3.4).
- 컨텍스트 첨부: 런·케이스·TC 상세의 [Hermes 와 이야기] 는 `/chat/new?run=r-…` 처럼 열리고, 첫 메시지 앞에 그 객체의 id 와 요약을 붙인다. Hermes 는 필요하면 도구로 나머지를 읽는다.
- 도구 호출 표시: Hermes 응답에 트레이스가 있으면 그것을, 없으면 그 턴 동안 플랫폼 `/mcp` 에 들어온 호출(events `mcp.call`)을 시각으로 묶어 보여 준다. 동시에 두 대화가 도구를 부르면 섞일 수 있다 — 3인 팀에서 드물고, 한계로 적어 둔다.
- 초안이 생기면 메시지 아래에 링크. 승인은 케이스 초안 화면에서 사람이.

### 3.3 [바뀐 기준으로 초안 다시 쓰기]

1. 카탈로그 변경 이력에 **변경 전 레코드 스냅샷**을 함께 저장한다(지금은 `kind·at` 만). `changes.json` 의 항목에 `before: {title, expect_hint, binding}` 추가.
2. 케이스 상세에서 근거 변경 배지가 있을 때 버튼이 뜬다. 플랫폼이 조립: 현재 케이스 YAML · 바뀐 TC 마다 전/후 레코드 · 사라진 TC 목록 · 새 PRD 절 본문 · 규칙("바뀐 부분만 고쳐라, covers 에서 사라진 id 는 빼고 대체 id 가 있으면 넣어라, 나머지 단계는 건드리지 마라").
3. Hermes 출력 → §7.2 검증(요청 TC = 새 covers 후보 집합) → 초안(source `hermes-revise`, `case_id` 는 원 케이스 id, note 에 어떤 TC 가 어떻게 바뀌었는지).
4. 사람이 초안 화면에서 원본과 diff 를 보고 승인 → PR. 원 케이스 파일을 플랫폼이 고치지 않는다.

버튼 경로이므로 프롬프트는 플랫폼이 조립하고 해시가 남는다(§13-8 유지).

### 3.4 Hermes 시스템 프롬프트(요지)

"너는 이 팀의 QA 엔지니어다. 기준(TC)은 SSOT·OpenAPI 에서 파생된 것이고 네가 만들지 않는다. 케이스를 쓰거나 고칠 때는 `qa_draft_create` 로 초안을 내고, 검증 사유가 돌아오면 고쳐서 다시 낸다. 실행·발행·승인은 사람이 버튼으로 한다 — 요청받으면 어디서 누르는지 링크로 안내한다. 답은 도구로 읽은 사실에 근거하고, 모르는 것은 모른다고 한다. 회원 UUID 같은 식별값은 응답에 옮기지 않는다."

### 3.5 대표 시나리오

| 사람이 말하는 것 | Hermes 가 하는 것 |
| --- | --- |
| "room 도메인에서 아직 안 덮은 정책 TC 중 지금 케이스로 만들 수 있는 것 골라 줘" | `qa_catalog_search(domain=room, layer=policy, only=uncovered)` → 제외 사유·바인딩 유무를 보고 후보 제시 |
| "G.room.create#8 케이스 써 줘" | `qa_tc_get` · `qa_spec_op(createRoom)` · `qa_prd_section(룸 생성, 4.7)` → YAML → `qa_draft_create` → 검증 통과/사유 보고 + 초안 링크 |
| "어제 배포 검증 왜 실패했어?" | `qa_run_list(trigger=deploy-sanity)` · `qa_run_get(with_steps)` → 단계·응답 인용해 해석. 진단 버튼과 같은 분류 |
| "SSOT 가 바뀐 뒤 손봐야 할 케이스 뭐야?" | `qa_changes` → 영향 케이스와 무엇이 바뀌었는지 → [다시 쓰기] 버튼 안내 |
| "룸 탐색 PRD 4.2 절에서 TC 뽑아 줘" | `qa_prd_section` → `qa_manual_tc_propose` → 초안(kind tc) |
| "스프린트 smoke 돌려 줘" | 돌리지 않는다. 대시보드 링크 |

## 4. 흐름

```text
브라우저 ─POST /chat/{id}/send─▶ qa-platform ─POST /v1/chat/completions (세션키 qa-chat-{id})─▶ hermes-gateway
                                                                                         │ tools/call
                                                                              ┌──────────┴──────────┐
                                                                              ▼                     ▼
                                                                   qa-platform /mcp          mcp-proxy /mcp (llm-wiki)
                                                                   (읽기 · 초안)              (위키 읽기 · wiki_apply)
                                                                              │
                                                                   sqlite: drafts · events(mcp.call)
브라우저 ◀─ 응답 + 그 턴의 도구 호출 + 초안 링크 ─ qa-platform ◀─────────── 응답 ────────── hermes-gateway
```

## 5. 데이터 모델

```text
chats          id, created_at, operator, title, session_key, context(json: run/case/tc), status(open|closed), turns
chat_messages  id, chat_id, at, role(user|assistant|system), content, tool_calls(json, 있으면), draft_ids(json)
events         chat.create · chat.send(chars) · chat.close · mcp.call(tool, args 요약, ok, ms) · draft.generate(source hermes-chat|hermes-revise)
drafts.source  hermes | explorer | hermes-chat | hermes-revise ;  drafts.kind  case | tc (서술 TC 제안)
catalog changes.json  항목에 before 스냅샷
```

## 6. 계약 변경

| 항목 | 변경 |
| --- | --- |
| 라우트 | `/chat`, `/chat/new`, `/chat/{id}`, `POST /chat/{id}/send`, `POST /chat/{id}/close`, `POST /cases/{id}/revise`(다시 쓰기), `POST /catalog/propose-tc`. 전부 팀 세션·운영자 필수 |
| MCP | `POST /mcp` — 내부 전용, `Authorization: Bearer QA_MCP_TOKEN`. Caddy `@qa` 에서 `/mcp` 는 403 |
| compose.ec2 | qa-platform: `QA_MCP_TOKEN`. hermes-config-init: `mcp_servers.qa-platform` 병합(include 목록 = §3.1). hermes-gateway `depends_on: qa-platform` 은 두지 않는다(qa 프로필과 hermes 프로필이 독립; 첫 도구 호출 때 연결) |
| SSM | `/plady/agent-platform/<env>/qa-mcp-token` **신규 1건** (§8-2) → `ec2-deploy.sh` 가 `.env.ec2` 에 `QA_MCP_TOKEN` 으로 |
| 백엔드·team-wiki-v2 | 변경 없음 |

## 7. 단계

| 단계 | 내용 | 비고 |
| --- | --- | --- |
| P4a | QA MCP 서버(읽기 10 + 제안 3) + compose 등록 + 도구 호출 감사 로그 | Slack 의 Hermes 도 같은 도구를 얻는다 — "이번 스프린트 smoke 결과?" 에 답할 수 있게 된다 |
| P4b | 채팅창 + 컨텍스트 첨부 + 도구 호출 표시 | Hermes 응답 트레이스 형식 확인(전제 5) 후 |
| P4c | [바뀐 기준으로 초안 다시 쓰기] + 변경 이력 before 스냅샷 | 버튼 경로, 채팅과 독립 |
| P4d | [PRD 절에서 서술 TC 제안] | P4a 의 `qa_manual_tc_propose` 재사용 |

## 8. 결정 필요

| # | 질문 | 권장 | 대안 |
| --- | --- | --- | --- |
| 1 | 채팅창에서 Hermes 가 `wiki_apply` 를 부를 수 있다(전제 3). 어떻게 할까 | **수용**: 팀 3명이 이미 Slack 에서 같은 권한을 갖고 있고, 위키 변경은 git 이라 되돌릴 수 있다. 채팅 기록에 남고, 시스템 프롬프트에 "QA 채팅에서는 위키를 쓰지 않는다" 를 넣는다(강제는 아님) | QA 전용 Hermes 인스턴스(별도 config, `wiki_apply` 제외) — 컨테이너·OAuth 세션이 하나 더 필요 |
| 2 | QA MCP 인증 토큰 | **새 SSM `qa-mcp-token`** — 위키 토큰과 범위 분리. 사람 작업 1건(SSM 주입) | `MCP_BEARER_TOKEN` 재사용(작업 없음, 범위 섞임) |
| 3 | 채팅으로 만든 초안의 근거 | **대화 기록 + 도구 호출 로그**로 충분하다고 본다. 버튼 경로의 프롬프트 해시 수준 재현성은 채팅에선 포기 | 채팅 초안을 금지하고 "초안 생성 버튼으로 가라" 만 안내 |
| 4 | 스트리밍 | 없음. 동기 + 진행 표시 + 180초 | SSE 스트리밍(표준 라이브러리로 가능하나 Hermes 스트리밍 도구 트레이스 형식 미확인) |
| 5 | 대화 한도 | 대화당 40턴, 30일 지나면 닫힘 표시(삭제 안 함) | 무제한 |
| 6 | Slack 의 Hermes 에도 QA 도구를 줄지 | **준다**(include 는 전역이라 자연히). 읽기·제안뿐이라 위험 없음 | qa-platform 서버를 채팅 세션에서만 노출 — Hermes config 로는 구분이 안 되어 사실상 불가 |

## 9. 리스크

- **위키 쓰기 오남용**(§8-1). 감사 로그와 git revert 가 방어선이다.
- **도구 호출 상관의 한계**: 동시 대화 시 `mcp.call` 이 어느 대화 것인지 확실치 않다. 표시는 "이 시각대의 호출" 로 정직하게.
- **비용·지연**: 도구를 여러 번 부르면 한 턴에 수십 초·수만 토큰. 턴 한도와 타임아웃으로 막고, 채팅 사용량을 events 로 센다.
- **Hermes 가 초안 검증을 못 넘길 때**: 사유를 돌려주고 스스로 고치게 한다. 3번 넘게 실패하면 사람에게 넘기라고 프롬프트에 둔다.
- **원칙 ① 착시**: "Hermes 가 돌렸다" 는 일이 없어야 한다. 실행 도구를 아예 만들지 않는 것으로 구조적으로 막는다.
