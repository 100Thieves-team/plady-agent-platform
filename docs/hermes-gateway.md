# Hermes Gateway 런타임 (PLA-249)

이 문서는 `plady-agent-platform`에서 **Hermes Agent Gateway**(OpenAI 호환 API 서버)를 어떻게 띄우고 운영하는지에 대한 SSOT runbook입니다. endpoint/secret **이름 계약**은 [`platform-contract.md`](platform-contract.md)가, PLA-244 핸드오프는 [`pla-244-handoff.md`](pla-244-handoff.md)가 SSOT입니다.

## 무엇을 띄우는가

- 런타임: [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent) 공개 이미지 `nousresearch/hermes-agent` (compose 기본 핀 `v2026.6.19` = v0.17.0, `HERMES_IMAGE`로 override). 초기 배포는 `v2026.4.3`(v0.7.0)였으나 PLA-244-B에서 성숙한 Slack 지원(`slack manifest`·스레드/승인 버튼)을 위해 상향.
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
| `HERMES_IMAGE` | 이미지 override(기본 `nousresearch/hermes-agent:v2026.6.19`). |
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

## MCP 도구 연동 (`mcp_servers` 매핑, PLA-244)

Hermes 에이전트가 llm-wiki MCP 도구를 호출하려면 `~/.hermes/config.yaml`(= named volume `hermes-home`, 컨테이너 `/opt/data/config.yaml`)의 `mcp_servers`에 llm-wiki 서버를 등록해야 한다. PLA-250 레지스트리([`mcp-registry.md`](mcp-registry.md) / [`config/mcp-registry.yaml`](../config/mcp-registry.yaml)) 계약을 Hermes config 스키마로 번역한 것이다.

### 어떻게 주입되는가 (멱등·secret-free)

- **헬퍼 서비스**: `compose.ec2.yaml`의 one-shot `hermes-config-init`(이미지 `mikefarah/yq`, profile `hermes`)가 `hermes-home` 볼륨의 `config.yaml`에 **runtime backend(`model.provider: openai-codex`, `model.default: gpt-5.5`, PLA-277)** + `mcp_servers.llm-wiki` + slack 동작 키를 **surgical leaf-`set`**으로 머지한다. 명시된 leaf만 건드리므로 사람이 둔 다른 키는 보존된다(파일 전체 덮어쓰기 금지). provider **자격**(Codex device-code OAuth 세션)은 같은 볼륨의 `auth.json`에 따로 있고 이 merge가 건드리지 않는다 — §2 참조.
- **배포 흐름**: `scripts/ec2-deploy.sh`가 이미지 pull 직후 `docker compose ... run --rm hermes-config-init`로 merge하고, 스택을 올린 뒤 `restart hermes-gateway`로 config를 로드시킨다. 매 배포 멱등(같은 키를 다시 써도 동일 결과).
- **endpoint**: 같은 compose 네트워크 내부 주소 `http://mcp-proxy:18765/mcp`를 쓴다(ALB 왕복·TLS 불필요). 공개 origin `https://mcp.agent.plady.io/mcp`도 동일 도구를 제공하지만 내부 경로가 더 짧고 안전하다.
- **토큰(절대 파일/repo에 평문 미커밋)**: `config.yaml`에는 `Authorization: "Bearer ${LLM_WIKI_MCP_BEARER_TOKEN}"` **플레이스홀더만** 들어간다. Hermes는 `transport.url`·`headers` 안의 `${VAR}`를 **MCP connect 시점에** 컨테이너 env(+`~/.hermes/.env`)에서 해석한다([업스트림 MCP config 문서](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md)). 그 env는 `hermes-gateway` 서비스의 `LLM_WIKI_MCP_BEARER_TOKEN: ${MCP_BEARER_TOKEN:-}`로 주입되며, 값은 기존 `.env.ec2`의 `MCP_BEARER_TOKEN`(SSM `/plady/agent-platform/<env>/llm-wiki-mcp-bearer-token`)과 동일하다. mcp-proxy가 같은 토큰을 검증하므로 한 값으로 충분하다.

