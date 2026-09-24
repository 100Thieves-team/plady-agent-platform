# QA 플랫폼 — Hermes 작업 진행 현황을 SSE 로 보여 주기 (설계)

> 상태: **구현됨 (2026-09-23)** — 사용자 요청 "Hermes 를 호출하는 기능이 블로킹되면 제대로 되고 있는지 모른다, SSE 로 진행 현황을 받자". 검토 답(§7)을 받아 구현했다. 구현 결과는 §8.
> 관련: [qa-platform-hermes.md](qa-platform-hermes.md)(Hermes 연동), `qa/hermes.py`, `qa/drafts.py`.

## 1. 지금

Hermes 를 부르는 기능 다섯 개 중 넷이 요청 하나로 끝까지 기다린다. 버튼을 누르면 페이지가 최대 3분 멈춰 있다가 결과 화면으로 넘어간다.

| 기능 | 화면 | 호출 | 기다리는 시간 |
|---|---|---|---|
| 고른 테스트 조건으로 스크립트 초안 생성 | 테스트 조건 목록 | `drafts.generate` → `hermes.chat` | 수십 초~3분 |
| PRD 절에서 수동 작성 테스트 조건 제안 | 테스트 조건 목록 | `drafts.propose_manual_tc` → `hermes.chat` | 수십 초~3분 |
| 바뀐 테스트 조건에 맞게 Hermes 가 고치기 | 스크립트 상세 | `drafts.revise` → `hermes.chat` | 수십 초~3분 |
| Hermes 실패 분석 | 실행 결과 | `hermes.triage` → `hermes.chat` | 수십 초 |
| Hermes 와 이야기 | 대화 | `hermes.stream_respond` | **이미 SSE** |

- 기다리는 동안 보이는 건 버튼 글자 "Hermes 가 읽는 중…" 뿐이다. 멈춘 건지, 오래 걸리는 건지, 실패한 건지 알 수 없다.
- 페이지를 닫거나 새로 고치면 결과는 서버에 생기지만, 어디서 찾는지 모른다.
- 프록시·브라우저 타임아웃에 걸리면 서버는 계속 일하는데 화면은 오류로 끝난다.

## 2. 바꾼 뒤

버튼을 누르면 **Hermes 작업**이 하나 생기고, 화면은 바로 진행 현황 카드로 바뀐다. 카드는 SSE 로 단계를 받아 갱신한다.

```
Hermes 작업 j-1a2b3c · 스크립트 초안 생성 · bebe · 00:47 경과
 ✅ 근거 모으기     TC 3건 · OpenAPI 4개 API · PRD 2절 (프롬프트 18,240자)
 ✅ Hermes 에게 보냄
 ⏳ Hermes 가 쓰는 중   2,310자 받음 · 마지막 수신 3초 전
 ○ 검증
 ○ 끝
 [그만두기]
```

끝나면 결과를 보여 주고 링크를 건다. 예를 들어 "초안 2건 생성, 1건은 검증에서 거절됨(사유)" 과 초안 링크다. 실패하면 어느 단계에서 왜 멈췄는지 보여 준다.

### 2.1 단계

네 기능이 같은 단계를 쓴다. 기능마다 이름만 조금 다르다.

| 단계 | 내용 | 진행 정보 |
|---|---|---|
| 대기 | 앞 작업이 끝나기를 기다림 (§4.3) | 앞에 몇 건 |
| 근거 모으기 | 테스트 조건·OpenAPI·PRD 절을 모아 프롬프트를 만든다 | 건수, 프롬프트 글자 수 |
| Hermes 에게 보냄 | 요청 전송, 첫 응답 전 | 경과 시간 |
| Hermes 가 쓰는 중 | 응답을 스트리밍으로 받는다 | 받은 글자 수, 마지막 수신 뒤 경과 시간. 실패 분석은 받은 글을 그대로 흘려 보여 준다 |
| 검증 | 결정론 검증(스크립트 초안·수동 테스트 조건) | 통과·거절 건수 |
| 끝 · 실패 · 그만둠 | 결과 저장, 링크 | 초안 id, 오류 메시지 |

