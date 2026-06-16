# EC2 Terraform deployment

이 Terraform 모듈은 EC2 한 대를 만들고 Docker/Compose/Git을 설치합니다.
GitHub 인증과 저장소 clone은 EC2에 접속해서 직접 진행합니다.

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

배포 후 출력되는 `wiki_ui_url`로 접속합니다. MCP HTTP endpoint는 `mcp_http_url`입니다.

## 주의

- Terraform은 더 이상 repo clone/token을 다루지 않습니다. private repo 인증은 EC2 안에서 직접 처리합니다.
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
