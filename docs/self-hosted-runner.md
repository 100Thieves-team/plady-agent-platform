# Self-hosted GitHub Actions 러너 (agent-platform EC2)

review-swarm([docs/review-swarm.md](review-swarm.md))이 도는 `[self-hosted, review-swarm]` 러너를 개인 맥북이 아니라
플랫폼 EC2(`plady-agent-platform-origin`, t3.small)에 **org 레벨**로 둔다. org 러너 하나를 `moimyeon-backend`,
`plady-agent-platform` 등 팀 저장소 전체가 공유한다.

| 항목 | 값 |
| --- | --- |
| 러너 이름 / 라벨 | `agent-platform-ec2` / `self-hosted, review-swarm, linux, ec2` |
| 호스트 유저 / 경로 | `actions-runner` / `/home/actions-runner/actions-runner` (systemd `actions.runner.100Thieves-team.agent-platform-ec2`) |
| 엔진 | Claude Code CLI (npm 전역, 러너 유저 `~/.npm-global/bin`), 인증은 SSM `claude-code-oauth-token` → 러너 `.env`의 `CLAUDE_CODE_OAUTH_TOKEN` |
| 설치 스크립트 | [`scripts/ec2-runner-setup.sh`](../scripts/ec2-runner-setup.sh) — `prepare` / `register` / `env` / `doctor` / `remove` |

## 절차

스크립트는 ec2-deploy.sh 와 같은 방식(base64 → `aws ssm send-command`)으로 실행한다. 아래 `ssm_run` 은 그 래퍼다.

```bash
export AWS_PROFILE=plady-service AWS_REGION=ap-northeast-2 INSTANCE=i-0b20c468bf62e8a1f
ssm_run() {  # ssm_run <phase>
  local b64; b64="$(base64 < scripts/ec2-runner-setup.sh | tr -d '\n')"
  local remote="set -euo pipefail
echo '${b64}' | base64 -d > /tmp/ec2-runner-setup.sh
export AWS_REGION=${AWS_REGION} PLATFORM_ENV=dev
bash /tmp/ec2-runner-setup.sh $1"
  local p; p="$(mktemp)"; jq -n --arg c "$remote" '{commands:[$c],executionTimeout:["1500"]}' > "$p"
  aws ssm send-command --instance-ids "$INSTANCE" --document-name AWS-RunShellScript \
    --comment "runner $1" --parameters "file://$p" --query Command.CommandId --output text; rm -f "$p"
}
```

1. **호스트 준비** (멱등): `ssm_run prepare` — 오래된 도커 이미지 정리, 2 GB 스왑, git/node 22/libicu, `actions-runner` 유저,
   actions/runner 타르볼(sha256 검증), Claude Code CLI 설치.
2. **등록 토큰 발급 → SSM** (org admin 권한 필요. 토큰은 1시간짜리, 러너 등록에만 쓰인다. 화면에 찍지 않는다):
   ```bash
   gh auth refresh -h github.com -s admin:org   # 최초 1회, 브라우저 device flow
   gh api -X POST orgs/100Thieves-team/actions/runners/registration-token --jq .token \
     | xargs -I{} aws ssm put-parameter --name /plady/agent-platform/dev/gha-runner-registration-token \
         --type SecureString --overwrite --value {}
   ```
3. **등록 + 서비스**: `ssm_run register` — `config.sh --unattended --replace` → `.env` 작성 → `svc.sh install/start`.
   끝나면 SSM 파라미터를 지운다(스크립트가 시도하지만 인스턴스 롤에 delete 권한이 없다):
   `aws ssm delete-parameter --name /plady/agent-platform/dev/gha-runner-registration-token`
4. **확인**: `ssm_run doctor` (서비스 상태 + 러너 유저로 `claude -p` 한 번) 와
   `gh api orgs/100Thieves-team/actions/runners --jq '.runners[]|[.name,.status,.busy]'`.
5. **저장소 쪽**: org Settings → Actions → Runner groups → Default 그룹이 모든 저장소에 열려 있는지 확인(기본값).
   `runs-on: [self-hosted, review-swarm]` 은 그대로 두면 된다. 이 저장소는 repository variable
   `REVIEW_SWARM_ENABLED=true` 로 잡을 켠다.
6. **맥북 러너 제거**: 테스트 PR 이 EC2 러너에서 돈 것을 확인한 뒤 moimyeon-backend Settings → Actions → Runners → `mac-review-swarm` Remove.
   둘이 같이 켜져 있으면 GitHub 이 노는 쪽에 잡을 준다.

## 사이징과 한계

- t3.small = vCPU 2 / RAM 2 GB. 스택(hermes 포함)이 이미 ~1 GB 를 쓰므로 리뷰 잡은 나머지 1 GB + 스왑 2 GB 안에서 돈다.
  `claude -p` 프로세스 하나가 300–600 MB 라 **`.review-swarm.yaml` 의 `engine.concurrency` 는 2 이하**로 둔다
  (이 저장소와 moimyeon-backend 모두 2). 리뷰가 느리거나 OOM 이 보이면 인스턴스를 t3.medium(4 GB) 으로 올리고
  `infra/terraform/platform` 의 `instance_type` 을 같이 맞춘다 — 그 다음에 concurrency 를 `router.maxAgents` 까지 올린다.
- 러너는 잡을 한 번에 하나만 받는다(러너 동시성 1). 두 저장소에서 동시에 PR 이 열리면 뒤의 잡은 큐에서 기다린다.
- 디스크: ec2-deploy.sh 가 배포 끝에 72시간 넘은 미사용 이미지를 지운다. 러너 `_work` 는 저장소 체크아웃 크기만큼 쓴다.
- 토큰 갱신: SSM 의 `claude-code-oauth-token` 을 바꿨으면 `ssm_run env` 로 러너 `.env` 를 다시 쓰고
  `systemctl restart actions.runner.100Thieves-team.agent-platform-ec2` 한다.
- 러너 버전 업: 스크립트 상단 `RUNNER_VERSION` / `RUNNER_SHA256` 을 올리고 `prepare` → `register` 를 다시 돈다(`--replace`).

## 보안 메모

- 두 저장소 워크플로 모두 `pull_request`(fork 제외 가드 포함)이며 `pull_request_target` 이 아니다. public 저장소인
  moimyeon-backend 는 Settings → Actions → General → "Require approval for all external contributors" 를 켜 둔다.
- 액션은 커밋 SHA 로 고정한다(`100Thieves-team/review-swarm@<sha>`). self-hosted 러너에서 `pull-requests: write` 로 도는 코드라
  mutable 참조를 쓰지 않는다.
- 러너 `.env`(0600, 러너 유저 소유)에 구독 토큰이 평문으로 있다. `.env.ec2` 와 같은 등급으로 다룬다.