> Hermes `mcp_servers` HTTP 항목 스키마는 평면형(`url`/`headers`/`timeout`/`tools.include`)이며 `transport:` 중첩이 아니다. 출처: [hermes-agent MCP config reference](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/mcp-config-reference.md), [use-mcp-with-hermes](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/use-mcp-with-hermes.md).

### 등록되는 도구 (현재: read-only `allow` tier만)

`config/mcp-registry.yaml`의 llm-wiki `allow` tier 11개만 `tools.include`에 넣는다(`include`는 화이트리스트 — 나머지는 자동 제외 = default-deny):

```
wiki_search, wiki_list, wiki_content_read, wiki_resolve, wiki_stats, wiki_lint,
wiki_history, wiki_suggest, wiki_graph, wiki_index_status, wiki_spaces_list
```

⚠️ **write(`approve`) tier는 의도적으로 제외**: `wiki_content_write`/`wiki_content_new`/`wiki_content_commit`/`wiki_ingest`/`wiki_export`는 [MCP 레지스트리의 Write 승인 흐름](mcp-registry.md#write-승인-흐름-approve-tier)을 강제하는 Slack interactive 승인 게이트(**PLA-244-B**)가 떠야 안전하게 노출할 수 있다. 그 게이트가 없는 현재 단계에서 include하면 `/v1` 경유 요청이 승인 없이 위키를 쓸 수 있으므로(완료 기준 "write는 명시적 승인 뒤에만" 위반), 244-B에서 승인 게이트와 함께 `hermes-config-init`의 include 목록에 추가한다. `deny` tier(`wiki_spaces_*`/`wiki_config`/`wiki_schema`/`wiki_index_rebuild`)는 운영자 opt-in 전까지 항상 제외.

### 검증

```bash
# (1) merge 결과 확인 — config.yaml에 mcp_servers.llm-wiki가 있고 토큰은 placeholder로만 존재
docker compose --env-file .env.ec2 -f compose.ec2.yaml --profile hermes \
  run --rm --entrypoint /bin/sh hermes-config-init -c 'cat /opt/data/config.yaml'
#   → mcp_servers.llm-wiki.url=http://mcp-proxy:18765/mcp,
#     headers.Authorization="Bearer ${LLM_WIKI_MCP_BEARER_TOKEN}" (평문 토큰 없음)

# (2) 에이전트가 실제로 도구를 잡는지 — provider(openai-codex device-code OAuth) 구성된 뒤,
#     /v1 chat completion으로 위키 검색을 유도하고 hermes 로그에서 llm-wiki MCP
#     연결/도구 호출을 확인. (MCP 연결은 lazy: 첫 도구 호출 시점에 맺어짐.)
docker compose --env-file .env.ec2 -f compose.ec2.yaml logs hermes-gateway | grep -i 'mcp\|llm-wiki'
```

## Slack 연동 (PLA-244-B)

Slack은 hermes의 **네이티브 메시징 플랫폼**이다. 별도 서비스/웹훅을 만들지 않는다 — 이미 떠 있는 `hermes-gateway`의 단일 `gateway run` 프로세스가 OpenAI API와 Slack을 **동시에** 서빙한다. **Socket Mode**(WebSocket)라 공개 인바운드 URL이 필요 없다(ALB/PLA-247 무관). 출처: [hermes-agent Slack 문서](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/messaging/slack.md), [messaging gateway](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/messaging/index.md).

### 어떻게 배선되는가 (secret-free 코드)

- **활성화 = 토큰 존재**. `SLACK_BOT_TOKEN`(xoxb-)·`SLACK_APP_TOKEN`(xapp-)이 컨테이너 env에 있으면 Slack 플랫폼이 자동으로 켜진다(별도 enable 플래그 없음). 둘 다 비면 Slack은 그냥 꺼진 채 API 서버만 뜬다.
- **env 주입**: `compose.ec2.yaml`의 `hermes-gateway`가 `SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN`/`SLACK_ALLOWED_USERS`를 받고, `scripts/ec2-deploy.sh`가 SSM에서 읽어 `.env.ec2`로 채운다(모두 optional). hermes의 env 우선순위는 process env > `~/.hermes/.env` > 기본값이라 컨테이너 env 주입이 그대로 동작한다(기존 `API_SERVER_KEY` 방식과 동일).
- **동작 설정**: `hermes-config-init`이 config.yaml에 Slack 동작 키를 merge한다. hermes(v0.17) 스키마상 키가 **두 곳으로 분리**됨(소스 `gateway/config.py`·`messaging/slack.md`로 검증): 최상위 `slack:`에 `require_mention: true` + `unauthorized_dm_behavior: ignore`, `platforms.slack:`에 `reply_to_mode: first` + `extra.reply_in_thread/reply_broadcast`. 플랫폼 활성화는 토큰이 하고, 이 키들은 동작만 튜닝한다. (leaf 단위로 set 해서 사람이 둔 다른 키는 보존.)
- **접근 제어(allowlist) = `SLACK_ALLOWED_USERS`** (Slack Member ID `U…`, 쉼표 구분). **fail-closed**: 비어 있으면 모든 Slack 사용자 거부(이관 #2 충족). 미인가 DM은 `unauthorized_dm_behavior: ignore`로 조용히 무시(원하면 `pair`로 바꿔 1회용 페어링 코드 발급 가능).

### write 도구 정책 (현재 read-only)

Slack을 통한 에이전트의 도구는 `mcp_servers`가 제공하는 것뿐이고, 현재는 **llm-wiki read 도구만**(11개) 노출된다. write(`wiki_content_*`/`wiki_ingest`/`wiki_export`)는 **의도적으로 비활성**: hermes에는 MCP 도구 호출을 막는 승인 게이트가 없어(`approvals.mode`는 셸 명령만, [#16462](https://github.com/NousResearch/hermes-agent/issues/16462)은 제안 단계) write를 켜면 allowlist된 사용자가 승인 없이 위키를 변경하게 된다. 따라서 "write는 승인 뒤에만" 기준을 **노출하지 않음**으로 충족한다. 상세는 [`mcp-registry.md` Write 승인 흐름](mcp-registry.md#write-승인-흐름-approve-tier).

### 장애 시 동작

provider/MCP 오류는 hermes가 해당 Slack 스레드에 에러 메시지로 응답한다. hermes 자체가 다운되면 Socket Mode 연결이 끊겨 봇이 응답하지 않는다(공개 엔드포인트가 없어 외부로 새는 표면 없음). 별도 처리 불필요.

### 검증 (사람: 앱·토큰 준비 후)

```bash
# config.yaml에 platforms.slack이 들어갔는지 (토큰 평문 없음 확인)
docker compose --env-file .env.ec2 -f compose.ec2.yaml --profile hermes \
  run --rm -T --entrypoint /bin/sh hermes-config-init -c 'cat /opt/data/config.yaml'

# 부팅 로그에서 Slack 플랫폼 연결 확인 (allowlist 경고가 사라졌는지도)
docker compose --env-file .env.ec2 -f compose.ec2.yaml logs hermes-gateway | grep -i slack
```

- allowlist에 든 사용자가 봇을 DM하거나 채널에서 `@봇` 멘션 → 응답 + (요청 시) 위키 검색 결과.
- allowlist 밖 사용자가 DM → 무응답(ignore). → fail-closed 확인.

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

### 2. Hermes provider 자격 구성 — openai-codex device-code OAuth (`/v1/models`·chat용)

런타임 백엔드는 **`openai-codex` provider**(ChatGPT 구독, "Sign in with ChatGPT")이다(PLA-277). 이전 Claude Code OAuth 경로는 Anthropic의 서드파티 앱 구독 한도 차단(2026-04-04 정책)으로 막혀 전환했다 — 배경은 [PLA-277](https://linear.app/100-thieves/issue/PLA-277).

**Claude 경로와의 핵심 차이 — 자격은 env가 아니라 볼륨 파일이다.** Codex 자격은 SSM secret이나 env 토큰이 아니라 **device-code OAuth 세션**(리프레시 토큰)으로, hermes가 `~/.hermes/auth.json`(= `hermes-home` 볼륨의 `/opt/data/auth.json`)에 영속한다. 그래서:

- **provider 선택**은 코드가 선언적으로 한다 — `hermes-config-init`이 `config.yaml`에 `model.provider: openai-codex` + `model.default: gpt-5.5`를 머지(별도 `hermes setup` 마법사 불필요). API key·`OPENAI_API_KEY`·Codex CLI 설치 **모두 불필요**. (별칭 `codex`는 ChatGPT 계정 백엔드가 HTTP 400 `unsupported-model`로 거부하므로 실제 모델 ID `gpt-5.5`를 쓴다.)
- **로그인은 사람이 1회** — 브라우저로 device-code OAuth를 통과해 `auth.json`을 **같은 볼륨에** 써야 게이트웨이가 본다. SSM 정적 주입과 맞지 않는 부분(이관 #2).
- 볼륨이 유지되는 한 재시작/이미지 업데이트에도 자격이 보존된다. **볼륨 reset 시 재로그인** 필요(아래 "Session persistence / reset").

> 로그인은 반드시 게이트웨이와 **같은 `hermes-home` 볼륨**에 기록해야 한다. `docker compose run`으로 `hermes-gateway`(같은 볼륨 마운트)에서 실행하면 TTY가 붙어 device code/URL을 읽을 수 있고, 결과 `auth.json`이 볼륨에 남아 이후 무인 기동에서 그대로 쓰인다. 헤드리스로 토큰만 주입하는 공식 경로는 없다 — 사람이 1회 인터랙티브 로그인.

```bash
# (1) provider 선택을 config.yaml에 머지 (배포 흐름이 자동으로 하지만, 수동도 가능).
#     main 머지/재배포 시 ec2-deploy.sh가 hermes-config-init으로 멱등 적용한다.
#     NOTE: EC2의 .env.ec2는 root 소유 600 secret이라 모든 compose 명령에 sudo 필요.
sudo docker compose --env-file .env.ec2 -f compose.ec2.yaml --profile hermes \
  run -T --rm hermes-config-init
#   → config.yaml에 model.provider: openai-codex / model.default: gpt-5.5 머지
#     (model.default는 ChatGPT 계정에서 거부되는 별칭 "codex"가 아니라 실제 모델 ID여야 한다.)

# (2) device-code OAuth 로그인 — 사람이 1회, 같은 hermes-home 볼륨에 대고 실행.
#     브라우저로 ChatGPT 구독 로그인(device code 입력). 자격은 /opt/data/auth.json에 영속.
#     provider 이름은 핀 버전(v2026.6.19)이 받는 "openai-codex"다("codex-oauth"는
#     Unknown provider로 거부됨 — 버전 스큐). 이름 헷갈리면 `... model` 인터랙티브 권장.
sudo docker compose --env-file .env.ec2 -f compose.ec2.yaml --profile hermes \
  run --rm hermes-gateway auth add openai-codex
#   → 출력된 URL 열고 코드 입력 → ChatGPT(구독) 로그인 → auth.json 기록.
#     (대안/권장: `... run --rm hermes-gateway model` 에서 OpenAI Codex + gpt-5.5 선택.)

# (3) 게이트웨이 기동/재기동 — config.yaml(provider) + auth.json(자격)을 로드.
docker compose --env-file .env.ec2 -f compose.ec2.yaml --profile hermes up -d hermes-gateway
```

> `auth.json`은 OAuth 리프레시 토큰을 담은 **secret**이다 — `hermes-home` 볼륨은 secret-grade로 취급(커밋·비암호 백업 금지, `HERMES_UID/GID` 권한 제한). 배포 로그는 자격 값을 찍지 않고 `codex auth: device-code OAuth in hermes-home volume (not env)`만 출력한다(`scripts/ec2-deploy.sh`).
>
> **지속가능성/ToS 점검(이관 #3)**: 항상 떠 있는 멀티유저 Slack 게이트웨이를 ChatGPT 구독 1개로 운영하면 5시간/주간 rate limit + "구독으로 멀티유저 서빙" ToS가 걸릴 수 있다. 메커니즘은 first-party로 동작하나 **팀 정책 판단 사안** — 막히면 fallback으로 raw `ANTHROPIC_API_KEY` provider 회귀(PLA-277 대안 절).

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

### 3.5. MCP 도구 연동 적용 (PLA-244)

`mcp_servers.llm-wiki` 매핑은 배포 흐름(`scripts/ec2-deploy.sh`의 `hermes-config-init`)이 자동으로 멱등 주입한다. **새 SSM secret을 만들 필요 없음** — bearer 토큰은 이미 존재하는 `/plady/agent-platform/<env>/llm-wiki-mcp-bearer-token`(런타임 `MCP_BEARER_TOKEN`)을 재사용한다. 적용하려면 `main`에 머지(=재배포)하면 끝. 상세·검증은 위 [MCP 도구 연동](#mcp-도구-연동-mcp_servers-매핑-pla-244) 절을 따른다. write 도구 노출은 PLA-244-B(Slack 승인 게이트)에서 추가.

### 3.6. Slack 앱 생성 + 토큰/allowlist → SSM (PLA-244-B)

코드 배선은 끝나 있다. 사람은 Slack 앱을 만들고 토큰 3개를 SSM에 넣은 뒤 재배포만 하면 된다.

```bash
# (1) Slack 앱 manifest 생성 (이미지가 기대하는 scope/event/Socket Mode 그대로)
APP_NAME="Plady Hermes" bash scripts/hermes-slack-manifest.sh   # JSON 출력
#   → https://api.slack.com/apps → Create New App → From a manifest 에 붙여넣기

# (2) Slack 앱에서:
#   - Socket Mode 활성화 → App-Level Token 발급(scope connections:write) = xapp-...
#   - 워크스페이스에 Install → Bot User OAuth Token = xoxb-...
#   - (manifest가 bot scope: chat:write, app_mentions:read, channels:history,
#     im:history, users:read 등 + event message.im/message.channels/app_mention 포함)

# (3) 허용할 사용자 Slack Member ID 수집 (프로필 → Copy member ID, U…)

# (4) SSM SecureString 저장 (<env>=dev). 값은 절대 커밋/공유 금지.
aws ssm put-parameter --region ap-northeast-2 --type SecureString \
  --name /plady/agent-platform/dev/slack-bot-token   --value "xoxb-..."
aws ssm put-parameter --region ap-northeast-2 --type SecureString \
  --name /plady/agent-platform/dev/slack-app-token   --value "xapp-..."
aws ssm put-parameter --region ap-northeast-2 --type SecureString \
  --name /plady/agent-platform/dev/slack-allowed-users --value "U0AAA,U0BBB"   # 쉼표 구분

# (5) 재배포(main 머지 또는 워크플로 dispatch). ec2-deploy.sh가 SSM→.env.ec2 주입,
#     config-init이 platforms.slack merge, hermes 재시작 시 Slack 플랫폼 활성화.
```

> allowlist를 비워두면 **모든 Slack 사용자가 거부**된다(의도된 fail-closed). 최소 1명의 Member ID는 넣어야 봇이 동작한다. 토큰 회전은 `--overwrite`.

### 4. (PLA-247) 공개 라우팅 — 별도 이슈 소관

`https://hermes.agent.plady.io`(+`/v1`)를 내부 `hermes-gateway:8642`로 라우팅(DNS A/ALB host rule 또는 Caddy reverse_proxy)하는 것은 PLA-247 작업이다. 이 이슈는 내부 타깃과 계약만 제공한다. PLA-247에 전달할 값:

- 내부 타깃: `hermes-gateway:8642` (compose 네트워크)
- public origin: `https://hermes.agent.plady.io`, OpenAI base URL은 동일 origin의 `/v1`
- TLS 종단은 ingress에서. 컨테이너는 host publish 없이 `expose`만 유지.
