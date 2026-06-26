# PLA-244 Slack - Hermes Agent handoff 계약

이 문서는 PLA-244 작업자가 `plady-agent-platform`의 endpoint/secret/session 계약을 어디서 소비해야 하는지 정리합니다. 상세 platform 계약은 [`platform-contract.md`](platform-contract.md)를 SSOT로 둡니다.

## PLA-244가 소비할 endpoint

| 용도 | 계약 |
| --- | --- |
| Hermes public origin | `https://hermes.agent.plady.io` |
| Hermes OpenAI-compatible base URL | `https://hermes.agent.plady.io/v1` |
| Wiki UI reference | `https://wiki.agent.plady.io` |
| llm-wiki MCP endpoint | `https://mcp.agent.plady.io/mcp` |
| n8n | `https://n8n.agent.plady.io`는 reserved only. PLA-244에서 runtime dependency로 사용하지 않는다. |
| OTEL | internal-only. PLA-244에서 public OTEL URL을 요구하지 않는다. |

### Slack URL 주의

- PLA-244는 Slack app 설정에서 사용할 URL을 `https://hermes.agent.plady.io` origin 아래로 맞춘다.
- PLA-244가 OpenAI-compatible client를 설정할 때는 `https://hermes.agent.plady.io/v1`을 base URL로 사용한다.
- Slack event/interactivity/OAuth path의 최종 shape는 Hermes runtime owner인 PLA-249와 맞춘다.
- PLA-246 범위에서는 path를 구현하거나 Slack app을 설정하지 않는다.

### OpenAI-compatible client 호출 계약 (PLA-249 확정)

PLA-249 런타임 runbook은 [`hermes-gateway.md`](hermes-gateway.md)가 SSOT다. PLA-244는 아래 헤더 계약을 그대로 소비한다.

| 항목 | 값 |
| --- | --- |
| Base URL | `https://hermes.agent.plady.io/v1` |
| Auth header | `Authorization: Bearer <API_SERVER_KEY>` (값은 아래 secret reference에서 조회) |
| Session header(선택) | `X-Hermes-Session-Key: <scope>` — Slack workspace/user 단위 세션 스코프. ≤256자, control char(`\r`,`\n`,`\x00`) 금지, 응답에 echo. |
| Health(무인증) | `GET https://hermes.agent.plady.io/health` → `{"status":"ok"}` |

## PLA-244가 소비할 secret reference

값은 기록하지 않습니다. PLA-244는 아래 **parameter 이름** 또는 그에 매핑된 runtime secret reference만 인용합니다.

| Secret reference | 목적 |
| --- | --- |
| `/plady/agent-platform/<env>/hermes-api-server-key` | Slack/Hermes entrypoint가 Hermes API boundary를 호출하거나 검증할 때 사용하는 key reference. |
| `/plady/agent-platform/<env>/llm-wiki-mcp-bearer-token` | Hermes가 llm-wiki MCP endpoint를 호출할 때 사용하는 bearer token reference. |

운영자가 값을 복사해 Linear, README, PR description, Slack thread에 붙여넣지 않습니다. 값 조회/주입은 후속 runtime/infra 작업의 배포 절차에서만 처리합니다.

## Session/ownership 계약

- Slack event 수신과 Slack UX 구성은 PLA-244의 책임입니다.
- Hermes Gateway runtime, auth boundary, agent session lifecycle은 PLA-249의 책임입니다.
- MCP registry/safe tool policy는 PLA-250의 책임입니다.
- DNS/ACM/ALB와 public ingress는 PLA-247의 책임입니다.
- PLA-246은 session lifecycle과 MCP safe tool policy의 owner를 지정할 뿐, 상세 계약을 정의하지 않습니다.
- PLA-244는 Hermes session storage schema나 MCP registry를 직접 정의하지 않습니다. 필요한 필드는 PLA-249/250 계약에 이슈 링크로 요청합니다.

## Ready checklist for PLA-244

PLA-244는 아래가 충족되면 platform 쪽 계약을 소비할 수 있습니다.

- [ ] `https://hermes.agent.plady.io` ingress가 PLA-247/249에서 준비됨.
- [ ] `https://hermes.agent.plady.io/v1` OpenAI-compatible base URL이 PLA-249에서 준비됨.
- [ ] Slack에서 호출할 Hermes path가 PLA-249에서 확정됨.
- [ ] Agent session lifecycle/start-stop-health 계약이 PLA-249에서 확정됨.
- [ ] MCP registry/safe tool policy가 PLA-250에서 확정됨.
- [ ] `/plady/agent-platform/<env>/hermes-api-server-key` 값이 secret store에 준비됨.
- [ ] Hermes가 MCP를 호출해야 하는 경우 `/plady/agent-platform/<env>/llm-wiki-mcp-bearer-token` 값이 secret store에 준비됨.
- [ ] 실제 secret 값은 Slack/Linear/GitHub 문서에 남기지 않음.
