# EC2 Terraform deployment

이 Terraform 모듈은 EC2 한 대, ECR repositories, GitHub Actions OIDC push role을 만듭니다.
GitHub 인증과 저장소 clone은 PAT 대신 GitHub Deploy Key를 SSM Parameter Store SecureString에 저장해서 자동화하고, EC2는 ECR prebuilt image를 pull합니다.

## 생성 리소스

- Dedicated VPC, public subnet, route table, internet gateway
- EC2 security group
  - Hugo UI: 기본 `1313/tcp`
  - MCP HTTP: 기본 `18765/tcp`, 기본 차단
  - SSH: 기본 차단
- Amazon Linux 2023 EC2 instance
- ECR repositories for prebuilt Docker images
- GitHub Actions OIDC role for ECR push
- SSM/ECR 접속용 IAM role/profile

## 사용법

실제 배포자가 처음부터 따라갈 단계별 절차는 [`../../../docs/ec2-deployment-setup.md`](../../../docs/ec2-deployment-setup.md)를 참고하세요.

```bash
cd infra/terraform/ec2
cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars를 열어 CIDR, key_name, instance_type 등을 조정
terraform init
terraform plan
terraform apply
```

Terraform apply가 끝나면 cloud-init이 app repo와 wiki data repo를 SSH deploy key로 clone하고, ECR prebuilt image를 `docker compose pull && up`으로 실행합니다.
Free-tier 제한 계정은 `instance_type = "t3.micro"`를 기본으로 씁니다. ECR image가 아직 없을 때만 경량 local build fallback을 수행합니다.

## EC2 접속 후 수동 배포

```bash
aws ssm start-session --region ap-northeast-2 --target <instance-id>
sudo -iu ec2-user
cat ~/LLM_WIKI_DEPLOY.md

gh auth login
git clone https://github.com/100Thieves-team/100Thieves-wiki-mcp.git /opt/100thieves-wiki-mcp
cd /opt/100thieves-wiki-mcp
docker compose up -d --build
docker compose ps
```

`gh` 설치에 실패했거나 다른 인증 방식을 쓰고 싶다면 SSH key로 clone하면 됩니다.

## GitHub Deploy Key 기반 자동 clone

PAT는 사용하지 않습니다. repo별 Deploy Key를 만들고 private key를 SSM SecureString에 저장합니다.

- App repo: [`100Thieves-team/100Thieves-wiki-mcp`](https://github.com/100Thieves-team/100Thieves-wiki-mcp), read-only deploy key
- Wiki data repo: [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2), write deploy key

자세한 단계는 [`../../../docs/ec2-deployment-setup.md`](../../../docs/ec2-deployment-setup.md)를 참고하세요.

GitHub Actions 변수에는 `github_actions_ecr_role_arn`, `ecr_llm_wiki_repository`, `ecr_wiki_ui_repository` output 값을 등록한 뒤 `Build Docker images` workflow를 실행합니다. 배포 후 출력되는 `wiki_ui_url`로 접속합니다. MCP HTTP endpoint는 `mcp_http_url`입니다.

## 주의

- Terraform은 Deploy Key 값을 직접 읽지 않습니다. SSM parameter 이름만 state에 저장하고, 실제 private key는 EC2 user-data가 SSM에서 읽습니다.
- wiki 산출물은 [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)에 쌓이도록 `wiki-workspace/` remote와 sync timer를 구성합니다.
- `allowed_mcp_cidr_blocks`는 기본값이 빈 배열이라 외부에서 MCP HTTP에 접근할 수 없습니다. 필요한 IP만 `/32` 등으로 열어주세요.
- llm-wiki 데이터는 EC2의 `/opt/100thieves-wiki-mcp/wiki-workspace`에 clone되는 별도 git repo이며, 기본 remote는 [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)입니다.

## 확인 명령

```bash
terraform output wiki_ui_url
terraform output mcp_http_url
terraform output ssm_start_session_command
```

SSM 접속 후 상태 확인:

```bash
sudo systemctl status docker
cd /opt/100thieves-wiki-mcp && sudo docker compose --env-file .env.ec2 -f compose.ec2.yaml ps
sudo tail -f /var/log/llm-wiki-bootstrap.log
sudo systemctl status llm-wiki-data-sync.timer
```
