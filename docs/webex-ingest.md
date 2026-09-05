# 회의 → 위키 자동 ingest (n8n: Webex transcript · Slack 허들 AI 노트)

회의가 끝나면 n8n 이 원문을 위키에 **보관**하고, Hermes 가 만든 초안으로 **컴파일**까지 시도한다. 앞단(수집)은 소스별 워크플로, 뒤단(보관→계획→초안→커밋)은 공용 서브워크플로 `wiki-ingest-raw` 하나다. [`meeting-ingest.md`](meeting-ingest.md) 의 v1 경로이자 [`n8n-placeholder.md`](n8n-placeholder.md) 가 예약해 두던 자리의 실제 런타임이다.

| 소스 | 앞단 워크플로 | 트리거 | 원문 |
| --- | --- | --- | --- |
| Webex | `webex-transcript-ingest` | Webex 웹훅 `meetingTranscripts/created` | transcript(txt) |
| Slack 허들 | `slack-huddle-notes-ingest` | Slack Events API `message` (허들 AI 노트 캔버스가 붙은 메시지) | 캔버스 본문(요약+transcript) |

워크플로 JSON 은 손으로 고치지 않는다: 노드 코드는 [`n8n/src/*.js`](../n8n/src/), `python3 n8n/build.py` 가 [`n8n/workflows/*.json`](../n8n/workflows/) 을 생성한다. 둘 다 커밋.

## 흐름

```
Webex  ──(webhook meetingTranscripts/created, X-Spark-Signature)──▶  n8n  https://n8n.agent.plady.io/webhook/webex-transcript
                                                                     │
        1. HMAC-SHA1 검증 (raw body, WEBEX_WEBHOOK_SECRET)          │
        2. GET /v1/meetings/{id}, GET /v1/meetingTranscripts/{id}/download?format=txt   (Webex OAuth2 credential)
        ── 여기까지 앞단. 아래는 wiki-ingest-raw (Execute Workflow) ──
        3. wiki_apply mode=archive → raw/meetings/webex-<날짜>-<제목>          (결정적, 항상)
        4. wiki_ingest_plan + wiki_rules + 후보 페이지 읽기 → Hermes /v1/chat/completions 에 초안 요청
        5. 초안(JSON: sources/ 1개 + topics/people 수정본)을 wiki_apply mode=knowledge, expected_head 로 커밋   (best effort)
        6. 실패 시 _wiki-alert 에 "원문은 보관됨, ingest 마무리 요청" 알림 (성공 알림은 wiki-data-sync 가 커밋 기준으로 보냄)

Slack  ──(Events API POST, X-Slack-Signature)──▶  n8n  https://n8n.agent.plady.io/webhook/slack-events
        1. HMAC-SHA256 검증(raw body + timestamp, 5분 replay 창), url_verification challenge 즉시 응답
        2. `message`(또는 message_changed) 에 filetype quip(캔버스) 파일이 있고 제목이 "Huddle notes/허들 노트" 인 것만 통과
        3. files.info + conversations.info + 캔버스 다운로드(HTML → 텍스트) → raw/meetings/slack-huddle-<날짜>-<채널>-<id>
        4~6. 위와 같은 wiki-ingest-raw
```

- **쓰기는 n8n 만 한다.** Hermes 는 여전히 읽기 도구만 가진다(레지스트리 `approve` tier 미노출). 모델은 초안만 내고, 검증·커밋은 `wiki_apply` 트랜잭션이 한다. "쓰기는 승인된 경로 뒤에서만" 이라는 계약을 코드가 지킨다.
- **멱등**: Webex 재전송, Slack 의 message_changed 연타, 컴파일 실패 후 재실행 — 이미 보관된 원문은 건너뛰고(`already archived`) 이미 source 페이지가 있으면 컴파일도 건너뛴다(`already compiled`).
- **n8n 2.x 주의**: 서브워크플로 `wiki-ingest-raw` 도 **활성(published)** 이어야 호출된다("Workflow is not active and cannot be executed"). 배포 스크립트가 셋 다 활성화한다.
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
| `/plady/agent-platform/<env>/slack-ingest-signing-secret` | Slack 수집 앱의 Signing Secret. Events API 요청 서명 검증 |
| `/plady/agent-platform/<env>/slack-ingest-bot-token` | Slack 수집 앱의 Bot User OAuth Token(`xoxb-…`). files.info·캔버스 다운로드·conversations.info |

