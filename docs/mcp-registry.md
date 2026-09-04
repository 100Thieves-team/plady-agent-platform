# MCP 레지스트리 계약과 안전한 도구 정책 (PLA-250)

이 문서는 `plady-agent-platform`가 노출/소비하는 **MCP 서버 레지스트리**와 **허용/차단 도구 정책**의 SSOT입니다. Hermes Gateway(PLA-249)와 [PLA-244](https://linear.app/100-thieves/issue/PLA-244) Slack 연동이 *어떤 MCP를, 어떤 인증으로, 어떤 도구 권한으로* 호출할 수 있는지를 추측 없이 소비할 수 있도록 합니다.

- endpoint/secret **이름 계약**의 상위 SSOT는 [`platform-contract.md`](platform-contract.md)입니다. 이 문서는 그 위에서 MCP 레지스트리/도구 정책을 확정합니다.
- Hermes 런타임 runbook은 [`hermes-gateway.md`](hermes-gateway.md), PLA-244 핸드오프는 [`pla-244-handoff.md`](pla-244-handoff.md)가 SSOT입니다.
- 머신 소비용 선언 파일은 [`config/mcp-registry.yaml`](../config/mcp-registry.yaml)입니다. 이 문서와 config의 **서버 집합·도구 tier는 항상 일치**해야 합니다.

## 범위와 비목표

- 이 문서는 **계약 문서**입니다. Slack 이벤트 UX, Calendar write workflow, GitHub/Linear mutation 기본 활성화는 만들지 않습니다.
- 실제 OAuth/PAT/API key **값은 어디에도 남기지 않습니다**(문서·코드·Linear·PR·Slack). 각 runtime이 Secret Manager/SSM 등 승인된 store에서 조회합니다.
- secret reference는 **이름**만 사용합니다. `llm-wiki-mcp-bearer-token`만 `platform-contract.md`에 비준된 authoritative 이름이고, 나머지(github/linear/slack/google-calendar/context7)는 컨벤션을 따른 **제안 placeholder**이며 소비 이슈가 확정하기 전까지 보장값이 아닙니다.

## MCP 서버 레지스트리

| 서버 | transport | auth secret ref (이름만) | 상태 | secret ref 권위 |
| --- | --- | --- | --- | --- |
| `llm-wiki` | HTTP `https://mcp.agent.plady.io/mcp` | `/plady/agent-platform/<env>/llm-wiki-mcp-bearer-token` | live | **authoritative** (`platform-contract.md`) |
| `github` | stdio `npx -y @modelcontextprotocol/server-github` | `/plady/agent-platform/<env>/github-mcp-pat` | contract-only | proposed placeholder |
| `linear` | remote HTTP `https://mcp.linear.app/mcp` | `/plady/agent-platform/<env>/linear-mcp-api-key` | contract-only | proposed placeholder |
| `notion` | remote HTTP `https://mcp.notion.com/mcp` | `/plady/agent-platform/<env>/notion-mcp-oauth` (OAuth) | contract-only | proposed placeholder |
| `figma` | remote HTTP `https://mcp.figma.com/mcp` | `/plady/agent-platform/<env>/figma-mcp-oauth` (OAuth) | contract-only | proposed placeholder |
| `slack` | **platform** (Socket Mode, MCP 서버 아님) | `/plady/agent-platform/<env>/slack-bot-token` + `…/slack-app-token` + `…/slack-allowed-users` | PLA-244-B 확정 | confirmed / PLA-244-owned |
| `google-calendar` | TBD (stdio \| http); auth=OAuth | `/plady/agent-platform/<env>/google-calendar-mcp-oauth` | contract-only | proposed placeholder |
| `context7` | remote HTTP `https://mcp.context7.com/mcp` | `/plady/agent-platform/<env>/context7-api-key` (optional) | contract-only | proposed placeholder |
| `n8n` | — | — | reserved (**PLA-251 소관**) | — |
| 그 외 미등록 | — | — | — | **default-deny** |

- `llm-wiki`만 현재 live 입니다(이미 compose `mcp-proxy`가 bearer 보호). 나머지는 **계약 entry**이며, 실제 연결은 소비 이슈(PLA-244 등)가 credential 주입 후 수행합니다.
- `n8n.agent.plady.io`는 [`platform-contract.md`](platform-contract.md)에서 reserved이며 실제 계약은 PLA-251 소관입니다. 여기서는 reserved 스텁(현재 live 아님, default-deny)만 둡니다.
- **Slack은 MCP 서버가 아니라 hermes 메시징 *플랫폼*입니다**(Socket Mode). 같은 `gateway run` 프로세스가 서빙하며 `mcp_servers`가 아니라 `SLACK_*` env + config `platforms.slack`로 구성합니다. PLA-244-B가 secret 이름을 확정했습니다: `slack-bot-token`(xoxb) + `slack-app-token`(xapp) + `slack-allowed-users`(Member ID allowlist, fail-closed). 런북 [`hermes-gateway.md`](hermes-gateway.md) "Slack 연동".
- **transport 표기 규칙**: MCP 표준 transport는 `stdio`와 Streamable `http` 둘뿐입니다([MCP spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)). OAuth/PAT/API key는 transport가 아니라 **auth 계층**(`auth.*`)입니다. transport가 아직 안 정해진 서버는 `TBD (stdio \| http)`로 표기하고, 인증 방식은 auth 컬럼/필드에 둡니다.

## 안전한 도구 정책 (3-tier, default-deny)

모든 MCP 서버는 **default-deny** 기준입니다. 도구는 아래 3-tier로 분류합니다.

| Tier | 의미 | 승인 |
| --- | --- | --- |
| `allow` | read-only / 안전한 조회. 부수효과 없음. | 자동 허용 |
| `approve` | write/mutation. 호출 전 **명시적 사람 승인** 필요. | 호출 단위 승인 게이트 |
| `deny` | 관리/구조/파괴적. 런타임 승인으로 풀리지 않음. | 운영자 config opt-in 필요 |

레지스트리에 등록되지 않은 도구는 `default: deny`로 차단합니다.

### Write 승인 흐름 (approve tier)

1. Hermes가 호출하려는 도구가 레지스트리에서 `approve` tier인지 판정합니다(미등록 → `deny`로 즉시 거부).
2. `approve`면 도구를 즉시 실행하지 않고 **승인 요청 이벤트**를 발생시킵니다.
3. PLA-244가 Slack interactive(승인/거부 버튼)로 사람에게 노출하고, 누가 승인했는지 기록합니다.
4. 승인 → 호출 forward / 거부·타임아웃 → 호출 거부(에러 반환). 승인 스코프는 기본 **호출 단위**(세션 전체 승인 아님)입니다.

`deny` tier 도구는 위 흐름으로 풀리지 않으며, 운영자가 config에서 명시적으로 tier를 올려야만 활성화됩니다.

> ⚠️ **구현 현실 (PLA-244-B 확인)**: 위 흐름은 *설계 계약*이지만, 현재 hermes-agent(`v2026.4.3`)에는 **MCP 도구 호출을 가로채는 승인 게이트가 없습니다**. `approvals.mode`(manual/smart/off)는 셸 명령만 게이트하며, MCP first-invoke 승인은 업스트림 제안 단계([#16462](https://github.com/NousResearch/hermes-agent/issues/16462))입니다. 따라서 1~4단계를 강제할 런타임 수단이 없어, PLA-244는 `approve` tier(write) 도구를 **아예 노출하지 않음**(default-deny by omission)으로 "write는 승인 뒤에만" 기준을 충족합니다. write를 실제로 켜려면 별도 승인 메커니즘(자체 프록시/게이트)이 선행되어야 합니다 — 후속 이슈.

## llm-wiki MCP 도구 분류 (23개)

dispatch table 기준(`llm-wiki/src/mcp/tools.rs`) 정확히 30개. 합계: allow 16 + approve 7 + deny 7 = 30 (중복·누락 없음). 2026-09 fork 추가분 7개(`llm-wiki/FORK-CHANGES.md`)는 아래 표 끝에 있다. `wiki_export`는 read처럼 보이지만 결과를 디스크에 쓰므로(`ops/export.rs`의 `fs::write`) approve로 둡니다.

| 도구 | R/W | tier | 목적 |
| --- | --- | --- | --- |
| `wiki_search` | R | allow | 전문(BM25) 검색 |
| `wiki_list` | R | allow | 페이지 목록(페이지네이션) |
| `wiki_content_read` | R | allow | 슬러그/URI로 페이지 내용 읽기 |
| `wiki_resolve` | R | allow | 슬러그/URI → 로컬 경로 해석 |
| `wiki_stats` | R | allow | 위키 헬스/구조 대시보드 |
| `wiki_lint` | R | allow | 결정적 lint(고아/깨진 링크 등) |
| `wiki_history` | R | allow | 페이지 git 커밋 이력 |
| `wiki_suggest` | R | allow | 연결 후보 페이지 추천 |
| `wiki_graph` | R | allow | 개념 그래프 생성(mermaid/dot/llms) |
| `wiki_index_status` | R | allow | 검색 인덱스 상태/staleness |
| `wiki_spaces_list` | R | allow | 등록된 wiki space 목록 |
| `wiki_content_write` | W | **approve** | 페이지 내용 쓰기(파일 수정) |
| `wiki_content_new` | W | **approve** | 새 페이지/섹션 생성 |
| `wiki_content_commit` | W | **approve** | 변경 git 커밋 |
| `wiki_ingest` | W | **approve** | 검증·(선택 redact)·커밋·인덱싱 |
| `wiki_export` | W | **approve** | llms.txt/JSON 등 내보내기 — **파일을 디스크에 씀**(기본 `llms.txt`, 임의 path 가능) |
| `wiki_rules` | R | allow | AGENTS.md 운영 규칙 반환 |
| `wiki_catalog` | R | allow | 종류(topic/source/…)별 페이지 목록 |
| `wiki_recent` | R | allow | git 이력에서 최근 변경 |
| `wiki_context` | R | allow | 질문에 맞는 페이지 본문 묶음(예산 내) |
| `wiki_ingest_plan` | R | allow | ingest 계획 — 필요한 페이지·후보·expected_head. 쓰지 않음 |
| `wiki_apply` | W | **approve** | 트랜잭션 ingest — raw/source/topic 한 번에 검증·커밋 |
| `wiki_save_answer` | W | **approve** | 질의 답변을 `answers/` 페이지로 커밋 |
| `wiki_spaces_create` | W | **deny** | 새 wiki repo 초기화/등록 |
| `wiki_spaces_register` | W | **deny** | 기존 repo 레지스트리 등록 |
| `wiki_spaces_remove` | W | **deny** | space 제거(디스크 삭제 가능) |
| `wiki_spaces_set_default` | W | **deny** | 기본 space 변경 |
| `wiki_config` | R/W | **deny** | 설정 get/set/list (set 포함) |
| `wiki_schema` | R/W | **deny** | 타입 스키마 list/add/remove/validate |
| `wiki_index_rebuild` | W | **deny** | 검색 인덱스 전체 재구축 |

> `wiki_config`/`wiki_schema`는 read 액션도 있으나 MCP 게이팅이 **도구 단위**라, 가장 위험한 능력(set/add/remove) 기준으로 `deny`로 둡니다. read 액션 접근이 막히는 **알려진 capability 손실**이며, 필요 시 후속 이슈에서 sub-tool 단위 정책으로 회수합니다.

### 다른 서버 mutation gated 정책 (요약)

- `github`: read(이슈/PR/코드 조회 등) `allow`, mutation(예: `create_issue`/`update_issue`/`create_or_update_file`/`merge_pull_request`) `approve`. 기본 활성화하지 않음(이슈 비목표).
- `linear`: read `allow`, mutation(이슈/코멘트 생성·수정) `approve`. transport는 공식 원격 HTTP(`https://mcp.linear.app/mcp`)로 확정(구형 SSE `/sse`). auth는 api_key(Bearer) 기본, OAuth 전환 여부는 소비 이슈가 확정.
- `notion`: read(회의록 조회 — PRD/스크럼/멘토링 회의록을 ingest 파이프라인 입력으로 사용) `allow`, mutation(페이지 생성·수정) `approve`.
- `figma`: read(와이어프레임/KPT 회고 컨텍스트) `allow`, mutation `approve`(현재 write 용도 없음). 로컬 데스크톱 서버(`http://127.0.0.1:3845/mcp`)는 개인 개발용 대안 경로.
- `slack`: PLA-244가 tier 확정. 메시지 전송 등 mutation은 `approve` 기본.
- `google-calendar`: read(`list events`/`get event`) `allow`, write(`create`/`update`/`delete` event) `approve`. **Calendar write workflow 구현은 범위 밖**(정책만 정의).
- `context7`: 문서 조회 read-only 도구만 노출 → 전부 `allow`, write 없음.
- `n8n`: reserved. 현재 도구 노출 없음 → `default: deny`.

## MCP 등록 runbook + smoke 절차

새 MCP를 레지스트리에 추가하는 순서:

1. [`config/mcp-registry.yaml`](../config/mcp-registry.yaml)에 server entry 추가(transport, auth.secret_ref 이름, status).
2. secret reference **이름** 확정(`/plady/agent-platform/<env>/...`). 값은 넣지 않음.
3. Hermes `~/.hermes/config.yaml`의 `mcp_servers`에 매핑(HTTP는 `url`+`headers`, stdio는 `command`/`args`/`env`).
4. `tool_policy`로 allow/approve/deny tier 지정. 미분류 도구는 `default: deny`.

### smoke (credential 유무로 2단계)

- **credential-free smoke (지금 실행 가능)** — `llm-wiki`(live)만 무인증 401 확인:
  ```bash
  # 운영
  curl -i https://mcp.agent.plady.io/mcp        # -> 401 (WWW-Authenticate: Bearer)
  # 로컬 (compose mcp-proxy)
  curl -i http://localhost:18765/mcp            # -> 401
  ```
  인증된 200 확인은 secret ref 값을 주입한 **사람**이 수행:
  ```bash
  curl -i -H "Authorization: Bearer <ref값>" http://localhost:18765/mcp
  ```
- **credential-required smoke (사람 주입 후)** — `github`/`linear`/`google-calendar`/`context7`는 실제 PAT/OAuth/key가 있어야 `tools/list`가 응답합니다. credential 주입 전에는 실행하지 않고, 아래 blocker 방식으로 기록합니다.

### credential blocker 기록 방식

- 레지스트리 `status` 필드 enum: `live` / `contract-only` / `pla-244-owned` / `reserved` / `blocked-missing-credential`. (`config/mcp-registry.yaml`가 emit하는 값과 동일.)
- secret ref가 아직 SSM에 없어 smoke 불가한 경우, Linear `## Codex Workpad`의 `Confusions`/`Notes`에 "어떤 server의 어떤 secret ref가 없어 smoke 불가"를 명시합니다. contract-only 서버 smoke는 기본적으로 이 경로로 처리합니다.

## Hermes `mcp_servers` 매핑 예시

`allow`+`approve` 합집합이 Hermes의 `tools.include`에 해당하고, `deny`는 include에서 제외합니다(실 키 값 없이 secret ref만 주석).

```yaml
# ~/.hermes/config.yaml (런타임 소유: PLA-249. 아래는 레지스트리 → Hermes 번역 예시)
mcp_servers:
  llm-wiki:
    url: https://mcp.agent.plady.io/mcp
    headers:
      Authorization: "Bearer ${LLM_WIKI_MCP_BEARER_TOKEN}"   # /plady/agent-platform/<env>/llm-wiki-mcp-bearer-token
    tools:
      include: [wiki_search, wiki_list, wiki_content_read, wiki_resolve, wiki_stats,
                wiki_lint, wiki_history, wiki_suggest, wiki_graph, wiki_index_status,
                wiki_spaces_list, wiki_export,
                wiki_content_write, wiki_content_new, wiki_content_commit, wiki_ingest]
      # deny tier(wiki_spaces_*, wiki_config, wiki_schema, wiki_index_rebuild)는 include 제외
```

> `approve` tier(`wiki_content_*`, `wiki_ingest`)는 include에 두되, 호출 전 [Write 승인 흐름](#write-승인-흐름-approve-tier)을 적용합니다.

## PLA-244 소비 체크리스트

PLA-244는 아래가 모두 명확하면 MCP 정책을 추측 없이 소비할 수 있습니다.

- [x] llm-wiki MCP endpoint: `https://mcp.agent.plady.io/mcp` (authoritative).
- [x] bearer secret ref: `/plady/agent-platform/<env>/llm-wiki-mcp-bearer-token` (authoritative).
- [x] write-capable 도구 승인 정책: [Write 승인 흐름](#write-승인-흐름-approve-tier).
- [x] Slack의 secret 이름/transport 확정(PLA-244-B): platform=Socket Mode, `slack-bot-token`+`slack-app-token`+`slack-allowed-users`. (Slack은 MCP 서버가 아니라 hermes 플랫폼.)

## 🙋 사람이 직접 해야 하는 일

> 실 secret/credential은 사람만 주입합니다. 값은 어디에도 커밋하지 않습니다. SSM 패턴은 [`hermes-gateway.md`](hermes-gateway.md)의 절차를 재사용합니다.

- `llm-wiki`: `MCP_BEARER_TOKEN`(로컬)/`/plady/agent-platform/<env>/llm-wiki-mcp-bearer-token`(SSM) 값 생성·주입.
- `github`: PAT 발급 → `/plady/agent-platform/<env>/github-mcp-pat`(SSM SecureString) 저장.
- `linear`: API key → `/plady/agent-platform/<env>/linear-mcp-api-key` 저장.
- `notion`: OAuth 연결(워크스페이스 관리자 승인) → `/plady/agent-platform/<env>/notion-mcp-oauth` 저장.
- `figma`: OAuth 연결 → `/plady/agent-platform/<env>/figma-mcp-oauth` 저장.
- `google-calendar`: OAuth 토큰 → `/plady/agent-platform/<env>/google-calendar-mcp-oauth` 저장.
- `context7`: (선택) API key → `/plady/agent-platform/<env>/context7-api-key` 저장.
- `slack`(플랫폼): `slack-bot-token`(xoxb)·`slack-app-token`(xapp)·`slack-allowed-users`(Member ID, 쉼표구분)를 SSM SecureString으로 저장. 절차는 [`hermes-gateway.md`](hermes-gateway.md) "Slack 연동".

```bash
# 예시: SSM SecureString 저장 (<env> = dev|staging|prod). 값은 절대 커밋/공유 금지.
aws ssm put-parameter --region ap-northeast-2 \
  --name "/plady/agent-platform/dev/github-mcp-pat" \
  --type SecureString --value "<PAT 값>"
```

credential이 아직 없어 smoke가 막힌 서버는 위 [credential blocker 기록 방식](#credential-blocker-기록-방식)으로 Workpad에 남깁니다.
