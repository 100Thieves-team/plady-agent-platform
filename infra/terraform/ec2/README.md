# EC2 Terraform deployment

이 Terraform 모듈은 EC2 한 대를 만들고 Docker/Compose/Git을 설치합니다.
GitHub 인증과 저장소 clone은 기본적으로 EC2에 접속해서 직접 진행하며, 원하면 SSM Parameter Store에 저장한 GitHub token으로 자동 clone도 할 수 있습니다.

## 생성 리소스

- Dedicated VPC, public subnet, route table, internet gateway
- EC2 security group
  - Hugo UI: 기본 `1313/tcp`
  - MCP HTTP: 기본 `18765/tcp`, 기본 차단
  - SSH: 기본 차단
- Amazon Linux 2023 EC2 instance
- SSM 접속용 IAM role/profile

## 사용법

```bash
cd infra/terraform/ec2
cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars를 열어 CIDR, key_name 등을 조정
terraform init
terraform plan
terraform apply
```

Terraform apply가 끝나면 EC2에 접속해서 GitHub 로그인/clone 후 Compose를 실행합니다.
`github_token_ssm_parameter_name`을 설정했다면 cloud-init이 자동 clone과 `docker compose up -d --build`까지 시도합니다.

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

`gh` 설치에 실패했거나 다른 인증 방식을 쓰고 싶다면 HTTPS token 또는 SSH key로 clone하면 됩니다.

## GitHub token 기반 자동 clone

토큰 자체를 `terraform.tfvars`에 넣지 말고, 먼저 SSM Parameter Store의 `SecureString`으로 저장합니다.

```bash
aws ssm put-parameter \
  --region ap-northeast-2 \
  --name /100thieves/wiki/github-token \
  --type SecureString \
  --value '<github-token>' \
  --overwrite
```

그 다음 `terraform.tfvars`에 parameter 이름만 넣습니다.

```hcl
repository_url                  = "https://github.com/100Thieves-team/100Thieves-wiki-mcp.git"
repository_ref                  = "main"
github_token_ssm_parameter_name = "/100thieves/wiki/github-token"
```

토큰이 customer-managed KMS key로 암호화되어 있다면 EC2 role에 `kms:Decrypt` 권한이 필요하므로 아래 값도 추가합니다.

```hcl
github_token_kms_key_arn = "arn:aws:kms:ap-northeast-2:123456789012:key/..."
```

배포 후 출력되는 `wiki_ui_url`로 접속합니다. MCP HTTP endpoint는 `mcp_http_url`입니다.

## 주의

- Terraform은 GitHub token 값을 직접 읽지 않습니다. `github_token_ssm_parameter_name`만 state에 저장하고, 실제 token은 EC2 user-data가 SSM에서 읽습니다.
- token 기반 자동 clone은 HTTPS repo URL 기준입니다. fine-grained token을 쓰면 대상 repo의 Contents read 권한이 필요합니다.
- `allowed_mcp_cidr_blocks`는 기본값이 빈 배열이라 외부에서 MCP HTTP에 접근할 수 없습니다. 필요한 IP만 `/32` 등으로 열어주세요.
- llm-wiki 데이터는 EC2의 `/opt/100thieves-wiki-mcp/wiki-workspace`에 생성되는 별도 git repo입니다. 인스턴스를 destroy하면 같이 사라지므로 운영 전 백업/remote push 정책을 정하세요.

## 확인 명령

```bash
terraform output wiki_ui_url
terraform output mcp_http_url
terraform output ssm_start_session_command
```

SSM 접속 후 상태 확인:

```bash
sudo systemctl status docker
cd /opt/100thieves-wiki-mcp && sudo docker compose ps
sudo tail -f /var/log/llm-wiki-bootstrap.log
```
