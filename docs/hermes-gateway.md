# Hermes Gateway 런타임 (PLA-249)

이 문서는 `plady-agent-platform`에서 **Hermes Agent Gateway**(OpenAI 호환 API 서버)를 어떻게 띄우고 운영하는지에 대한 SSOT runbook입니다. endpoint/secret **이름 계약**은 [`platform-contract.md`](platform-contract.md)가, PLA-244 핸드오프는 [`pla-244-handoff.md`](pla-244-handoff.md)가 SSOT입니다.

## 무엇을 띄우는가

- 런타임: [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent) 공개 이미지 `nousresearch/hermes-agent` (compose 기본 핀 `v2026.4.3`, `HERMES_IMAGE`로 override).
- 프로세스 모델: 단일 `gateway run` 프로세스가 **OpenAI 호환 HTTP API 서버**를 노출. 별도 `dashboard` 컨테이너는 API key를 저장하므로 **공개하지 않음**(필요 시 127.0.0.1 + SSH 터널).
- compose 서비스: `hermes-gateway` (profile `hermes`). 기본 `docker compose up`에서는 뜨지 않음.
- 영속화: named volume `hermes-home` → 컨테이너 `/opt/data`.

### 네트워크/포트

| 항목 | 값 |
| --- | --- |
| 컨테이너 내부 바인드 | `API_SERVER_HOST=0.0.0.0`, `API_SERVER_PORT=8642` |
| 로컬(`compose.yaml`) | host publish `8642:8642` (smoke 편의) |
| 운영(`compose.ec2.yaml`) | host publish 없음, compose 네트워크에만 `expose: 8642` |
| 공개 origin | `https://hermes.agent.plady.io` → `hermes-gateway:8642` 라우팅은 **PLA-247**(DNS/ACM/ALB) 소관 |
| OpenAI base URL | `https://hermes.agent.plady.io/v1` |

> 컨테이너 안에서 `0.0.0.0` 바인드는 **host publish가 없다는 전제** 하에 안전합니다. 운영에서는 절대 `ports`로 host에 직접 노출하지 말고, 공개는 PLA-247 ingress(TLS 종단) 뒤에서만 합니다.

## 환경 변수

| 변수 | 용도 |
| --- | --- |
| `API_SERVER_ENABLED=true` | API 서버 활성화(기본 false). |
| `API_SERVER_KEY` | **모든 배포에서 필수**(loopback 포함) Bearer 인증 키. 값은 SSM `/plady/agent-platform/<env>/hermes-api-server-key`에서 조회. compose에는 host env `HERMES_API_SERVER_KEY`로 주입. |
| `API_SERVER_PORT=8642` / `API_SERVER_HOST=0.0.0.0` | 위 표 참조. |
| `HERMES_UID` / `HERMES_GID` | `hermes-home` 볼륨 파일 소유자. 기본 `10000`. |
| `HERMES_IMAGE` | 이미지 override(기본 `nousresearch/hermes-agent:v2026.4.3`). |
| `HERMES_PLATFORM` | 이미지 플랫폼(기본 `linux/amd64`). 이미지가 amd64 전용이라 Apple Silicon(arm64)에서는 에뮬레이션으로 실행된다. EC2(amd64)는 네이티브. |

실제 키 값은 문서/코드/Linear/PR에 **절대** 남기지 않습니다.

## Runbook (start / stop / restart / health)

```bash
# 키 주입 (로컬). 값은 SSM에서 조회한 실제 키. 커밋 금지.
export HERMES_API_SERVER_KEY="<from /plady/agent-platform/<env>/hermes-api-server-key>"

# start
docker compose --profile hermes up -d hermes-gateway

# stop / start / restart
docker compose stop hermes-gateway
docker compose start hermes-gateway
docker compose restart hermes-gateway

# logs
docker compose logs -f hermes-gateway

# health (무인증)
curl -fsS localhost:8642/health      # -> {"status":"ok"}

# 전체 smoke (health + 401 + authenticated /v1/models)
HERMES_API_KEY="$HERMES_API_SERVER_KEY" scripts/hermes-gateway-smoke.sh
```

운영(EC2)에서는 `--env-file .env.ec2 -f compose.ec2.yaml`를 붙이고(`.env.ec2`에 `HERMES_API_SERVER_KEY` 포함), host publish가 없으므로 smoke는 컨테이너 내부 또는 ingress를 통해 수행합니다:

