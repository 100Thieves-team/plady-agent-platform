# EC2 Terraform deployment

이 Terraform 모듈은 EC2 한 대에 Docker/Compose를 설치하고 이 저장소를 clone한 뒤 `docker compose up -d --build`로 `llm-wiki` MCP 서버와 Hugo UI를 실행합니다.

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
# terraform.tfvars를 열어 CIDR, key_name, repository_url 등을 조정
terraform init
terraform plan
terraform apply
```

배포 후 출력되는 `wiki_ui_url`로 접속합니다. MCP HTTP endpoint는 `mcp_http_url`입니다.

## 주의

- `repository_url`은 EC2 인스턴스에서 접근 가능해야 합니다. private repo라면 deploy key, GitHub token, 또는 별도 artifact 배포 방식을 준비해야 합니다.
- `allowed_mcp_cidr_blocks`는 기본값이 빈 배열이라 외부에서 MCP HTTP에 접근할 수 없습니다. 필요한 IP만 `/32` 등으로 열어주세요.
- llm-wiki 데이터는 EC2의 `app_dir/wiki-workspace`에 생성되는 별도 git repo입니다. 인스턴스를 destroy하면 같이 사라지므로 운영 전 백업/remote push 정책을 정하세요.

## 확인 명령

```bash
terraform output wiki_ui_url
terraform output mcp_http_url
terraform output ssm_start_session_command
```

SSM 접속 후 상태 확인:

```bash
sudo systemctl status docker
sudo systemctl status llm-wiki-compose
cd /opt/100thieves-wiki-mcp && sudo docker compose ps
sudo tail -f /var/log/llm-wiki-bootstrap.log
```
