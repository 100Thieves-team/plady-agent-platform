# n8n Reserved Placeholder (PLA-251)

이 문서는 `n8n.agent.plady.io`의 **예약/비활성 placeholder 계약**의 SSOT runbook입니다. endpoint **이름 계약**은 [`platform-contract.md`](platform-contract.md)가 SSOT입니다.

## 현재 상태: RESERVED, DISABLED (실제 runtime 없음)

PLA-251은 n8n의 **자리만 예약**하고 **실제 runtime은 만들지 않습니다.** 현재 상태:

- **public**: `n8n.agent.plady.io`는 예약된 hostname입니다. 공개 ALB가 이 host에 대해 **503**을 반환합니다 — `infra/terraform/platform/alb.tf`의 `aws_lb_listener_rule.reserved_unavailable` (`var.reserved_subdomains`). 변경하지 않습니다.
- **compose**: `compose.yaml` / `compose.ec2.yaml`에 n8n 서비스가 **주석 처리된 placeholder 블록**으로만 존재합니다. 주석이라 절대 기동되지 않습니다(= "실제 runtime 금지"를 코드로 보장). `docker compose config`에 서비스로 나타나지 않습니다.
- **내부 타깃 컨벤션**: 활성화 시 내부 타깃은 `n8n:5678` (compose 네트워크)로 예약합니다. 다른 서비스들처럼 host publish 없이 `expose`만 두고, 공개는 PLA-247 ingress(Caddy/ALB) 뒤에서만 합니다.

> PLA-251 동안에는 n8n을 공개 runtime으로 홍보하거나 기동하지 않습니다. teammate 코드가 도착하기 전까지 disabled placeholder입니다.

## Enable 체크리스트 (미래 teammate 소관)

실제 n8n을 켜는 작업은 별도 이슈/teammate가 담당합니다. 켤 때 필요한 단계:

1. `compose.yaml` / `compose.ec2.yaml`의 주석 `n8n` 블록을 해제하고 이미지 태그(`N8N_IMAGE`)를 핀합니다.
2. `profiles: [n8n]` 유지 — 기본 `docker compose up`에 영향 없게.
3. secret(예: `N8N_ENCRYPTION_KEY`, DB 자격)은 SSM에서 주입합니다. 이름 계약(예: `/plady/agent-platform/<env>/n8n-encryption-key`)을 [`platform-contract.md`](platform-contract.md)에 추가하고, **값은 어디에도 커밋하지 않습니다.**
4. 내부 타깃 `n8n:5678`을 `expose`로 유지하고 host publish(`ports`)는 두지 않습니다.
5. PLA-247 ingress 라우팅: `infra/terraform/platform/`에서 `n8n`을 `reserved_subdomains`에서 제거하고 Caddy/ALB가 `n8n.agent.plady.io` → `n8n:5678`로 reverse proxy 하도록 host rule을 추가합니다(503 규칙 대체).
6. 인증/접근 경계를 정의합니다(n8n UI/webhook은 인증 없이 공개 금지).

## 핸드오프

- 이 이슈(PLA-251)는 **예약 계약과 disabled placeholder**만 제공합니다. workflow/runtime/credential 구현은 범위 밖입니다.
- public 503 동작은 PLA-247이 이미 구현했습니다. 본 이슈는 그것을 변경하지 않고 참조만 합니다.
