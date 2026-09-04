# Webex 회의 → 위키 자동 ingest (n8n)

Webex 회의가 끝나고 transcript 가 만들어지면 n8n 이 원문을 위키에 **보관**하고, Hermes 가 만든 초안으로 **컴파일**까지 시도한다. [`meeting-ingest.md`](meeting-ingest.md) 의 v1 경로이자 [`n8n-placeholder.md`](n8n-placeholder.md) 가 예약해 두던 자리의 실제 런타임이다. Slack 허들은 Hermes Slack 앱이 이미 맡고 있어 여기 범위가 아니다.

## 흐름

```
Webex  ──(webhook meetingTranscripts/created, X-Spark-Signature)──▶  n8n  https://n8n.agent.plady.io/webhook/webex-transcript
                                                                     │
        1. HMAC-SHA1 검증 (raw body, WEBEX_WEBHOOK_SECRET)          │
        2. GET /v1/meetings/{id}, GET /v1/meetingTranscripts/{id}/download?format=txt   (Webex OAuth2 credential)
        3. wiki_apply mode=archive → raw/meetings/webex-<날짜>-<제목>          (결정적, 항상)
        4. wiki_ingest_plan + wiki_rules + 후보 페이지 읽기 → Hermes /v1/chat/completions 에 초안 요청
        5. 초안(JSON: sources/ 1개 + topics/people 수정본)을 wiki_apply mode=knowledge, expected_head 로 커밋   (best effort)
        6. 실패 시 _wiki-alert 에 "원문은 보관됨, ingest 마무리 요청" 알림 (성공 알림은 wiki-data-sync 가 커밋 기준으로 보냄)
```

- **쓰기는 n8n 만 한다.** Hermes 는 여전히 읽기 도구만 가진다(레지스트리 `approve` tier 미노출). 모델은 초안만 내고, 검증·커밋은 `wiki_apply` 트랜잭션이 한다. "쓰기는 승인된 경로 뒤에서만" 이라는 계약을 코드가 지킨다.
- **멱등**: Webex 가 같은 이벤트를 재전송하거나 컴파일 실패 후 다시 돌려도, 이미 보관된 원문은 건너뛰고(`already archived`) 이미 source 페이지가 있으면 컴파일도 건너뛴다(`already compiled`).
- 워크플로 정의는 [`n8n/workflows/`](../n8n/workflows/) 가 SSOT. 배포마다 `n8n import:workflow` 로 덮어쓴다. 편집기에서 고쳤다면 export 해서 레포에 넣어야 살아남는다.

## 런타임 (EC2)

| 항목 | 값 |
| --- | --- |
| compose 서비스 | `n8n` (profile `n8n`, `compose.ec2.yaml`), 이미지 `n8nio/n8n:2.37.9` 핀 |
| 내부 타깃 | `n8n:5678` (host publish 없음) |
| 공개 | `https://n8n.agent.plady.io` — ALB → Caddy `@n8n` |
| 공개 경로 | `/webhook/*` 만 인증 없이 n8n 으로. 워크플로가 서명을 검증한다 |
| 편집기·REST | wiki 와 같은 팀 비밀번호 세션(wiki-auth `forward_auth`) 뒤 + n8n owner 로그인 |
| 영속화 | named volume `n8n-data` (`/home/node/.n8n`, SQLite + credential) |
| 실행 로그 | 14일 후 자동 정리(`EXECUTIONS_DATA_MAX_AGE=336`) — transcript 가 실행 데이터에 남으므로 길게 두지 않는다 |

### SSM 이름 계약 (값은 어디에도 남기지 않음)

| Parameter | 용도 |
| --- | --- |
| `/plady/agent-platform/<env>/n8n-encryption-key` | n8n credential 암호화 키. 없으면 배포 스크립트가 n8n 프로필을 켜지 않는다. **분실 시 저장된 credential 전부 무효** |
| `/plady/agent-platform/<env>/webex-webhook-secret` | Webex 웹훅 HMAC secret. 등록 워크플로가 Webex 에 보내고, ingest 워크플로가 검증에 쓴다 |

`scripts/ec2-deploy.sh` 가 둘을 읽어 `.env.ec2` 에 `N8N_ENCRYPTION_KEY` / `WEBEX_WEBHOOK_SECRET` 로 쓴다. 워크플로가 읽는 나머지 값(`LLM_WIKI_MCP_BEARER_TOKEN`, `HERMES_API_KEY`, `WIKI_SLACK_WEBHOOK_URL`)은 이미 `.env.ec2` 에 있는 값을 컨테이너 env 로 넘긴 것이다.

## 🙋 사람이 한 번 해야 하는 일