- **결정 (2026-09-23 사용자 "yaml")**: 스크립트 초안도 Hermes 가 쓰는 YAML 을 받는 대로 보여 준다. 카드에 "검증 전이라 틀린 곳이 있을 수 있다" 를 적는다.
- 실패 분석은 짧은 문장이고 검증 단계가 없으니 받는 대로 보여 준다.

## 3. 구조

```
[버튼] POST /drafts/generate 등  ─→  작업 만들기(jobs 행) + 스레드 시작 ─→  303 /jobs/{id}
                                                                          │
브라우저  GET /jobs/{id}  (진행 현황 화면)                                  │
          └ EventSource /api/jobs/{id}/events  ←── 작업 스레드가 jobs 행과 메모리 상태를 갱신
```

### 3.1 작업 저장

- sqlite 에 `hermes_jobs` 표를 둔다. 열은 id, kind, operator, status, stage, progress(JSON), result(JSON), error, 만든·시작·끝난 시각, 입력 요약.
- 메모리에도 같은 상태를 두고 SSE 는 메모리를 읽는다. 표는 새로 고침·재접속·서버 재시작 뒤 결과를 찾기 위한 것이다.
- 서버가 재시작되면 끝나지 않은 작업은 "서버 재시작으로 중단" 으로 표시한다. 자동으로 다시 돌리지 않는다. 실행 시작은 언제나 사람이 한다.

### 3.2 Hermes 스트리밍

- `hermes.chat` 에 스트리밍 판을 더한다. chat completions 를 `stream: true` 로 보내고 델타가 올 때마다 콜백을 부른다.
- 호출 쪽(`drafts.generate` 등)은 지금처럼 전체 글을 받아 처리한다. 콜백으로 진행만 알린다.
- **구현**: 배포된 hermes-agent 에서 이미 쓰고 있는 `/v1/responses` 스트리밍(대화 화면과 같은 경로)을 쓴다. chat completions 스트리밍은 확인된 적이 없어 쓰지 않았다. `hermes.ask_stream()` 이 system 을 `instructions` 로, 근거를 `input` 으로 보낸다.

### 3.3 SSE

- `GET /api/jobs/{id}/events`. 기존 대화 SSE 도우미(`_sse_start`, `_sse`)를 쓴다.
- 이벤트는 `stage`(단계 바뀜), `progress`(글자 수·건수), `text`(실패 분석의 글 조각), `done`, `error` 다.
- 연결하자마자 현재 상태 전체를 한 번 보낸다. 그래서 새로 고치거나 다시 연결해도 이어서 보인다.
- 15초마다 keepalive 를 보낸다. 끝난 작업에 연결하면 `done` 이나 `error` 하나를 보내고 닫는다.
- JavaScript 가 꺼져 있으면 진행 현황 화면이 5초마다 새로 고침한다.

### 3.4 화면

- **진행 현황 화면** `/jobs/{id}`: 위 카드. 끝나면 결과 링크로 자동 이동하지 않고 링크만 보여 준다. 여러 건이 나왔을 수 있어서다.
- **실패 분석**은 실행 결과 화면 안에서 카드로 바로 흐른다. 따로 이동하지 않는다.
- **초안 목록** 위에 "진행 중인 Hermes 작업" 줄을 둔다. 페이지를 닫았다가 돌아와도 찾을 수 있다.
- 목록 화면 `/jobs`: 최근 작업, 담당자·종류·결과·걸린 시간. 감사 로그와 별도로 Hermes 가 얼마나 걸리는지 보는 용도다.

## 4. 규칙

### 4.1 사람 트리거
작업은 사람이 버튼을 눌렀을 때만 생긴다. 재시도도 사람이 [다시 시도] 를 눌러야 한다.

### 4.2 감사 로그
지금처럼 시작과 끝을 남긴다. `draft.generate` 등 기존 action 을 그대로 쓰고, detail 에 job id 와 걸린 시간을 더한다. 그만두기는 `hermes_job.cancel` 로 남긴다.