```bash
docker compose --env-file .env.ec2 -f compose.ec2.yaml --profile hermes up -d hermes-gateway
docker compose --env-file .env.ec2 -f compose.ec2.yaml exec hermes-gateway \
  curl -fsS localhost:8642/health
```

### Endpoints

| Method | Path | 인증 | 비고 |
| --- | --- | --- | --- |
| GET | `/health` | 없음 | `{"status":"ok"}` |
| GET | `/v1/models` | Bearer | 모델 목록(provider 구성 필요) |
| POST | `/v1/chat/completions` | Bearer | OpenAI Chat Completions |
| POST | `/v1/responses` | Bearer | OpenAI Responses(대화 상태) |
| GET | `/v1/capabilities` | Bearer | API surface 설명 |

인증: `Authorization: Bearer <API_SERVER_KEY>`.

## Session persistence / reset / rollback

세션 상태, OAuth 토큰, tool 자격/state는 모두 `hermes-home` 볼륨(`/opt/data`)에 영속화됩니다.

- **persistence**: 볼륨이 유지되는 한 컨테이너 재시작/이미지 업데이트에도 세션·OAuth·tool state가 보존됩니다.
- **reset (파괴적)**: 모든 세션·OAuth·tool 자격을 초기화.
  ```bash
  docker compose --profile hermes stop hermes-gateway
  docker volume rm <project>_hermes-home   # 예: feat_pla-249-hermes-runtime_hermes-home
  docker compose --profile hermes up -d hermes-gateway
  ```
  `<project>`는 `docker volume ls`로 확인. 이 작업은 되돌릴 수 없습니다.
- **rollback (백업/복원)**: reset 전 또는 업그레이드 전 볼륨 스냅샷.
  ```bash
  # 백업
  docker run --rm -v <project>_hermes-home:/data -v "$PWD":/backup alpine \
    tar czf /backup/hermes-home-backup.tgz -C /data .
  # 복원
  docker run --rm -v <project>_hermes-home:/data -v "$PWD":/backup alpine \
    sh -c 'rm -rf /data/* && tar xzf /backup/hermes-home-backup.tgz -C /data'
  ```
  백업 산출물은 OAuth 토큰/자격을 포함하므로 **secret로 취급**(암호화 보관, 커밋 금지).
- **버전 rollback**: `HERMES_IMAGE`를 이전 핀 태그로 바꿔 재기동.

## 보안 주의사항

- `API_SERVER_KEY`는 모든 배포에서 필수이며 SSM에서만 조회합니다. 문서/코드/PR/Slack에 값을 남기지 않습니다.
- `hermes-home`(`/opt/data`)은 **session 메모리 · OAuth 토큰 · tool 자격**을 보관합니다. secret-grade 볼륨으로 취급: `HERMES_UID/GID`로 파일 권한 제한, 공유/비암호 위치 백업 금지, repo에 커밋 금지.
- `X-Hermes-Session-Key`는 세션 스코프 라우팅 키입니다(≤256자, control char 거부, 응답에 echo). PLA-244가 Slack workspace/user 단위로 안전하게 매핑·주입하며, 추측 가능한 값/PII 그대로 사용을 피합니다.
- `dashboard` 컨테이너는 API key를 저장하므로 공개 노출하지 않습니다. 필요 시 `127.0.0.1` 바인드 + SSH 터널로만 접근.
- 운영에서 host publish(`ports`) 금지. 공개 노출/TLS 종단은 PLA-247 ingress 뒤에서만.

## PLA-244 핸드오프 요약

| 항목 | 값 |
| --- | --- |
| Public origin | `https://hermes.agent.plady.io` |
| OpenAI base URL | `https://hermes.agent.plady.io/v1` |
| Auth header | `Authorization: Bearer <API_SERVER_KEY>` |
| Session header(선택) | `X-Hermes-Session-Key: <scope>` (≤256자, control char 금지) |
| Secret reference | `/plady/agent-platform/<env>/hermes-api-server-key` |

상세 소비 계약은 [`pla-244-handoff.md`](pla-244-handoff.md)를 따릅니다.

## 🙋 사람이 직접 해야 하는 일 (구체 절차)

> 아래는 사람만 할 수 있는 작업이다(실 secret/credential, 외부 자격). 실제 키 값은 어디에도 커밋하지 않는다.

### 1. `API_SERVER_KEY` 생성 → SSM 저장 → 런타임 주입

