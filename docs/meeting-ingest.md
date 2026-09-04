# 회의록 ingest 경로 (구현계획 Phase 2)

[`dev-environment-implementation-plan.md`](dev-environment-implementation-plan.md) Phase 2의 "회의(멘토링/데일리 스크럼/기획 회의) → 위키 지식" 흐름 계약입니다. 다이어그램의 webex/slack → API → llm-wiki 화살표를 단계적으로 구현합니다.

## 결정 사항

- **공개 수집 API는 지금 만들지 않는다.** 새 public endpoint는 PLA-247 ingress(DNS/ACM/ALB) 계약 변경이 선행되어야 하므로 별도 이슈로 미룬다. Hermes path 확장 vs 별도 서비스(`api.agent.plady.io`) 결정도 그 이슈에서 한다.
- ~~**n8n은 켜지 않는다.**~~ 2026-09-04 해제. Webex 경로는 n8n 이 자동 수집한다 — [`webex-ingest.md`](webex-ingest.md). notion/Slack 은 여전히 아래 v0(사람) 경로와 Hermes Slack 앱이 맡는다.
- **v0는 로컬 운영자 경로로 시작한다.** 회의록은 notion에 남기고(레지스트리의 notion MCP read 계약), 운영자가 로컬에서 `scripts/mcp-call.py`로 llm-wiki MCP `wiki_ingest`(approve tier)를 호출해 위키에 반영한다. 사람이 호출 자체를 수행하므로 "write는 사람 승인 뒤에만" 기준을 자연 충족한다.

## v0 흐름

```
notion 회의록 (PRD/스크럼/멘토링)
   → 운영자가 markdown 으로 추출
   → scripts/mcp-call.py call wiki_ingest --args @meeting.json
   → llm-wiki 검증·커밋·인덱싱 → team-wiki-v2
```

- 엔드포인트: 로컬 `http://localhost:18765/mcp` 또는 운영 `https://mcp.agent.plady.io/mcp`.
- 인증: `MCP_BEARER_TOKEN` 환경변수(값은 SSM `/plady/agent-platform/<env>/llm-wiki-mcp-bearer-token`에서 사람이 조회). 값을 인자/파일로 넘기지 않는다.
- `wiki_ingest` 인자 스키마는 추측하지 않는다 — `scripts/mcp-call.py list-tools` 출력의 `inputSchema`가 SSOT다.

### smoke

```bash
# credential-free (401 확인)
curl -i http://localhost:18765/mcp

# 사람(token 보유자)이 수행
export MCP_BEARER_TOKEN="..."
scripts/mcp-call.py list-tools
```

> ⚠️ `scripts/mcp-call.py`는 아직 live 엔드포인트 대상 smoke 전입니다. 첫 사용자가 `list-tools`로 동작 확인 후 이 경고를 제거해 주세요.

## 회의록 payload 규약 (v0)

`wiki_ingest`에 넘기기 전 markdown 본문 앞머리에 다음 메타데이터를 둔다(위키 페이지 frontmatter로 보존).

| 필드 | 값 |
| --- | --- |
| `meeting_type` | `mentoring` \| `daily-scrum` \| `planning` |
| `held_at` | 회의 일시 (ISO-8601, KST) |
| `source` | `notion` \| `slack` \| `webex` |
| `source_ref` | 원본 링크(notion 페이지 URL 등) |

redact 규칙은 [`otel-collector.md`](otel-collector.md)와 동일 기준: 시크릿/토큰, PII를 남기지 않는다.

## 이후 단계 (별도 이슈)

1. **수집 API**: PLA-247 ingress 계약에 endpoint 추가 후, 위 payload 규약을 그대로 받는 서비스 구현. Hermes path 확장 vs 별도 서비스 결정 포함.
2. **n8n 자동화**: PLA-251 활성화 이후, notion 회의록/Slack 스레드를 주기 수집해 수집 API로 전달하는 워크플로.
3. ~~**webex**~~: 완료 — Webex `meetingTranscripts` 웹훅 → n8n → `wiki_apply`(archive) → Hermes 초안 → `wiki_apply`(knowledge). [`webex-ingest.md`](webex-ingest.md).
4. **Session → wiki 자동 ingest**: Claude/codex 세션 종료 훅이 요약을 같은 payload 규약으로 전송 (Phase 4).
