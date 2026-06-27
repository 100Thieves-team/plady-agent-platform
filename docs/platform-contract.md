# Plady Agent Platform 계약

이 문서는 `plady-agent-platform` 레포가 제공해야 하는 platform foundation 계약의 SSOT입니다. PLA-247/249/250/251 작업자는 이 문서를 기준으로 구현을 이어가고, 구현 중 계약이 바뀌면 이 문서를 먼저 갱신합니다.

## 범위와 비목표

- 이 문서는 **계약 문서**입니다. DNS, ACM, ALB, Terraform resource, Hermes runtime, MCP registry, OTEL collector, n8n, Slack 구현을 만들지 않습니다.
- 실 secret/token 값은 이 문서·코드·Linear에 절대 남기지 않습니다. 값은 각 runtime이 Secret Manager/SSM 등 승인된 secret store에서 조회합니다.
- 기존 EC2/Caddy/`plady.kro.kr` 문서는 legacy wiki deployment 참고 자료입니다. 새 platform endpoint 계약은 이 문서를 우선합니다.


## Delegated contract boundaries

PLA-246 fixes the foundation contract: domain ownership, public endpoint names, reserved/internal endpoint boundaries, and secret parameter names. It does **not** define the full Hermes agent session lifecycle or MCP registry/safe tool policy.

- Hermes agent session lifecycle (start/stop/restart/health, storage, and runbook) is owned by PLA-249.
- MCP registry and safe tool policy are owned by PLA-250.
- PLA-244 should consume those downstream contracts when it needs session semantics or write-tool approval policy; it should not infer them from this foundation document.

## 도메인 소유 경계

| 영역 | 소유/변경 권한 | 계약 |
| --- | --- | --- |
| `plady.io` root zone | Cloudflare에서 구매·관리되는 root domain. AWS Route 53 소유가 아님. | root zone 변경은 Cloudflare owner가 승인/적용한다. |
| `agent.plady.io` delegated zone | `plady-agent-platform` / 새 AWS platform 계정의 platform boundary. | platform infra 작업(PLA-247)이 이 subdomain 아래 public endpoints를 수용한다. |
| Route 53 | 현재 작업 세션에서는 권한 차단으로 사용 불가. | PLA-246에서는 Route 53 hosted zone/resource를 만들지 않는다. PLA-247에서 사용 가능 여부와 대체 DNS 절차를 확정한다. |

### Delegation 원칙

1. `plady.io`는 Cloudflare root가 계속 소유한다.
2. `agent.plady.io` 아래 record는 platform ownership boundary로 취급한다.
3. Cloudflare root zone에는 delegation 또는 target record에 필요한 최소 record만 둔다.
4. platform 작업자는 root zone을 직접 소유한다고 가정하지 않는다.
5. Route 53 권한 차단 상태에서는 Terraform/DNS 변경을 시도하지 않고, 필요한 record contract만 문서화한다.

## Public endpoint 계약

| Endpoint | 공개 범위 | 소유 후속 이슈 | 목적/계약 |
| --- | --- | --- | --- |
| `https://wiki.agent.plady.io` | Public HTTPS | PLA-247 + wiki UI deployment | llm-wiki/Hugo 기반 wiki UI의 canonical platform URL. |
| `https://mcp.agent.plady.io/mcp` | Public HTTPS + bearer token | PLA-247 + PLA-250 | llm-wiki MCP HTTP endpoint. 반드시 bearer token 보호 뒤에 노출한다. |
| `https://hermes.agent.plady.io` | Public HTTPS | PLA-247 + PLA-249 | Hermes Gateway public origin. Slack event/interactivity/OAuth callback 등 non-OpenAI path의 origin. |
| `https://hermes.agent.plady.io/v1` | Public HTTPS + Hermes API key | PLA-249 + PLA-244 | OpenAI-compatible Hermes base URL. PLA-244가 OpenAI-compatible client 설정에 소비하는 canonical base URL. |
| `https://n8n.agent.plady.io` | Reserved, not live by default | PLA-251 | n8n placeholder/reserved endpoint. PLA-251에서 disabled placeholder로 구현(ALB 503 + compose 주석 블록, 내부 타깃 `n8n:5678` 예약). 런북 [`n8n-placeholder.md`](n8n-placeholder.md). |
| OTEL collector | Internal-only | PLA-251 | public DNS/Internet endpoint를 만들지 않는다. 내부 OTLP `otel-collector:4317`(gRPC)/`4318`(HTTP), file/local-first export, raw prompt/completion·secret/token·PII 미저장. 런북 [`otel-collector.md`](otel-collector.md). |

### Endpoint 보안 기본값

- `mcp.agent.plady.io/mcp`는 bearer token 없이 접근할 수 없어야 한다.
- `hermes.agent.plady.io/v1` OpenAI-compatible API는 `/plady/agent-platform/<env>/hermes-api-server-key` 또는 PLA-249가 확정하는 동등한 runtime secret reference로 보호한다.
- `hermes.agent.plady.io`의 non-OpenAI paths는 PLA-249가 정의하는 API auth boundary 뒤에 둔다.
- `n8n.agent.plady.io`는 reserved name일 뿐이며, enable 전에는 public service로 홍보하지 않는다.
- OTEL은 internal-only이다. `otel.agent.plady.io` 같은 public hostname을 새로 만들지 않는다.

## Secret/SSM parameter 이름 계약

값은 기록하지 않습니다. 아래는 **이름 계약**만입니다.

| Parameter name | 값 유형 | 소비자 | 비고 |
| --- | --- | --- | --- |
| `/plady/agent-platform/<env>/hermes-api-server-key` | Hermes API server auth key | Hermes Gateway runtime, Slack/Hermes integration | PLA-249/PLA-244가 값 주입 방식을 정한다. |
| `/plady/agent-platform/<env>/llm-wiki-mcp-bearer-token` | llm-wiki MCP bearer token | MCP reverse proxy/client config | `mcp.agent.plady.io/mcp` 보호에 사용한다. |

### `<env>` 규칙

- `<env>`는 배포 환경 이름 자리표시자입니다. 예: `dev`, `staging`, `prod`.
- 문서/코드/Linear에는 parameter **이름**만 남기고 실제 parameter **값**은 남기지 않습니다.
- legacy `/100thieves/wiki/...` SSM path는 새 platform 계약이 아닙니다. 신규 platform 작업은 `/plady/agent-platform/<env>/...` 이름 계약을 사용합니다.

## 후속 이슈 핸드오프

- PLA-247: `agent.plady.io` DNS/ACM/ALB/platform Terraform 구현. Cloudflare root와 Route 53 권한 차단 사실을 고려해 구현 가능 경로를 확정한다.
- PLA-249: `https://hermes.agent.plady.io` runtime path, `https://hermes.agent.plady.io/v1` OpenAI-compatible API, API auth, agent session lifecycle 구현.
- PLA-250: `https://mcp.agent.plady.io/mcp` registry/safe tool policy와 bearer-token 보호 세부 계약 구현.
- PLA-251: internal OTEL collector(내부 OTLP `otel-collector:4317`/`4318`, file/local-first export, privacy sanitization — 런북 [`otel-collector.md`](otel-collector.md))와 reserved `n8n.agent.plady.io` disabled placeholder(런북 [`n8n-placeholder.md`](n8n-placeholder.md)) 구현.
- PLA-244: Slack integration은 [`docs/pla-244-handoff.md`](pla-244-handoff.md)를 우선 참고한다.