```bash
# (1) 강한 키 생성 (예: 32바이트 hex)
KEY="$(openssl rand -hex 32)"

# (2) SSM SecureString으로 저장 (<env> = dev|staging|prod)
aws ssm put-parameter \
  --region ap-northeast-2 \
  --name "/plady/agent-platform/dev/hermes-api-server-key" \
  --type SecureString \
  --value "$KEY"
# 키 회전 시 --overwrite 추가.

# (3-로컬) 컨테이너에 주입할 host env로 export
export HERMES_API_SERVER_KEY="$(aws ssm get-parameter \
  --region ap-northeast-2 \
  --name /plady/agent-platform/dev/hermes-api-server-key \
  --with-decryption --query Parameter.Value --output text)"

# (3-EC2) .env.ec2 에 한 줄 추가 (값은 SSM에서 조회해 채움, 커밋 금지)
#   HERMES_API_SERVER_KEY=<위 SSM 값>
# 기존 refresh-ec2-runtime-env.sh 흐름을 쓰면 SSM→.env.ec2 주입을 자동화할 수 있다.
```

`KEY` 셸 변수는 사용 후 `unset KEY`. 값은 Linear/PR/Slack/문서에 붙여넣지 않는다.

### 2. Hermes provider 자격 구성 (`/v1/models`·chat용)

provider(예: Anthropic/OpenAI/Nous Portal)를 구성해야 `/v1/models`가 모델을 반환한다. 설정은 `~/.hermes/config.yaml`(model/provider) + `~/.hermes/.env`(API key)에 저장되며, **우리 compose에서는 이 경로가 named volume `hermes-home`(`/opt/data`)에 매핑**된다.

> ⚠️ 업스트림 문서의 `docker run -v ~/.hermes:/opt/data ... setup`을 그대로 쓰면 **다른 위치**(호스트 `~/.hermes`)에 저장되어 우리 `hermes-gateway` 컨테이너가 보지 못한다. 반드시 아래처럼 **`docker compose run`으로 같은 `hermes-home` 볼륨**에 설정한다.

```bash
# HERMES_API_SERVER_KEY 가 export 되어 있어야 한다(위 1단계).

# 방식 A: 대화형 setup 마법사 (권장) — 같은 hermes-home 볼륨에 기록
docker compose --profile hermes run --rm hermes-gateway setup
#   → provider 선택, API key 입력(또는 Nous Portal OAuth 브라우저 플로우).

# 방식 B: 이미 구성된 설치에서 provider/model 추가·전환
docker compose --profile hermes run --rm hermes-gateway model
```

provider별 env 변수(참고): Anthropic `ANTHROPIC_API_KEY`, OpenAI `OPENAI_API_KEY`, OpenRouter `OPENROUTER_API_KEY`, Google `GOOGLE_API_KEY`/`GEMINI_API_KEY`, DeepSeek `DEEPSEEK_API_KEY`. Nous Portal은 OAuth 자동. (env로 주입하려면 secrets-manager/CI 연계 시 `-e` 전달; 디스크에 키를 두지 않으려는 경우에 유용.)

### 3. 기동 + smoke (위 1·2 완료 후)

```bash
# 기동
docker compose --profile hermes up -d hermes-gateway

# health (무인증)
curl -fsS localhost:8642/health        # -> {"status":"ok"}

# 전체 smoke: health → 무인증 401 → Bearer 200 /v1/models
HERMES_API_KEY="$HERMES_API_SERVER_KEY" scripts/hermes-gateway-smoke.sh
```

EC2(운영)는 host publish가 없으므로 컨테이너 내부 또는 PLA-247 ingress를 통해 호출한다:

```bash
docker compose --env-file .env.ec2 -f compose.ec2.yaml --profile hermes up -d hermes-gateway
docker compose --env-file .env.ec2 -f compose.ec2.yaml exec hermes-gateway curl -fsS localhost:8642/health
```

### 4. (PLA-247) 공개 라우팅 — 별도 이슈 소관

`https://hermes.agent.plady.io`(+`/v1`)를 내부 `hermes-gateway:8642`로 라우팅(DNS A/ALB host rule 또는 Caddy reverse_proxy)하는 것은 PLA-247 작업이다. 이 이슈는 내부 타깃과 계약만 제공한다. PLA-247에 전달할 값:

- 내부 타깃: `hermes-gateway:8642` (compose 네트워크)
- public origin: `https://hermes.agent.plady.io`, OpenAI base URL은 동일 origin의 `/v1`
- TLS 종단은 ingress에서. 컨테이너는 host publish 없이 `expose`만 유지.