`scripts/ec2-deploy.sh` 가 넷을 읽어 `.env.ec2` 에 `N8N_ENCRYPTION_KEY` / `WEBEX_WEBHOOK_SECRET` / `SLACK_INGEST_SIGNING_SECRET` / `SLACK_INGEST_BOT_TOKEN` 으로 쓴다. 워크플로가 읽는 나머지 값(`LLM_WIKI_MCP_BEARER_TOKEN`, `HERMES_API_KEY`, `WIKI_SLACK_WEBHOOK_URL`)은 이미 `.env.ec2` 에 있는 값을 컨테이너 env 로 넘긴 것이다.

## 🙋 사람이 한 번 해야 하는 일

1. **Webex Integration 만들기** — [developer.webex.com](https://developer.webex.com/my-apps) → Create a New App → Integration.
   - Redirect URI: `https://n8n.agent.plady.io/rest/oauth2-credential/callback`
   - Scopes(포털에서 체크): `meeting:transcripts_read`, `meeting:schedules_read`. 조직 전체 회의를 받으려면(권장) 관리자 계정으로 `spark-admin:meeting_transcripts_read`, `spark-admin:meeting_schedules_read` 도 추가하고 `.env.ec2` 의 `WEBEX_WEBHOOK_OWNED_BY=org` 로 둔다(기본 `creator` = 인증한 사람이 호스트인 회의만).
   - `spark:kms` 는 포털 목록에 **없다**. Webex 가 모든 Integration 에 자동으로 붙이는 스코프라 체크할 수 없고, 저장 뒤 상세 페이지의 예시 OAuth URL 에 들어 있다. 다음 단계의 n8n Scope 문자열에만 직접 넣는다.
   - Client ID / Client Secret 은 다음 단계에서 n8n 에만 넣는다. 레포·Linear·Slack 에 남기지 않는다.
2. **n8n 첫 로그인** — `https://n8n.agent.plady.io` → 팀 비밀번호(wiki 와 동일) → n8n owner 계정 생성(강한 비밀번호, 팀 비밀번호 관리자에 보관).
3. **OAuth2 credential** — generic 타입은 Credentials 페이지 목록에 안 뜬다. 워크플로 `webex-transcript-ingest` → **Get meeting** 노드 → "Credential for OAuth2 API" 드롭다운 → **+ Create new credential** 로 만든다(Scope 칸이 있는 폼). 이름 `Webex OAuth2`.
   ⚠️ n8n 내장 **"Cisco Webex OAuth2 API"** 는 쓰지 않는다: 스코프가 숨겨진 고정값(messaging 11개)이라 Integration 과 안 맞아 `invalid_scope` 가 나고, 맞춰도 `meeting:transcripts_read` 가 없어 transcript 를 못 받는다.
   - Grant Type `Authorization Code`, Authorization URL `https://webexapis.com/v1/authorize`, Access Token URL `https://webexapis.com/v1/access_token`, Authentication `Body`.
   - Scope(공백 구분): 1번에서 체크한 것 + `spark:kms`. 예: `spark:kms meeting:transcripts_read meeting:schedules_read` (admin 스코프를 켰다면 그것도). 포털 상세 페이지의 예시 OAuth URL 에 있는 `scope=` 값을 그대로 옮기면 정확하다.
   - Client ID/Secret 입력 → **Connect my account** → Webex 동의. (토큰 갱신은 n8n 이 한다.)
4. **credential 연결** — 만든 자리(`Get meeting`)는 자동 연결. 나머지 HTTP 노드 3개(`Download transcript`, `webex-register-webhook` 의 `List existing webhooks`·`Create webhook`) 드롭다운에서 `Webex OAuth2` 선택 → 각 워크플로 Save. (import 는 credential 을 연결하지 못한다. 이후 재배포 import 로 정의가 덮여도 DB 의 연결은 유지된다 — 안 되면 다시 선택.)
5. **웹훅 등록** — `webex-register-webhook` 을 한 번 실행(Execute workflow). 이미 같은 targetUrl 이 있으면 건너뛴다. Webex 쪽 결과는 `List existing webhooks` 노드 출력에서 확인.
6. **확인** — 녹화+Webex Assistant(또는 자막)를 켠 짧은 회의를 하나 끝낸다(transcript 는 녹화가 켜져 있어야 생긴다). 몇 분 뒤 `_wiki-alert` 에 archive 커밋 알림, 이어서 knowledge 커밋 알림(또는 실패 알림)이 온다. n8n Executions 에서 각 노드 출력을 볼 수 있다.


## 🙋 Slack 허들 노트 — 사람이 한 번 해야 하는 일

전제: 워크스페이스에 Slack AI 가 있어 허들이 끝나면 "Huddle notes" 캔버스가 채널 스레드에 자동으로 올라온다. Hermes Slack 앱은 Socket Mode 라 Events API Request URL 을 쓸 수 없으므로 **수집 전용 앱을 하나 더** 만든다.

1. **Slack 앱 생성** — [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch → 이름 `plady-wiki-ingest`, 워크스페이스 선택.
2. **OAuth & Permissions** → Bot Token Scopes: `channels:history`, `groups:history`, `channels:read`, `groups:read`, `files:read`. → **Install to Workspace** → `Bot User OAuth Token`(`xoxb-…`) 확인.
3. **Basic Information** → App Credentials → `Signing Secret` 확인.
4. **SSM 에 넣기**(값은 본인 터미널에서만; 여기 붙이지 않는다):
   ```bash
   aws ssm put-parameter --profile plady-service --region ap-northeast-2 --type SecureString \
     --name /plady/agent-platform/dev/slack-ingest-signing-secret --value '<Signing Secret>'
   aws ssm put-parameter --profile plady-service --region ap-northeast-2 --type SecureString \
     --name /plady/agent-platform/dev/slack-ingest-bot-token --value '<xoxb-…>'
   ```
5. **재배포** — `gh workflow run deploy-agent-platform.yml` (Actions 탭 → Deploy → Run workflow 도 같다). 배포 로그에 `slack ingest app present` 가 보여야 한다.
6. **Event Subscriptions** → Enable → Request URL `https://n8n.agent.plady.io/webhook/slack-events` → Slack 이 challenge 를 보내고 워크플로가 서명을 검증해 응답하면 ✅ Verified. (5번 전에 하면 서명 secret 이 없어 실패한다.) → Subscribe to bot events: `message.channels`, `message.groups` → Save Changes → 앱 재설치 요청이 뜨면 Reinstall.
7. **채널 초대** — 허들을 하는 채널마다 `/invite @plady-wiki-ingest`. 초대된 채널의 메시지만 이벤트로 온다.
8. **확인** — 허들을 하나 하고 끝낸다. Slack 이 노트 캔버스를 올리면 n8n Executions 에 `slack-huddle-notes-ingest` 가 생기고(3분 대기 포함), `_wiki-alert` 에 `archive(slack-huddle): …` 알림이 온다. **실행이 아예 안 생기면** Event Subscriptions 에 bot events 가 저장되지 않은 것이다 — 봇이 채널에 있어도 `message.groups`/`message.channels` 구독이 없으면 Slack 은 아무것도 보내지 않는다(2026-09-05 첫 시도가 이 경우였다: URL 검증 이벤트만 도착). 캔버스 제목이 "Huddle notes"/"허들 노트" 가 아닌 워크스페이스면 `.env.ec2` 에 `SLACK_INGEST_ANY_CANVAS=true` 를 두고(compose 의 n8n env 에 추가) 재배포하면 채널에 공유되는 모든 캔버스를 받는다 — 첫 실행의 `Verify & classify` 출력에 `why` 로 왜 걸렀는지 남는다.

### 실제로 관찰된 모양 (2026-09-05, #proj-moimyeon, 봇 토큰으로 conversations.history 조회)

- 허들이 시작되면 Slack 이 채널에 **`subtype: huddle_thread`, `user: USLACKBOT`** 메시지를 하나 만든다(허들 스레드 루트). `room.date_end` 가 비어 있으면 진행 중.
- 끝나면 그 메시지에 캔버스 파일이 붙는다: `files[0].filetype = "quip"`, 제목 `":headphones: Huddle notes: 9/5/26 in <#C…>"` (한국어 워크스페이스 표기: `"허들 메모: 26/9/4 채널: …"`). `files.info` 에는 `is_huddle_canvas: true`, `huddle_transcript_file_id` 가 있다.
- 캔버스 다운로드(`url_private_download`, Bearer 봇 토큰)는 **HTML**(`<div class="quip-canvas-content">…`) → 워크플로가 태그를 벗겨 텍스트로 만든다. 내용: 참석자, Summary(짧은 허들이면 "Not enough to summarize"), transcript 파일 링크.
- **transcript 파일**(`filetype: huddle_transcript`, mimetype `application/vnd.slack-huddle-transcript`)은 봇 토큰으로 다운로드하면 302 → **403**. 즉 현재 원문은 Slack AI 가 쓴 노트(요약·액션 아이템)이고 발화 전문은 아니다. 워크플로는 transcript 를 받을 수 있으면 `## Transcript` 로 덧붙이고, 못 받으면 조용히 넘어간다. (사람 토큰이나 다른 스코프로 열리는지는 후속 조사.)
- 그래서 워크플로는 `Is huddle notes` 뒤에 **3분 Wait** 를 둔다: 캔버스는 허들 종료 직후 붙지만 AI 노트는 그 뒤로도 채워진다. raw 는 create-only 라 반쯤 쓰인 캔버스를 보관하면 되돌릴 수 없다.
- 팀원이 같은 캔버스를 다시 공유하는 메시지(예: `@Hermes Ingest 해줘 F0…`)도 같은 캔버스 id 로 들어오므로 `already archived` 로 끝난다.

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

# 3) 서명된 가짜 이벤트 (Webex / Slack)
scripts/webex-ingest-stub.py --fire http://localhost:5678/webhook/webex-transcript --secret s
scripts/webex-ingest-stub.py --fire http://localhost:5678/webhook/webex-transcript --secret s --bad-signature   # 거부돼야 한다
SLACK_INGEST_SIGNING_SECRET=k SLACK_API_BASE=http://host.docker.internal:18790/api   # n8n env 에 추가해 띄운 경우
scripts/webex-ingest-stub.py --fire-slack-challenge http://localhost:5678/webhook/slack-events --signing-secret k   # challenge 에코
scripts/webex-ingest-stub.py --fire-slack http://localhost:5678/webhook/slack-events --signing-secret k              # archive(slack-huddle)
git -C wiki-workspace log --oneline -3   # archive(webex) + ingest(knowledge) 커밋
```

로컬 `wiki-workspace` 에 테스트 커밋이 남으니 끝나면 `git reset --hard origin/main` 으로 돌린다.

## 운영 메모

- **사이징**: n8n + 태스크 러너 ≈ 400 MB. t3.small 에 hermes·hugo·GHA 러너까지 얹혀 있어 스왑에 기대게 된다. 컴파일이 자주 실패하거나 느리면 t3.medium 으로 (terraform `instance_type` 도 같이).
- **컴파일 품질**: 초안은 `wiki_apply` 가 검증한다(source 페이지의 `raw_source_path`, topic 실제 변경, 규칙 위반). 실패는 Slack 알림으로 사람/에이전트에게 넘어가고 원문은 이미 보관돼 있어 잃는 것이 없다.
- **비밀값 회전**: `webex-webhook-secret` 을 바꾸면 Webex 웹훅을 삭제하고 등록 워크플로를 다시 실행한다. `n8n-encryption-key` 는 회전하지 않는다(credential 재입력 필요).
- **Hermes 도구 목록**: 이 작업에서 읽기 전용 도구 5개(`wiki_rules`, `wiki_catalog`, `wiki_recent`, `wiki_context`, `wiki_ingest_plan`)를 Hermes include 에 추가했다(레지스트리 `allow`). 쓰기 도구는 여전히 미노출.
