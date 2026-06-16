# EC2 배포 셋업 절차

이 문서는 `100Thieves-wiki-mcp`를 AWS EC2에 배포하기 위해 작업자가 순서대로 수행할 절차입니다.

**선택한 안전한 방식:** GitHub PAT를 쓰지 않고, GitHub **Deploy Key + AWS SSM Parameter Store SecureString**을 사용합니다.

- App repo deploy key: [`100Thieves-team/100Thieves-wiki-mcp`](https://github.com/100Thieves-team/100Thieves-wiki-mcp) clone용, **read-only**
- Wiki data repo deploy key: [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2) wiki 산출물 저장용, **write 허용**
- private key 값은 Terraform state에 넣지 않고 SSM SecureString에만 저장합니다.
- EC2는 instance role로 SSM에서 private key를 읽고, repo별 SSH host alias를 사용합니다.

## 0. 준비물

로컬 머신에 아래가 준비되어 있어야 합니다.

- AWS CLI 인증
- Terraform
- 이 저장소 clone본
- GitHub repository admin 권한 또는 Deploy Key를 등록할 수 있는 권한

확인:

```bash
aws sts get-caller-identity
terraform version
git remote -v
```

## 1. GitHub Deploy Key 생성

Deploy Key는 GitHub 정책상 같은 key를 여러 repo에 재사용할 수 없습니다. app repo용과 wiki data repo용을 **따로** 만듭니다.

```bash
mkdir -p .deploy-keys
ssh-keygen -t ed25519 -C "llm-wiki-app-repo" -f .deploy-keys/llm_wiki_app_repo -N ""
ssh-keygen -t ed25519 -C "llm-wiki-data-repo" -f .deploy-keys/llm_wiki_data_repo -N ""
```

`.deploy-keys/`는 `.gitignore`에 포함되어 있지만, private key를 Git에 올리지 않도록 커밋 전에 항상 `git status`를 확인하세요.

GitHub에 public key를 등록합니다.

1. [`100Thieves-team/100Thieves-wiki-mcp`](https://github.com/100Thieves-team/100Thieves-wiki-mcp) → Settings → Deploy keys
   - title: `llm-wiki-ec2-prod-app-readonly`
   - key: `.deploy-keys/llm_wiki_app_repo.pub`
   - **Allow write access: OFF**
2. [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2) → Settings → Deploy keys
   - title: `llm-wiki-ec2-prod-data-write`
   - key: `.deploy-keys/llm_wiki_data_repo.pub`
   - **Allow write access: ON**

`team-wiki-v2`는 llm-wiki 산출물이 쌓이는 SSOT 데이터 repo입니다. EC2의 sync timer가 이 repo로 push하려면 write deploy key가 필요합니다.

## 2. private key를 SSM SecureString에 저장

private key를 `terraform.tfvars`에 넣지 않습니다. SSM Parameter Store의 `SecureString`으로 저장합니다.

```bash
aws ssm put-parameter \
  --region ap-northeast-2 \
  --name /100thieves/wiki/app-repo-deploy-key \
  --type SecureString \
  --value "$(cat .deploy-keys/llm_wiki_app_repo)" \
  --overwrite

aws ssm put-parameter \
  --region ap-northeast-2 \
  --name /100thieves/wiki/data-repo-deploy-key \
  --type SecureString \
  --value "$(cat .deploy-keys/llm_wiki_data_repo)" \
  --overwrite
```

기본 AWS managed KMS key를 쓰면 추가 설정이 필요 없습니다. customer-managed KMS key를 쓴 경우에는 Terraform 변수에 해당 KMS key ARN도 설정합니다.

SSM 저장이 끝난 뒤 로컬 private key 파일은 필요 없으면 삭제해도 됩니다.

## 3. Terraform 변수 파일 작성

```bash
cd infra/terraform/ec2
cp terraform.tfvars.example terraform.tfvars
```

`terraform.tfvars` 권장 예시:

```hcl
aws_region    = "ap-northeast-2"
project_name  = "100thieves-wiki"
instance_type = "t3.large"

# UI는 필요하면 팀/VPN IP로 제한하세요.
allowed_ui_cidr_blocks = ["0.0.0.0/0"]

# MCP는 코딩 에이전트/사내망 IP만 열 것을 권장합니다.
allowed_mcp_cidr_blocks = ["203.0.113.10/32"]

app_dir = "/opt/100thieves-wiki-mcp"

app_repository_url                  = "git@github.com-llm-wiki-app:100Thieves-team/100Thieves-wiki-mcp.git"
app_repository_ref                  = "main"
app_repo_ssh_key_ssm_parameter_name = "/100thieves/wiki/app-repo-deploy-key"

wiki_data_repository_url                  = "git@github.com-llm-wiki-data:100Thieves-team/team-wiki-v2.git"
wiki_data_repo_ssh_key_ssm_parameter_name = "/100thieves/wiki/data-repo-deploy-key"

# customer-managed KMS key를 쓴 경우에만 필요합니다.
# app_repo_ssh_key_kms_key_arn = "arn:aws:kms:ap-northeast-2:123456789012:key/..."
# wiki_data_repo_ssh_key_kms_key_arn = "arn:aws:kms:ap-northeast-2:123456789012:key/..."
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

## 5. EC2 부팅/자동 배포 확인

Deploy Key 설정이 완료되어 있으면 cloud-init이 아래 작업을 수행합니다.

1. Docker/Git/curl/SSH client 설치
2. Docker Compose 설치
3. SSM Parameter Store에서 app repo deploy private key 읽기
4. [`100Thieves-team/100Thieves-wiki-mcp`](https://github.com/100Thieves-team/100Thieves-wiki-mcp) clone
5. SSM Parameter Store에서 wiki data repo deploy private key 읽기
6. [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)를 `wiki-workspace/`로 clone
7. `docker compose up -d --build`
8. `llm-wiki-data-sync.timer`를 켜서 `wiki-workspace` commit을 `team-wiki-v2`로 주기적 push

SSM으로 접속해서 로그를 확인합니다.

```bash
aws ssm start-session --region ap-northeast-2 --target <instance-id>
sudo tail -f /var/log/llm-wiki-bootstrap.log
```

상태 확인:

```bash
cd /opt/100thieves-wiki-mcp
sudo docker compose ps
sudo systemctl status llm-wiki-data-sync.timer
```

## 6. 수동 fallback

Deploy Key 자동화가 실패했거나 임시로 직접 확인해야 한다면 EC2에 접속해서 수동 clone도 가능합니다.

```bash
aws ssm start-session --region ap-northeast-2 --target <instance-id>
sudo -iu ec2-user
cat ~/LLM_WIKI_DEPLOY.md

gh auth login
git clone https://github.com/100Thieves-team/100Thieves-wiki-mcp.git /opt/100thieves-wiki-mcp
cd /opt/100thieves-wiki-mcp
rm -rf wiki-workspace
git clone https://github.com/100Thieves-team/team-wiki-v2.git wiki-workspace
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
sudo systemctl status llm-wiki-data-sync.timer
sudo journalctl -u llm-wiki-data-sync.service -n 100 --no-pager
```

`team-wiki-v2`에 push되는지 확인:

```bash
cd /opt/100thieves-wiki-mcp/wiki-workspace
sudo git remote -v
sudo git log --oneline -5
sudo /usr/local/bin/llm-wiki-data-sync
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

### wiki 데이터 저장소

`wiki-workspace/`는 llm-wiki가 만드는 별도 git-backed wiki repo입니다. 이 저장소의 remote는 [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)입니다. 저장소 분리 구조는 [`wiki-data-repo.md`](wiki-data-repo.md)를 참고하세요.

동기화 timer 확인:

```bash
sudo systemctl list-timers llm-wiki-data-sync.timer
sudo systemctl status llm-wiki-data-sync.timer
```

수동 push:

```bash
sudo /usr/local/bin/llm-wiki-data-sync
```

### 종료/삭제

```bash
cd infra/terraform/ec2
terraform destroy
```

EC2를 destroy하기 전에 `team-wiki-v2`에 최신 commit이 push되어 있는지 확인하세요.

## 9. 자주 보는 문제

- **EC2가 app repo clone 실패**: app repo deploy key가 [`100Thieves-team/100Thieves-wiki-mcp`](https://github.com/100Thieves-team/100Thieves-wiki-mcp)에 등록되어 있는지, `app_repo_ssh_key_ssm_parameter_name`이 맞는지 확인합니다.
- **EC2가 wiki data repo clone/push 실패**: data repo deploy key가 [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)에 등록되어 있고 **Allow write access**가 켜져 있는지 확인합니다.
- **`AccessDeniedException` on SSM**: SSM parameter 이름이 Terraform 변수와 일치하는지 확인하고, customer-managed KMS를 썼다면 KMS key ARN 변수도 설정합니다.
- **UI 접속 불가**: `allowed_ui_cidr_blocks`, EC2 public IP, `docker compose ps`를 확인합니다.
- **MCP 접속 불가**: `allowed_mcp_cidr_blocks`는 기본 차단입니다. 필요한 client IP만 `/32`로 열어주세요.
- **기존 EC2에 user_data 변경이 반영되지 않음**: user-data는 기본적으로 최초 부팅 때 실행됩니다. 새 인스턴스로 재생성하거나 EC2 안에서 수동 절차를 실행하세요.
