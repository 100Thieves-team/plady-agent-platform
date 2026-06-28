# Wiki 데이터 저장소 구조

결론부터 말하면, MCP로 `wiki_ingest` 요청을 날렸을 때 쌓이는 회의록/ADR/멘토링 정리 데이터는 이 wrapper repo가 아니라 **별도 git repo인 [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)**에 저장되도록 구성합니다.

로컬/컨테이너 내부에서는 그 repo가 `wiki-workspace/` 경로로 mount됩니다. Hugo UI는 `wiki-workspace/wiki`를 사이트 root로, `wiki-workspace/raw`를 `/raw/` section으로 노출합니다.

## 저장소 역할

| 저장소/경로 | 역할 | Git 관리 |
| --- | --- | --- |
| [`100Thieves-team/plady-agent-platform`](https://github.com/100Thieves-team/plady-agent-platform) | Docker Compose, Terraform, upstream `llm-wiki`, Hugo UI scaffold | app wrapper repo |
| [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2) | 실제 wiki content, raw 문서, schema, llm-wiki ingest 결과 | wiki data SSOT repo |
| `wiki-workspace/` | `team-wiki-v2`가 clone되는 로컬 작업 디렉터리 | wrapper repo에서는 `.gitignore` 처리 |

현재 구조는 아래처럼 동작합니다.

```text
plady-agent-platform/
  compose.yaml
  docker/
  llm-wiki/
  llm-wiki-hugo-cms/
  wiki-workspace/        # team-wiki-v2 clone 위치
    .git/
    wiki.toml
    raw/
    wiki/
    schemas/
```

EC2에서는 기본적으로 아래 경로가 됩니다.

```text
/opt/plady-agent-platform/wiki-workspace/
```

## ingest 시 일어나는 일

`llm-wiki` MCP 서버는 Docker Compose에서 `/workspace`를 `./wiki-workspace`에 mount합니다.

```yaml
llm-wiki:
  volumes:
    - ./wiki-workspace:/workspace
```

따라서 `wiki_ingest` 또는 content write/commit 류 작업은 다음 저장소에 반영됩니다.

```bash
cd wiki-workspace
git status
git log --oneline
git remote -v
```

즉, app wrapper repo에 데이터 commit이 생기는 것이 아니라 `wiki-workspace` 내부 git history에 wiki 데이터 commit이 쌓입니다. EC2 배포에서는 `wiki-workspace`의 remote가 [`team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)로 설정됩니다.

## 안전한 GitHub 인증 방식

PAT는 범위가 넓고 회전/감사가 불편하므로 기본 방식으로 쓰지 않습니다. 대신 repo별 GitHub Deploy Key를 사용합니다.

- app repo deploy key: [`100Thieves-team/plady-agent-platform`](https://github.com/100Thieves-team/plady-agent-platform) read-only clone용
- wiki data deploy key: [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2) clone/push용, write 허용
- private key는 AWS SSM Parameter Store `SecureString`에 저장
- Terraform state에는 SSM parameter 이름만 저장

## 배포 모델 두 가지

team-wiki-v2 백킹은 배포 플랫폼에 따라 **두 가지 모델**이 있습니다. 신규 작업은 아래 #1을 사용합니다.

| 모델 | 플랫폼 | 저장소 | 동기화 주체 |
| --- | --- | --- | --- |
| **#1 named volume + compose 사이드카 (현행, PLA-275)** | `agent.plady.io` (account `781897847312`, EC2 + ALB, 무인 SSM 배포) | named volume `wiki-data:/workspace` | compose 서비스 `wiki-data-sync` |
| #2 host bind-mount + systemd (legacy) | `plady.kro.kr` (account `367177489299`, cloud-init) | host `./wiki-workspace` | `llm-wiki-data-sync.timer` |

---

## 모델 #1 — agent-platform: named volume + `wiki-data-sync` 사이드카 (현행)

신규 플랫폼(`compose.ec2.yaml`)은 cloud-init도 host bind-mount도 없습니다. `llm-wiki`/`wiki-ui`가 공유하는 **named volume `wiki-data`의 `/workspace`** = team-wiki-v2 repo root이고, 동기화는 compose 사이드카 서비스 **`wiki-data-sync`** (`alpine/git`)가 담당합니다. (legacy systemd timer를 그대로 포팅하지 않고 compose 서비스로 포팅한 이유: 무인 SSM 배포·멱등성·볼륨 모델 일관성.)

동작:

- **deploy key 없음** → 사이드카는 "backing DISABLED" 로그 후 idle. wiki-ui는 빈 scaffold를 계속 서빙하고 MCP는 볼륨을 read/write하지만 git 백킹은 안 됨. (스택 전체를 죽이지 않음.)
- **첫 부팅(볼륨 비어 `.git` 없음)** → `git init` → `remote add origin` → `fetch origin <branch>` → `checkout -f -B <branch> origin/<branch>`. tracked(`wiki/ raw/ inbox/ schemas/ wiki.toml`)는 채우고, untracked `site/`(v2 `.gitignore` 대상, wiki-ui가 wipe+recopy)는 보존.
- **재배포(볼륨 persist, `.git` 있음)** → 미커밋 로컬 변경 commit → `pull --rebase --autostash` (미푸시 로컬 커밋 보존).
- **동기화 루프** → `WIKI_SYNC_INTERVAL`초(기본 120)마다 `git add -A` → 변경 있으면 commit → `pull --rebase --autostash` → `push origin HEAD:<branch>`. pull→push 사이에 들어온 MCP write는 다음 사이클이 잡음. rebase 충돌 시 `rebase --abort` 후 그 사이클 push skip + 경고 로그, 다음 사이클 재시도.

관련 env(`scripts/ec2-deploy.sh`가 SSM에서 읽어 `.env.ec2`로 렌더):

| env | 기본값 | 출처 |
| --- | --- | --- |
| `TEAM_WIKI_V2_DEPLOY_KEY_B64` | (빈 값) | SSM `WIKI_DATA_KEY_PARAM` 값을 `base64 -w0` 인코딩 |
| `TEAM_WIKI_V2_REPO_SSH` | `git@github.com:100Thieves-team/team-wiki-v2.git` | env |
| `WIKI_SYNC_INTERVAL` | `120` | env |
| `WIKI_SYNC_BRANCH` | `main` | compose 기본 |

확인 / 운영:

```bash
# 사이드카 로그 (enabled/disabled, push 결과)
docker compose -f compose.ec2.yaml logs -f wiki-data-sync

# 볼륨이 v2 checkout인지
docker compose -f compose.ec2.yaml exec wiki-data-sync git -C /workspace log --oneline -5
docker compose -f compose.ec2.yaml exec wiki-data-sync git -C /workspace remote -v

# 즉시 push 강제 (사이클을 기다리지 않고)
docker compose -f compose.ec2.yaml exec wiki-data-sync sh -c 'cd /workspace && git add -A && git commit -m manual || true && git push origin HEAD:main'
```

### 1회 사람 작업 — deploy key를 신규 account SSM에 넣기

v2엔 write 가능한 deploy key `llm-wiki-ec2-prod-data-write`가 **이미 등록**돼 있습니다(재사용 가능). 단 private key는 legacy account(`367177489299`) SSM에만 있으니, 신규 account(`781897847312`)로 1회 복사해야 사이드카가 enabled 됩니다.

옵션 A — legacy 키 복사 (가장 간단):

```bash
# 1) legacy account에서 private key를 읽어 (legacy 자격증명으로)
KEY="$(aws ssm get-parameter --profile legacy --region <legacy-region> \
  --name /100thieves/wiki/data-repo-deploy-key --with-decryption \
  --query Parameter.Value --output text)"

# 2) 신규 account SSM SecureString으로 기록 (신규 자격증명으로)
aws ssm put-parameter --profile agent-platform --region <new-region> \
  --name /plady/agent-platform/dev/team-wiki-v2-deploy-key \
  --type SecureString --value "$KEY" --overwrite

unset KEY   # 셸 히스토리/환경에 남기지 말 것
```

옵션 B — 새 키 발급(권장 회전 시): `ssh-keygen -t ed25519` → 공개키를 v2 **Settings → Deploy keys**에 *Allow write access* 로 등록 → private key를 위 신규 SSM 파라미터에 기록 → legacy 키는 v2에서 제거(회전).

검증:

```bash
# 신규 account에서 파라미터가 보이는지 (값은 출력하지 말 것 — 존재만 확인)
aws ssm get-parameter --region <new-region> \
  --name /plady/agent-platform/dev/team-wiki-v2-deploy-key \
  --query 'Parameter.Type' --output text   # -> SecureString

# 재배포 후 사이드카 로그가 "backing ENABLED" 인지 확인
docker compose -f compose.ec2.yaml logs wiki-data-sync | grep -i 'backing'
```

> **실 secret(private key) 값은 repo/문서/PR/Linear/로그 어디에도 남기지 말 것.** SSM SecureString에만 존재. EC2 instance role은 이미 그 SecureString을 decryption 읽기 가능.

---

## 모델 #2 — legacy: host bind-mount + systemd timer

legacy `plady.kro.kr`(cloud-init, `infra/terraform/ec2`)는 host `./wiki-workspace`를 bind-mount하고, EC2 bootstrap이 `team-wiki-v2`를 `wiki-workspace/`로 clone한 뒤 `llm-wiki-data-sync.timer`를 활성화합니다.

이 timer는 주기적으로 아래 작업을 수행합니다.

1. `wiki-workspace` 상태 확인
2. 필요 시 local 변경 commit
3. `origin main`으로 push

확인:

```bash
sudo systemctl status llm-wiki-data-sync.timer
sudo journalctl -u llm-wiki-data-sync.service -n 100 --no-pager
```

수동 실행:

```bash
sudo /usr/local/bin/llm-wiki-data-sync
```

## 새 서버에서 데이터 복원

기존 wiki 데이터 repo를 새 서버에 붙이려면 app repo를 clone한 뒤, Compose 실행 전에 `wiki-workspace` 위치에 [`team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)를 clone합니다.

```bash
git clone https://github.com/100Thieves-team/plady-agent-platform.git /opt/plady-agent-platform
cd /opt/plady-agent-platform
rm -rf wiki-workspace
git clone https://github.com/100Thieves-team/team-wiki-v2.git wiki-workspace
docker compose up -d --build
```

## 주의사항

- `wiki-workspace/`는 wrapper repo의 `.gitignore` 대상입니다.
- 운영 SSOT는 [`team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)입니다.
- EC2 인스턴스를 destroy하기 전에 `llm-wiki-data-sync`가 최신 commit을 push했는지 확인하세요.
- data repo Deploy Key는 write 권한이 필요하지만, 권한 범위가 `team-wiki-v2` 단일 repo로 제한되므로 PAT보다 안전합니다.

## Legacy `team-wiki` migration

기존 [`100Thieves-team/team-wiki`](https://github.com/100Thieves-team/team-wiki) 문서는 `scripts/migrate-team-wiki.sh`로 새 llm-wiki data workspace에 이관합니다.

기본은 dry-run입니다.

```bash
scripts/migrate-team-wiki.sh
```

실제 복사:

```bash
scripts/migrate-team-wiki.sh --apply
```

이관 구조:

```text
wiki-workspace/
  raw/legacy-team-wiki/raw/          # 기존 raw 원문
  raw/legacy-team-wiki/Clippings/    # 기존 clipping 문서
  raw/legacy-team-wiki/attachments/  # 이미지/첨부파일
  raw/legacy-team-wiki/views/        # 기존 view 정의
  raw/legacy-team-wiki/root/         # 루트 markdown/html 문서
  wiki/                              # 새 llm-wiki doc schema로 정규화한 seed pages
  migration/team-wiki-migration-report.md
```

legacy repo의 자체 LLM Wiki/Obsidian 규칙은 active 규칙으로 가져오지 않습니다. `AGENTS.md`, `CLAUDE.md` 같은 루트 규칙성 문서는 `raw/legacy-team-wiki/root/`에 archive만 하고, 실제 index 대상 seed page는 현재 repo의 `doc` schema frontmatter로 정규화합니다.

이관 후에는 한 번에 전부 재작성하지 말고 batch별로 검증합니다.

```bash
scripts/check-mcp-tools.sh
# MCP에서 wiki_ingest, wiki_lint, wiki_index_rebuild를 batch별로 실행
```

권장 순서:

1. `wiki/people`
2. `wiki/topics`
3. `wiki/sources`
4. `raw/legacy-team-wiki/raw`
5. `raw/legacy-team-wiki/Clippings`

마지막으로 `wiki-workspace`에서 `git status`를 확인하고, 문제가 없으면 `team-wiki-v2`에 commit/push합니다.
