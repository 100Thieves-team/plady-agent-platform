# 개발 환경 아키텍처 구현 계획

[`dev-environment-architecture.drawio`](../dev-environment-architecture.drawio) 다이어그램과 현재 구현 상태를 대조해, 미구현 구간의 구현 계획을 정리합니다. 플랫폼 계약 SSOT는 [`platform-contract.md`](platform-contract.md)이며, 이 문서는 계획 문서입니다.

## 현재 상태 요약

구현 완료(다이어그램과 일치):

- Hermes Agent → llm-wiki: `hermes-gateway` live, `hermes-config-init`이 llm-wiki MCP를 read-only로 배선 (PLA-249)
- Slack Chat Bot: Hermes Socket Mode 네이티브 플랫폼 (PLA-244-B) — `SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN` 주입 시 활성화, allowlist fail-closed
- WIKI MCP: `mcp-proxy` bearer 보호 엔드포인트 live, 도구 정책 레지스트리 (PLA-250)
- OTEL collector: 내부 전용 live (PLA-251)
- github repo 구조: `.agents/skills/` (Skill/Agents.md), ADR/knowledge 문서는 [`team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)로 분리 저장

미구현 갭:

| # | 갭 | 현재 상태 |
| --- | --- | --- |
| 1 | 회의 수집 API — webex/slack의 멘토링·데일리 스크럼·기획 회의 → API → 위키 | 코드 없음. Slack은 챗봇 경로만 존재, webex는 저장소 전체에 참조 없음 |
| 2 | n8n 파이프라인 — n8n → API/llm-wiki ingest 자동화 | 예약/비활성 플레이스홀더 (compose 블록 주석, ALB 503) |
| 3 | Code Review Agent — 팀 지식 기반 github PR 리뷰 | 저장소는 [`review-swarm`](https://github.com/100Thieves-team/review-swarm)으로 확정, 이 플랫폼과의 배선은 미구현 |
| 4 | notion/figma MCP — 로컬 Claude/codex Session → notion 회의록, figma 와이어프레임/KPT | `config/mcp-registry.yaml`에 항목 없음 |
| 5 | github/linear MCP 활성화 | 레지스트리에 `contract-only` (credential 미주입, linear는 transport tbd) |
| 6 | 로컬 Agent 로그 → OTEL | collector가 compose 내부 전용이라 로컬 개발 머신 텔레메트리가 도달할 경로 없음 |
| 7 | Agent 로그/Session → WIKI MCP 자동 ingest | [`agent-ingest-workflow.md`](agent-ingest-workflow.md) 수동 워크플로만 존재 |

## Phase 1 — MCP 레지스트리 완성 (로컬 에이전트 연결 활성화)

의존성이 없고 가장 저렴한 단계. 다이어그램의 "local Claude/codex → 외부 서비스" 연결을 살립니다.

1. **github/linear MCP 활성화**
   - SSM에 `/plady/agent-platform/<env>/github-mcp-pat`, `/plady/agent-platform/<env>/linear-mcp-api-key` 주입.
   - linear는 원격 HTTP(`mcp.linear.app`)로 transport 확정.
   - 레지스트리 status를 `contract-only` → `live`로 승격. 기존 tool_policy(read allow / mutation approve)는 그대로 소비.
2. **notion/figma 레지스트리 항목 추가**
   - 기존 컨벤션(`contract-only` → credential 주입 → `live`)을 따라 notion MCP(회의록 read), figma MCP(와이어프레임/KPT read) 항목을 `config/mcp-registry.yaml` + [`mcp-registry.md`](mcp-registry.md)에 추가.
   - 둘 다 read-only allow로 시작, write는 approve 게이트가 준비될 때까지 default-deny.

## Phase 2 — 회의 수집 API + ingest 파이프라인

다이어그램에서 가장 큰 갭인 "회의 → API → 위키 지식" 흐름.

3. **수집 API 정의**
   - 결정 필요: `hermes.agent.plady.io` 밑의 새 path vs 별도 서비스(`api.agent.plady.io`). 별도 서비스라면 PLA-247 ingress 계약에 서브도메인 추가.
   - 입력 계약: 회의 종류(멘토링/스크럼/기획), 원문 transcript, 출처(webex/slack/notion).
4. **n8n 활성화 (PLA-251 소관)**
   - compose `n8n` 블록 활성화, `n8n.agent.plady.io` ALB 503 해제, 레지스트리 `reserved` → `live`.
   - n8n 워크플로가 notion 회의록/Slack 스레드를 주기적으로 수집해 수집 API 또는 `wiki_ingest`로 전달.
5. **webex 연동**
   - webex 녹취/회의록 export API 조사부터 시작 (저장소에 참조가 전혀 없어 스코프 불확실).
   - 초기에는 "notion에 회의록을 남기면 n8n이 가져가는" 우회 경로로 시작하고, webex 직접 연동은 후순위.

## Phase 3 — Code Review Agent: review-swarm 배선

Code Review Agent는 [`100Thieves-team/review-swarm`](https://github.com/100Thieves-team/review-swarm)을 사용합니다. review-swarm은 self-hosted GitHub Actions 러너에서 로컬 Claude Code/Codex CLI로 멀티에이전트 리뷰(안전 게이트/전문 분석가/가치 에이전트 + 적대적 verify + 결정론적 policy gate)를 실행하고, 에이전트별 GitHub App 봇으로 PR 인라인 리뷰를 게시합니다. 새로 만드는 것이 아니라 이 플랫폼에 **배선**하는 작업입니다.

6. **review-swarm 도입**
   - self-hosted 러너 준비: Node.js ≥ 20.19 + `claude`/`codex` CLI 로그인 상태. 후보는 기존 EC2 호스트 또는 별도 러너 — EC2는 무인 배포 호스트라 CLI 대화형 로그인 세션 유지가 관건, 결정 필요.
   - 대상 저장소(`plady-agent-platform`, `team-wiki-v2` 등)에 PR opened/synchronize 워크플로 배선, 에이전트별 GitHub App 봇 등록.
   - Blackboard의 "팀 규칙" 입력을 WIKI MCP(read-only, 기존 `llm-wiki-mcp-bearer-token` 계약 소비)로 연결해, 다이어그램의 "Code Review Agent ← llm-wiki 지식" 화살표를 충족.
   - 리뷰 게시 외 쓰기 권한은 부여하지 않음(레지스트리 default-deny 원칙 유지).

## Phase 4 — 관측성 마무리

7. **로컬 에이전트 → OTEL 경로**
   - collector는 내부 전용 계약(PLA-251) 유지. 공개 노출 대신 로컬 개발 시 `docker compose --profile otel`로 같은 collector를 로컬에 띄워 파일 export하는 현재 방식을 유지하고, EC2 쪽은 Hermes/mcp-proxy 컨테이너의 OTLP export만 배선.
   - 다이어그램의 "Agent 로그 → Otel"은 이 범위로 재해석.
8. **Session → wiki 자동 ingest**
   - Claude/codex 세션 종료 시 요약을 `wiki_ingest`로 보내는 훅/스킬. Phase 2의 ingest 계약 확정 이후 진행.

## 핵심 의사결정 포인트

- Phase 2: 수집 API 위치 — Hermes path 확장 vs 별도 서비스.
- Phase 2: webex 직접 연동 여부 vs notion 우회 경로.
- Phase 3: review-swarm self-hosted 러너 호스트 — 기존 EC2 vs 별도 머신(CLI 로그인 세션 유지 문제).

나머지는 기존 PLA 계약(247 ingress, 250 레지스트리, 251 n8n/otel) 컨벤션을 그대로 따릅니다.
