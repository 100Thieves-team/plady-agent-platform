# agent.plady.io platform Terraform (PLA-247)

이 모듈은 `agent.plady.io` 플랫폼 ingress를 구성합니다: 위임 Route 53 zone, ACM 인증서, public ALB, 서비스 alias 레코드, Caddy origin EC2, ECR repositories, GitHub Actions OIDC role, 그리고 SSM 파라미터 이름 계약입니다. 엔드포인트/시크릿 계약의 SSOT는 [`../../../docs/platform-contract.md`](../../../docs/platform-contract.md)입니다.

> Legacy `../ec2/` 모듈(plady.kro.kr wiki/Caddy 자동 HTTPS)은 그대로 두고, 이 모듈이 새 플랫폼 ingress를 담당합니다.

## 생성 리소스

- 전용 VPC, 2개 AZ public subnet, IGW, route table (ALB는 2개 이상 subnet 필요)
- Public Application Load Balancer
  - HTTP :80 → HTTPS 301 redirect
  - HTTPS :443 (ACM cert, TLS1.3) → Caddy origin target group
  - host routing: `wiki`/`mcp`/`hermes`는 Caddy origin으로, reserved `n8n`은 503
- ACM 인증서: `agent.plady.io` + `*.agent.plady.io` (DNS 검증)
- Route 53 위임 zone + ACM 검증 레코드 + `wiki`/`mcp`/`hermes`/`n8n` alias (`manage_dns = true`일 때)
- Caddy origin EC2 (ALB security group에서만 ingress 허용)
- ECR repositories + GitHub Actions OIDC ECR push role
- 플랫폼 SSM 파라미터(이름 계약)에 대한 EC2 read IAM 권한

## ⚠️ Route 53 SCP blocker (현재 상태)

플랫폼 AWS 계정에서 **Route 53가 SCP로 차단**되어 있어 hosted zone/record를 만들 수 없습니다. `plady.io` root는 **Cloudflare에서 구매·관리**됩니다. 두 가지 경로가 있습니다.

### 경로 A — Route 53 위임 (SCP 해제 후, `manage_dns = true`)

1. `terraform apply` → `agent.plady.io` Route 53 zone, ACM 검증 레코드, ALB alias 레코드 생성.
2. `terraform output agent_zone_name_servers` 의 NS 값을 PLA-248에 전달.
3. PLA-248이 Cloudflare `plady.io` root에 `agent` NS 위임 레코드를 만든다.
4. 위임 전파 후 ACM 검증이 자동 완료되고 ALB HTTPS가 활성화된다.

### 경로 B — Cloudflare 직접 (현재 권장, `manage_dns = false`)

Route 53 없이 Cloudflare `agent.plady.io`에 레코드를 직접 만든다.

1. `terraform.tfvars`에 `manage_dns = false` 설정 후 `terraform apply`. Route 53 리소스는 전부 skip되고 ALB/ACM/compute만 생성된다.
2. `terraform output acm_validation_records` → 각 도메인의 검증 CNAME을 Cloudflare `agent.plady.io`에 추가 (proxy OFF / DNS only).
3. ACM 인증서가 `Issued`가 될 때까지 대기 (`aws acm describe-certificate --certificate-arn <arn>`).
4. `terraform output cloudflare_service_records` → `wiki`/`mcp`/`hermes`/`n8n`.agent.plady.io CNAME을 ALB DNS 이름으로 Cloudflare에 추가 (proxy OFF 권장; Cloudflare proxy를 켜면 origin TLS/host 동작을 별도 검증해야 함).
5. `https://wiki.agent.plady.io` 접속 확인.

> `manage_dns = false`일 때 `aws_acm_certificate_validation` 대기 리소스는 생성되지 않습니다. ALB HTTPS listener는 cert ARN을 참조하므로, 인증서가 `Issued`가 되기 전에는 listener가 정상 동작하지 않습니다. 2~3단계 순서를 지키세요.

## 사용법

```bash
cd infra/terraform/platform
cp terraform.tfvars.example terraform.tfvars
# manage_dns 등 조정
terraform init
terraform plan
terraform apply
```

## 주의

- Terraform state에 실제 secret 값을 넣지 않습니다. SSM은 **이름 계약**만 다룹니다 (`/plady/agent-platform/<env>/...`).
- EC2 origin은 ALB security group에서만 ingress를 받습니다. 직접 public 노출이 없습니다.
- `mcp.agent.plady.io/mcp` bearer token 보호와 Hermes runtime/auth는 각각 PLA-250 / PLA-249가 origin(Caddy) 뒤에서 구현합니다. 이 모듈은 ingress/target 배선만 담당합니다.
- reserved `n8n.agent.plady.io`는 ALB에서 503을 반환합니다. PLA-251이 활성화합니다.

## 확인 명령

```bash
terraform output agent_zone_name_servers   # 경로 A: PLA-248 위임용 NS
terraform output acm_validation_records    # 경로 B: Cloudflare 검증 CNAME
terraform output cloudflare_service_records # 경로 B: Cloudflare 서비스 CNAME
terraform output alb_dns_name
terraform output hermes_public_origin_url  # PLA-244 handoff
terraform output hermes_openai_base_url    # PLA-244 handoff
```