### 4.3 동시에 몇 개
Hermes 는 한 대다. 동시에 도는 작업은 **2건**까지로 하고 나머지는 대기열에 넣는다. 대화 위젯은 이 제한 밖이다. 대화는 사람이 보고 있는 짧은 턴이라서다.

### 4.4 그만두기
- 대기 중이면 바로 뺀다.
- 도는 중이면 Hermes 스트림 연결을 끊고 "그만둠" 으로 표시한다. Hermes 서버 쪽 처리가 즉시 멈추는지는 보장하지 않는다.
- 그만둔 작업의 결과는 저장하지 않는다.

### 4.5 타임아웃
작업 하나에 300초(`QA_JOB_TIMEOUT`). 진행 카드에 한도를 보여 준다. "마지막 수신 뒤 60초" 동안 아무것도 안 오면 멈춘 것으로 보고 실패로 끝낸다.

## 5. 구현 순서

| 단계 | 내용 |
|---|---|
| S1 | dev hermes-agent 스트리밍 지원 확인, `hermes.chat_stream` 추가, `hermes_jobs` 표와 작업 실행기, SSE 경로, 진행 현황 화면 |
| S2 | 네 기능을 작업으로 옮긴다. 초안 생성 · 수동 테스트 조건 제안 · 고치기는 진행 현황 화면으로, 실패 분석은 제자리 카드로 |
| S3 | 초안 목록의 진행 중 줄, `/jobs` 목록, 그만두기 |

사람 작업은 없다. 새 비밀값도 필요 없다.

## 6. 하지 않는 것

- 작업 끝날 때 Slack 알림. 사용자가 알림은 필요 없다고 했다(2026-09-22, API 문서 갱신 때와 같은 기준).
- 실패한 작업 자동 재시도.

## 7. 검토 질문과 답 (2026-09-23)

1. 초안 YAML 을 쓰는 도중에 보여 줄까? → **"yaml"**: 보여 준다(§2.1).
2. 동시 작업 2건 제한과 대기열 → 답 없음. 설계대로 2건(`QA_JOB_CONCURRENCY`)으로 두었다.
3. 폼 편집과 무엇을 먼저? → **"둘 다 같이 구현해"**.

## 8. 구현 결과 (2026-09-23)

| 부분 | 어디 |
|---|---|
| 작업 관리(단계·글·대기·그만두기·재시작 중단) | `qa/jobs.py` `Jobs`·`Job` |
| 스트리밍 ask | `qa/hermes.py` `ask_stream()`, `Canceled`. `drafts.generate`·`revise`·`propose_manual_tc`·`hermes.triage` 가 `ask` 를 받는다(없으면 기존 동기 호출 — MCP 도구·JSON API 는 그대로) |
| 표 | `hermes_jobs`(id, kind, operator, label, status, stage, info, result, error, text, back, 시각) |
| 라우트 | `GET /jobs` · `GET /jobs/{id}` · `GET /api/jobs/{id}` · `GET /api/jobs/{id}/events`(SSE: `snapshot`·`state`·`text`·`end`, 15초 keepalive) · `POST /jobs/{id}/cancel` · `GET /static/jobs.js` |
| 바뀐 버튼 | 초안 생성·수동 테스트 조건 제안·고치기는 `/jobs/{id}` 로 간다. 실패 분석은 `X-QA-Job` 헤더로 작업 id 를 받아 제자리 카드로 흐르고, 끝나면 화면을 새로 고친다. `/api/…` JSON 경로는 예전처럼 끝까지 기다린다 |
| 설정 | `QA_JOB_CONCURRENCY`(2) · `QA_JOB_TIMEOUT`(300초) · `QA_JOB_STALL`(60초, Hermes keepalive 10초) |
| 감사 로그 | `hermes_job.start`(버튼을 누른 것) · `hermes_job.cancel` · 결과는 기존 `draft.generate`·`run.triage` 등(`run.triage` 는 detail 에 job id) |
| 테스트 | `tests/test_jobs.py` 13건 — SSE 파싱·그만두기·멈춤, 단계·글·결과·표, 대기와 그만두기, 재시작 중단, 초안 생성 작업, 실제 HTTP 로 SSE `snapshot → text → end`, 실패 분석 제자리 작업 |