1. **Webex Integration 만들기** — [developer.webex.com](https://developer.webex.com/my-apps) → Create a New App → Integration.
   - Redirect URI: `https://n8n.agent.plady.io/rest/oauth2-credential/callback`
   - Scopes: `meeting:transcripts_read`, `meeting:schedules_read`, `spark:kms`. 조직 전체 회의를 받으려면(권장) 관리자 계정으로 `spark-admin:meeting_transcripts_read`, `spark-admin:meeting_schedules_read` 도 추가하고 `.env.ec2` 의 `WEBEX_WEBHOOK_OWNED_BY=org` 로 둔다(기본 `creator` = 인증한 사람이 호스트인 회의만).
   - Client ID / Client Secret 은 다음 단계에서 n8n 에만 넣는다. 레포·Linear·Slack 에 남기지 않는다.
2. **n8n 첫 로그인** — `https://n8n.agent.plady.io` → 팀 비밀번호(wiki 와 동일) → n8n owner 계정 생성(강한 비밀번호, 팀 비밀번호 관리자에 보관).
3. **OAuth2 credential** — Credentials → New → *OAuth2 API* (generic), 이름 `Webex OAuth2`:
   - Grant Type `Authorization Code`, Authorization URL `https://webexapis.com/v1/authorize`, Access Token URL `https://webexapis.com/v1/access_token`, Scope 는 1번과 동일(공백 구분), Authentication `Body`.
   - Client ID/Secret 입력 → **Connect my account** → Webex 동의. (토큰 갱신은 n8n 이 한다.)
4. **credential 연결** — 워크플로 `webex-transcript-ingest` 의 HTTP 노드 2개(`Get meeting`, `Download transcript`) 와 `webex-register-webhook` 의 HTTP 노드 2개에 `Webex OAuth2` 선택 → Save. (import 는 credential 을 연결하지 못한다. 이후 재배포 import 로 정의가 덮여도 DB 의 연결은 유지된다 — 안 되면 다시 선택.)
5. **웹훅 등록** — `webex-register-webhook` 을 한 번 실행(Execute workflow). 이미 같은 targetUrl 이 있으면 건너뛴다. Webex 쪽 결과는 `List existing webhooks` 노드 출력에서 확인.
6. **확인** — 녹화+Webex Assistant(또는 자막)를 켠 짧은 회의를 하나 끝낸다(transcript 는 녹화가 켜져 있어야 생긴다). 몇 분 뒤 `_wiki-alert` 에 archive 커밋 알림, 이어서 knowledge 커밋 알림(또는 실패 알림)이 온다. n8n Executions 에서 각 노드 출력을 볼 수 있다.

## 로컬 검증 (Webex 계정·모델 없이)

```bash
# 1) 스텁: Webex API + Hermes 흉내 (transcript 고정, 초안은 프롬프트에서 유도)
scripts/webex-ingest-stub.py --port 18790 --transcript fixtures/webex-sample.txt --title "데일리 스크럼"

# 2) 로컬 스택 — n8n 이 스텁을 보도록
MCP_BEARER_TOKEN=local HERMES_API_SERVER_KEY=stub WEBEX_WEBHOOK_SECRET=s \
WEBEX_API_BASE=http://host.docker.internal:18790 HERMES_API_URL=http://host.docker.internal:18790 \
docker compose --profile n8n up -d llm-wiki wiki-auth mcp-proxy n8n
# HTTP 노드의 authentication 을 뺀 사본을 import (스텁은 인증을 보지 않는다)
docker compose --profile n8n run --rm -v "$PWD/n8n/workflows:/w:ro" n8n import:workflow --separate --input=/w
docker compose --profile n8n run --rm n8n update:workflow --id=webex-transcript-ingest --active=true && docker compose restart n8n

# 3) 서명된 가짜 이벤트
scripts/webex-ingest-stub.py --fire http://localhost:5678/webhook/webex-transcript --secret s
scripts/webex-ingest-stub.py --fire http://localhost:5678/webhook/webex-transcript --secret s --bad-signature   # 거부돼야 한다
git -C wiki-workspace log --oneline -3   # archive(webex) + ingest(knowledge) 커밋
```

로컬 `wiki-workspace` 에 테스트 커밋이 남으니 끝나면 `git reset --hard origin/main` 으로 돌린다.

## 운영 메모

- **사이징**: n8n + 태스크 러너 ≈ 400 MB. t3.small 에 hermes·hugo·GHA 러너까지 얹혀 있어 스왑에 기대게 된다. 컴파일이 자주 실패하거나 느리면 t3.medium 으로 (terraform `instance_type` 도 같이).
- **컴파일 품질**: 초안은 `wiki_apply` 가 검증한다(source 페이지의 `raw_source_path`, topic 실제 변경, 규칙 위반). 실패는 Slack 알림으로 사람/에이전트에게 넘어가고 원문은 이미 보관돼 있어 잃는 것이 없다.
- **비밀값 회전**: `webex-webhook-secret` 을 바꾸면 Webex 웹훅을 삭제하고 등록 워크플로를 다시 실행한다. `n8n-encryption-key` 는 회전하지 않는다(credential 재입력 필요).
- **Hermes 도구 목록**: 이 작업에서 읽기 전용 도구 5개(`wiki_rules`, `wiki_catalog`, `wiki_recent`, `wiki_context`, `wiki_ingest_plan`)를 Hermes include 에 추가했다(레지스트리 `allow`). 쓰기 도구는 여전히 미노출.
