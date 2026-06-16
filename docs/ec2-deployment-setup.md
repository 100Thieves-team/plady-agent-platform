# EC2 배포 셋업 절차

이 문서는 `100Thieves-wiki-mcp`를 AWS EC2에 배포하기 위해 작업자가 순서대로 수행할 절차입니다.

배포 방식은 두 가지입니다.

1. **권장: GitHub token 기반 자동 clone**  
   Terraform은 token 값을 직접 저장하지 않고, EC2가 SSM Parameter Store에서 token을 읽어 private repo를 clone합니다.
2. **수동 clone**  
   EC2에 접속해서 `gh auth login` 또는 SSH/HTTPS 인증 후 직접 clone합니다.

## 0. 준비물

로컬 머신에 아래가 준비되어 있어야 합니다.

- AWS CLI 인증
- Terraform
- 이 저장소 clone본
- GitHub token 또는 EC2에서 사용할 GitHub 로그인 수단

확인:

```bash
aws sts get-caller-identity
terraform version
git remote -v
```

## 1. GitHub token 준비

자동 clone을 쓰려면 GitHub fine-grained token을 만듭니다. 개인 계정보다는 별도 봇/머신 계정을 권장합니다.

권장 계정 정책:

- 봇 계정 예시: `100thieves-wiki-bot`
- 봇 계정에는 이 저장소 접근 권한만 부여
- token 소유자는 개인 계정이 아니라 봇 계정으로 설정
- token 만료일과 rotation 담당자를 정해 운영 문서에 기록
- 퇴사/권한 변경에 영향을 받는 개인 token은 사용하지 않기

- 대상 repository: [`100Thieves-team/100Thieves-wiki-mcp`](https://github.com/100Thieves-team/100Thieves-wiki-mcp)
- 필요한 권한: **Contents: Read-only**
- 만료일: 팀 운영 정책에 맞게 설정

수동 clone만 사용할 경우 이 단계는 건너뛰어도 됩니다.

## 2. token을 SSM Parameter Store에 저장

`terraform.tfvars`에 token 값을 직접 넣지 않습니다. token은 SSM `SecureString`으로 저장하고, Terraform에는 parameter 이름만 넣습니다.

```bash
read -rsp "GitHub token: " GITHUB_TOKEN; echo
aws ssm put-parameter \
  --region ap-northeast-2 \
  --name /100thieves/wiki/github-token \
  --type SecureString \
  --value "$GITHUB_TOKEN" \
  --overwrite
unset GITHUB_TOKEN
```

기본 AWS managed KMS key를 쓰면 추가 설정이 필요 없습니다. customer-managed KMS key를 쓴 경우에는 나중에 `github_token_kms_key_arn`도 설정합니다.

## 3. Terraform 변수 파일 작성

```bash
cd infra/terraform/ec2
cp terraform.tfvars.example terraform.tfvars
```

`terraform.tfvars` 예시:

```hcl
aws_region   = "ap-northeast-2"
project_name = "100thieves-wiki"
instance_type = "t3.large"

# UI는 필요하면 팀/VPN IP로 제한하세요.
allowed_ui_cidr_blocks = ["0.0.0.0/0"]

# MCP는 코딩 에이전트/사내망 IP만 열 것을 권장합니다.
allowed_mcp_cidr_blocks = ["203.0.113.10/32"]

app_dir = "/opt/100thieves-wiki-mcp"

repository_url                  = "https://github.com/100Thieves-team/100Thieves-wiki-mcp.git"
repository_ref                  = "main"
github_token_ssm_parameter_name = "/100thieves/wiki/github-token"

# customer-managed KMS key를 쓴 경우에만 필요합니다.
# github_token_kms_key_arn = "arn:aws:kms:ap-northeast-2:123456789012:key/..."
```

현재 내 공인 IP를 `/32`로 확인하려면:

```bash
curl -s https://checkip.amazonaws.com
```

## 4. Terraform 실행

```bash
terraform init
terraform validate
terraform plan
terraform apply
```

`apply`가 끝나면 출력값을 확인합니다.

```bash
terraform output instance_id
terraform output wiki_ui_url
terraform output mcp_http_url
terraform output ssm_start_session_command
```

## 5. EC2 부팅/자동 clone 확인

자동 clone을 설정했다면 cloud-init이 아래 작업을 수행합니다.

1. Docker/Git/curl 설치
2. Docker Compose 설치
3. SSM Parameter Store에서 GitHub token 읽기
4. repo clone
5. `docker compose up -d --build`

SSM으로 접속해서 로그를 확인합니다.

```bash
aws ssm start-session --region ap-northeast-2 --target <instance-id>
sudo tail -f /var/log/llm-wiki-bootstrap.log
```

상태 확인:

```bash
cd /opt/100thieves-wiki-mcp
sudo docker compose ps
```

## 6. 수동 clone 방식으로 진행하는 경우

`github_token_ssm_parameter_name`을 설정하지 않았다면 EC2에 접속해서 직접 clone합니다.

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

## 7. 배포 확인

로컬에서 Terraform output URL로 확인합니다.

```bash
curl -I $(terraform output -raw wiki_ui_url)
```

MCP endpoint는 SSE 세션이 필요하므로 단순 GET에서는 `Bad Request: Session ID is required`가 나올 수 있습니다. 서버가 떠 있는지 최소 확인하려면:

```bash
curl -i -N --max-time 3 \
  -H 'Accept: text/event-stream' \
  "$(terraform output -raw mcp_http_url)"
```

EC2 내부 상태:

```bash
cd /opt/100thieves-wiki-mcp
sudo docker compose ps
sudo docker compose logs --tail=100 llm-wiki
sudo docker compose logs --tail=100 wiki-ui
```

## 8. 운영 작업

### 새 코드 반영

```bash
aws ssm start-session --region ap-northeast-2 --target <instance-id>
sudo -iu ec2-user
cd /opt/100thieves-wiki-mcp
git pull --ff-only origin main
docker compose up -d --build
docker compose ps
```

### wiki 데이터 백업

`wiki-workspace/`는 llm-wiki가 만드는 별도 git-backed wiki repo입니다. EC2를 destroy하면 같이 사라질 수 있으므로 운영 전 remote push 정책을 정하세요. 저장소 분리 구조는 [`wiki-data-repo.md`](wiki-data-repo.md)를 참고하세요.

예시:

```bash
cd /opt/100thieves-wiki-mcp/wiki-workspace
git status
git remote add origin <wiki-data-repo-url>
git push -u origin main
```

### 종료/삭제

```bash
cd infra/terraform/ec2
terraform destroy
```

## 9. 자주 보는 문제

- **EC2가 repo clone 실패**: GitHub token 권한이 `Contents: Read-only` 이상인지, SSM parameter 이름이 맞는지 확인합니다.
- **`AccessDeniedException` on SSM**: `github_token_ssm_parameter_name`이 Terraform에 들어갔는지 확인하고, customer-managed KMS를 썼다면 `github_token_kms_key_arn`도 설정합니다.
- **UI 접속 불가**: `allowed_ui_cidr_blocks`, EC2 public IP, `docker compose ps`를 확인합니다.
- **MCP 접속 불가**: `allowed_mcp_cidr_blocks`는 기본 차단입니다. 필요한 client IP만 `/32`로 열어주세요.
- **기존 EC2에 user_data 변경이 반영되지 않음**: user-data는 기본적으로 최초 부팅 때 실행됩니다. 새 인스턴스로 재생성하거나 EC2 안에서 수동 절차를 실행하세요.
