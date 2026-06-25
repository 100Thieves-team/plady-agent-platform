# EC2 배포 셋업 절차

> **PLA-246 note:** This is legacy EC2/Caddy wiki deployment guidance. It is kept for historical operations only. The new `agent.plady.io` platform contract is [`docs/platform-contract.md`](platform-contract.md); DNS/ACM/ALB/Terraform implementation belongs to PLA-247. Legacy `plady.kro.kr` and `/100thieves/wiki/...` values below are not the new platform contract.

이 문서는 `plady-agent-platform`를 AWS EC2에 배포하기 위해 작업자가 순서대로 수행할 절차입니다.

**선택한 안전한 방식:** GitHub PAT를 쓰지 않고, GitHub **Deploy Key + AWS SSM Parameter Store SecureString**을 사용합니다. 컨테이너 이미지는 GitHub Actions가 **ECR**에 미리 빌드/푸시하고, EC2는 `docker compose pull && up`만 수행합니다.

- App repo deploy key: [`100Thieves-team/plady-agent-platform`](https://github.com/100Thieves-team/plady-agent-platform) clone용, **read-only**
- Wiki data repo deploy key: [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2) wiki 산출물 저장용, **write 허용**
- private key 값은 Terraform state에 넣지 않고 SSM SecureString에만 저장합니다.
- EC2는 instance role로 SSM에서 private key를 읽고, repo별 SSH host alias를 사용합니다.
- EC2는 ECR read 권한으로 prebuilt image를 pull합니다.

### Existing legacy instance path

New examples use `/opt/plady-agent-platform` after the repo rename. If you are operating an already-running legacy EC2 instance that was cloned at `/opt/100thieves-wiki-mcp`, do not assume the path changed in place. Either migrate the checkout deliberately or pass the old path explicitly when using helper scripts, for example:

```bash
APP_DIR=/opt/100thieves-wiki-mcp scripts/refresh-ec2-runtime-env.sh
# or
scripts/refresh-ec2-runtime-env.sh --app-dir /opt/100thieves-wiki-mcp
```

## 0. 준비물

로컬 머신에 아래가 준비되어 있어야 합니다.

- AWS CLI 인증
- Terraform
- 이 저장소 clone본
- GitHub repository admin 권한 또는 Deploy Key를 등록할 수 있는 권한
- `plady.kro.kr` DNS A record를 설정할 수 있는 권한

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

1. [`100Thieves-team/plady-agent-platform`](https://github.com/100Thieves-team/plady-agent-platform) → Settings → Deploy keys
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

MCP_BEARER_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
aws ssm put-parameter \
  --region ap-northeast-2 \
  --name /100thieves/wiki/mcp-bearer-token \
  --type SecureString \
  --value "$MCP_BEARER_TOKEN" \
  --overwrite
unset MCP_BEARER_TOKEN
```

기본 AWS managed KMS key를 쓰면 추가 설정이 필요 없습니다. customer-managed KMS key를 쓴 경우에는 Terraform 변수에 해당 KMS key ARN도 설정합니다.
MCP bearer token 값은 채팅/문서에 남기지 말고, 필요할 때 SSM에서 조회하세요.
이 token은 서버 시작 때마다 새로 만들지 않습니다. SSM의 `/100thieves/wiki/mcp-bearer-token` 값을 다시 `put-parameter --overwrite`로 덮어쓸 때만 rotation됩니다.

SSM의 고정 token 값을 EC2 `.env.ec2`에 다시 반영해야 할 때는 repo root에서 아래 helper를 실행합니다. 이 명령은 token을 새로 만들지 않고 SSM SecureString 값을 다시 읽어 `mcp-proxy`만 재기동합니다.

```bash
scripts/refresh-ec2-runtime-env.sh
```

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
instance_type = "t3.micro"
root_volume_size = 30

domain_name = "plady.kro.kr"
acme_email = "admin@plady.kro.kr"

# t3.micro가 너무 느리고 계정에서 허용된다면 t3.small로 올리세요.

# Caddy가 HTTP/HTTPS를 받습니다. HTTP는 ACME HTTP-01과 HTTPS redirect에 필요합니다.
allowed_http_cidr_blocks  = ["0.0.0.0/0"]
allowed_https_cidr_blocks = ["0.0.0.0/0"]

# direct container ports는 HTTPS reverse proxy 뒤로 숨깁니다.
allowed_ui_cidr_blocks  = []
allowed_mcp_cidr_blocks = []

app_dir = "/opt/plady-agent-platform"

app_repository_url                  = "git@github.com-llm-wiki-app:100Thieves-team/plady-agent-platform.git"
app_repository_ref                  = "main"
app_repo_ssh_key_ssm_parameter_name = "/100thieves/wiki/app-repo-deploy-key"

wiki_data_repository_url                  = "git@github.com-llm-wiki-data:100Thieves-team/team-wiki-v2.git"
wiki_data_repo_ssh_key_ssm_parameter_name = "/100thieves/wiki/data-repo-deploy-key"

mcp_bearer_token_ssm_parameter_name = "/100thieves/wiki/mcp-bearer-token"

# customer-managed KMS key를 쓴 경우에만 필요합니다.
# app_repo_ssh_key_kms_key_arn = "arn:aws:kms:ap-northeast-2:123456789012:key/..."
# wiki_data_repo_ssh_key_kms_key_arn = "arn:aws:kms:ap-northeast-2:123456789012:key/..."
# mcp_bearer_token_kms_key_arn = "arn:aws:kms:ap-northeast-2:123456789012:key/..."

# 계정에 GitHub Actions OIDC provider가 이미 있으면 아래 ARN을 넣으세요.
# github_actions_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
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
terraform output dns_a_record
terraform output ssm_start_session_command
terraform output github_actions_ecr_role_arn
terraform output ecr_llm_wiki_repository
terraform output ecr_wiki_ui_repository
```

## 5. DNS A record 설정

Terraform이 Elastic IP를 만들고 `dns_a_record` output에 필요한 값을 출력합니다. DNS 관리 화면에서 아래와 같이 설정하세요.

```bash
terraform output -raw dns_a_record
# 예: plady.kro.kr A 203.0.113.10
```

DNS 설정 후 로컬에서 확인합니다.

```bash
dig +short plady.kro.kr A
```

출력 IP가 Terraform의 `public_ip`와 같아야 Caddy가 ZeroSSL 인증서를 발급받을 수 있습니다. DNS 전파 전에도 EC2는 떠 있지만 HTTPS 검증은 실패할 수 있고, Caddy가 자동으로 재시도합니다.

## 6. GitHub Actions ECR push 설정

Terraform output을 GitHub Actions repository variables로 등록합니다. role ARN은 secret이 아니므로 variable로 두면 됩니다.
`AWS_ROLE_TO_ASSUME`가 설정되기 전에는 workflow가 의도적으로 skip됩니다.

```bash
# repo root에서 실행
scripts/configure-github-actions-ecr.sh
```

스크립트는 아래 repository variables를 설정합니다.

- `AWS_ROLE_TO_ASSUME`
- `AWS_REGION`
- `ECR_LLM_WIKI_REPOSITORY`
- `ECR_WIKI_UI_REPOSITORY`

변수 설정과 동시에 GitHub Actions `Build Docker images` workflow를 실행하려면:

```bash
scripts/configure-github-actions-ecr.sh --run-workflow
```

이미 EC2가 먼저 떠서 local build fallback 상태라면, workflow 성공 후 EC2에서 아래를 한 번 실행하면 prebuilt image로 전환됩니다.

```bash
cd /opt/plady-agent-platform
sudo docker compose --env-file .env.ec2 -f compose.ec2.yaml pull
sudo docker compose --env-file .env.ec2 -f compose.ec2.yaml up -d
```

## 7. EC2 부팅/자동 배포 확인

Deploy Key 설정이 완료되어 있으면 cloud-init이 아래 작업을 수행합니다.

1. Docker/Git/curl/SSH client 설치
2. Docker Compose 설치
3. SSM Parameter Store에서 app repo deploy private key 읽기
4. [`100Thieves-team/plady-agent-platform`](https://github.com/100Thieves-team/plady-agent-platform) clone
5. SSM Parameter Store에서 wiki data repo deploy private key 읽기
6. [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)를 `wiki-workspace/`로 clone
7. SSM SecureString에서 MCP bearer token을 읽어 `.env.ec2`에 기록
8. ECR에 로그인하고 `compose.ec2.yaml`로 prebuilt image pull
9. Caddy를 80/443에 띄우고 `plady.kro.kr`에 ZeroSSL HTTPS를 자동 적용
10. `docker compose --env-file .env.ec2 -f compose.ec2.yaml up -d`
11. `llm-wiki-data-sync.timer`를 켜서 `wiki-workspace` commit을 `team-wiki-v2`로 주기적 push

ECR 이미지가 아직 없으면 경량 로컬 build로 fallback합니다. `llm-wiki` Dockerfile은 Rust 컴파일 대신 upstream release binary를 내려받기 때문에 `t3.micro`에서도 첫 실행 가능성이 높습니다.

SSM으로 접속해서 로그를 확인합니다.

```bash
aws ssm start-session --region ap-northeast-2 --target <instance-id>
sudo tail -f /var/log/llm-wiki-bootstrap.log
```

상태 확인:

```bash
cd /opt/plady-agent-platform
sudo docker compose --env-file .env.ec2 -f compose.ec2.yaml ps
sudo systemctl status llm-wiki-data-sync.timer
```

## 8. 수동 fallback

Deploy Key 자동화가 실패했거나 임시로 직접 확인해야 한다면 EC2에 접속해서 수동 clone도 가능합니다.

```bash
aws ssm start-session --region ap-northeast-2 --target <instance-id>
sudo -iu ec2-user
cat ~/LLM_WIKI_DEPLOY.md

gh auth login
git clone https://github.com/100Thieves-team/plady-agent-platform.git /opt/plady-agent-platform
cd /opt/plady-agent-platform
rm -rf wiki-workspace
git clone https://github.com/100Thieves-team/team-wiki-v2.git wiki-workspace
docker compose up -d --build
docker compose ps
```

## 9. Codex MCP client 설정

Codex에서 팀 wiki MCP를 쓰려면 로컬 Codex 설정에 HTTP MCP endpoint를 추가합니다. Bearer token 값은 Codex config에 저장하지 않고 환경변수로 주입합니다.

```bash
scripts/configure-codex-mcp.sh

# GUI Codex 앱이면 macOS login session에 token env를 설정한 뒤 앱을 재시작합니다.
scripts/set-codex-mcp-token-env.sh

# 터미널에서 Codex CLI를 바로 실행할 때만 현재 shell export가 필요합니다.
eval "$(scripts/set-codex-mcp-token-env.sh --mode shell)"

codex mcp list | grep team-wiki
```

현재 운영 endpoint는 `https://plady.kro.kr/mcp`입니다. Codex MCP 설정을 다시 적용하려면 아래처럼 URL을 지정해서 실행하세요.

```bash
scripts/configure-codex-mcp.sh --url https://plady.kro.kr/mcp
```

## 10. 배포 확인

로컬에서 Terraform output URL로 확인합니다.

```bash
curl -I $(terraform output -raw wiki_ui_url)
# https://plady.kro.kr
```

MCP endpoint는 HTTPS와 bearer token이 모두 있어야 proxy를 통과합니다. token 없이 호출하면 `401 Unauthorized`가 나와야 정상입니다.

```bash
curl -i -N --max-time 3 \
  -H 'Accept: text/event-stream' \
  "$(terraform output -raw mcp_http_url)"
```

발급된 token으로 호출하면 proxy를 통과하고, SSE session 없이 직접 GET했을 때는 `Bad Request: Session ID is required`가 나올 수 있습니다.

```bash
MCP_BEARER_TOKEN="$(aws ssm get-parameter \
  --region ap-northeast-2 \
  --name /100thieves/wiki/mcp-bearer-token \
  --with-decryption \
  --query Parameter.Value \
  --output text)"

curl -i -N --max-time 3 \
  -H "Authorization: Bearer $MCP_BEARER_TOKEN" \
  -H 'Accept: text/event-stream' \
  "$(terraform output -raw mcp_http_url)"
unset MCP_BEARER_TOKEN
```

EC2 내부 상태:

```bash
cd /opt/plady-agent-platform
sudo docker compose --env-file .env.ec2 -f compose.ec2.yaml ps
sudo docker compose --env-file .env.ec2 -f compose.ec2.yaml logs --tail=100 llm-wiki
sudo docker compose --env-file .env.ec2 -f compose.ec2.yaml logs --tail=100 wiki-ui
sudo systemctl status llm-wiki-data-sync.timer
sudo journalctl -u llm-wiki-data-sync.service -n 100 --no-pager
```

`team-wiki-v2`에 push되는지 확인:

```bash
cd /opt/plady-agent-platform/wiki-workspace
sudo git remote -v
sudo git log --oneline -5
sudo /usr/local/bin/llm-wiki-data-sync
```

## 11. 운영 작업

### 새 코드 반영

```bash
aws ssm start-session --region ap-northeast-2 --target <instance-id>
sudo -iu ec2-user
cd /opt/plady-agent-platform
git pull --ff-only origin main
docker compose --env-file .env.ec2 -f compose.ec2.yaml pull
docker compose --env-file .env.ec2 -f compose.ec2.yaml up -d
docker compose --env-file .env.ec2 -f compose.ec2.yaml ps
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

## 12. 자주 보는 문제

- **EC2가 app repo clone 실패**: app repo deploy key가 [`100Thieves-team/plady-agent-platform`](https://github.com/100Thieves-team/plady-agent-platform)에 등록되어 있는지, `app_repo_ssh_key_ssm_parameter_name`이 맞는지 확인합니다.
- **EC2가 wiki data repo clone/push 실패**: data repo deploy key가 [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)에 등록되어 있고 **Allow write access**가 켜져 있는지 확인합니다.
- **`AccessDeniedException` on SSM**: SSM parameter 이름이 Terraform 변수와 일치하는지 확인하고, customer-managed KMS를 썼다면 KMS key ARN 변수도 설정합니다.
- **`EntityAlreadyExists` on GitHub OIDC provider**: AWS 계정에 `token.actions.githubusercontent.com` OIDC provider가 이미 있으면 `github_actions_oidc_provider_arn`에 기존 ARN을 넣고 다시 `terraform apply`합니다.
- **HTTPS 인증서 발급 실패**: `dig +short plady.kro.kr A`가 `terraform output -raw public_ip`와 같은지 확인합니다. 80/tcp가 열려 있어야 ACME HTTP-01 검증이 통과합니다. `kro.kr` 공유 도메인은 Let's Encrypt registered-domain rate limit에 걸릴 수 있어 Caddy의 기본 ACME CA를 ZeroSSL로 지정했습니다.
- **직접 `:1313`, `:18765` 접근 실패**: HTTPS 구성에서는 direct container ports를 public으로 닫고 Caddy만 `80/443`으로 공개합니다. UI는 `https://plady.kro.kr`, MCP는 `https://plady.kro.kr/mcp`를 사용하세요.
- **ECR pull 실패**: GitHub Actions workflow가 성공했는지, EC2 role에 ECR pull 권한이 있는지, `.env.ec2`의 image URI가 맞는지 확인합니다.
- **UI 접속 불가**: `allowed_ui_cidr_blocks`, EC2 public IP, `docker compose --env-file .env.ec2 -f compose.ec2.yaml ps`를 확인합니다.
- **Codex에서 `team-wiki`가 `Tools: (none)`으로 보임**: 먼저 서버 자체가 tool을 내보내는지 확인합니다. `scripts/check-mcp-tools.sh`를 실행했을 때 `wiki_ingest`, `wiki_search` 등이 보이면 서버는 정상입니다. 그 다음 `~/.codex/config.toml`의 `[mcp_servers.team-wiki]`에서 `bearer_token_env_var = "LLM_WIKI_MCP_BEARER_TOKEN"`인지 확인하세요. 여기에 실제 token 값을 넣으면 Codex는 그 문자열을 환경변수 이름으로 오해합니다.
- **MCP가 `401 Unauthorized` 반환**: `Authorization: Bearer <token>` 헤더가 없거나 SSM의 `/100thieves/wiki/mcp-bearer-token` 값과 다릅니다.
- **MCP 접속 불가**: `allowed_mcp_cidr_blocks`는 기본 차단입니다. 필요한 client IP만 `/32`로 열거나, public 노출이 필요할 때만 `0.0.0.0/0`로 열어주세요. HTTP bearer token은 TLS 없이는 탈취될 수 있으므로 운영에서는 HTTPS를 붙이는 것을 권장합니다.
- **기존 EC2에 user_data 변경이 반영되지 않음**: user-data는 기본적으로 최초 부팅 때 실행됩니다. 새 인스턴스로 재생성하거나 EC2 안에서 수동 절차를 실행하세요.
