# QA 자동화 플랫폼 — 설계·런북 (MOI-483)

> 상태: **P0·P1 구현됨 (2026-09-21)** — 설계 2판을 사용자가 승인한 뒤 구현. 아래 §0~§13 은 설계, §14 는 구현 결과와 운영 절차.
> 이슈: [MOI-483 QA 자동화 플랫폼 구축](https://linear.app/100-thieves/issue/MOI-483/qa-자동화-플랫폼-구축)
> 플랫폼 계약 SSOT는 [`platform-contract.md`](platform-contract.md). 소스는 [`qa-platform/`](../qa-platform/README.md).
>
> 설계 결정 이력:
> - 1판(2026-09-20): 배포 훅 자동 실행 + 스케줄 자동 실행 제안.
> - 2판(2026-09-20, 사용자 결정): **실행을 시작하는 것은 언제나 사람이다.** 자동 트리거 전부 삭제. 감사 로그가 1급 자산. 배포 감지는 inbound webhook 대신 GitHub Actions 조회(읽기). Slack 은 `WIKI_SLACK_WEBHOOK_URL` 재사용. PR 프리뷰가 없으므로 검증 대상은 dev.

## 용어 (2026-09-22 화면 용어 정리)

화면은 일반 QA 용어를 쓴다. 이 문서와 설계 문서의 옛말은 아래처럼 읽는다. 코드 키(`run`, `case`, `catalog`, `covers`, `audit`, `operator`)는 그대로다.

| 화면 (지금) | 문서의 옛말 | 뜻 |
| --- | --- | --- |
| 테스트 조건 | 기준 · 카탈로그 · 테스트 조건 | 무엇을 확인해야 하는가 — SSOT·PRD·OpenAPI 에서 파생 |
| 테스트 스크립트 | 스크립트 | 테스트 조건을 확인하는 실행 단위(YAML, git 원본) |
| 검증하는 테스트 조건 | 덮는 테스트 조건 · covers | 스크립트가 확인한다고 선언한 테스트 조건 |
| 정합성 (정합 · 경고 · 불일치) | 대조 (OK · 경고 · 오류) | 스크립트 선언과 테스트 조건 목록·API 계약의 일치 검사 |
| 테스트 조건 변경 | 근거 변경 · 드리프트 | 검증하는 테스트 조건이 마지막 검토 이후 바뀜 |
| 자동화됨 · 미자동화 · 자동화 제외 | 덮음 · 미커버 · 제외 | 테스트 조건을 검증하는 스크립트 유무 |
| API 매핑 | 바인딩 | SSOT command·검사 ↔ OpenAPI operation·에러 코드 |
| 스펙 불일치 경고 | 카탈로그 경고 | 매핑이 가리키는 op·코드가 OpenAPI 에 없음 |
| 테스트 실행 · 실행 기록 | 런 | 사람이 돌린 한 번의 기록 |
| 실행 종류 | 트리거 | 배포 검증 · 스프린트 smoke · 릴리스 QA · 수동 실행 … |
| 검증 항목 (assertion) | 단언 | 단계별 응답 비교 조건 |
| 스크립트 초안 | 스크립트 초안 · 초안함 | 승인 전 YAML |
| 담당자 | 운영자 | 버튼을 누른 사람(자기 신고) |
| 감사 로그 | 활동 | events |
| API 호출 | 탐색기 | OpenAPI 로 요청 하나를 dev 에 보내 보는 화면 |
| Hermes 실패 분석 | Hermes 진단 | 실패한 스크립트의 원인 분류 |
| 위키에 보고서 게시 | 위키 발행 | wiki_apply 로 보고서 페이지 생성 |
| 비즈니스 규칙 · API 계약 · 수동 작성 | 정책 · 계약 · 서술 | 테스트 조건의 세 층 |
| Normal · Swagger 보기 | 호출 카드 · 요청 원문 보기 | 같은 요청을 입력 폼 / 실제로 나가는 요청 원문으로 보는 토글 (토스 용례) |
| 테스트 데이터 만들기 | 준비 작업 · setup | 여러 API 를 순서대로 호출하는 스크립트를 버튼 하나로 (suite `setup`, `inputs` · `outputs`) |
| 호출하는 스크립트 · 최근 호출 | 부르는 스크립트 · 최근 호출 | 어떤 API 를 호출하는 스크립트 · 그 API 를 호출한 단계 최신순 |
| 결과값 · 최근에 넣은 값 | outputs · 최근 값 | 테스트 데이터 만들기의 결과 · API 호출 입력칸이 브라우저에 기억한 값 |
| 이 API 에 해당하는 테스트 조건 | 걸린 테스트 조건 | API 계약 테스트 조건(operation) + API 매핑으로 이어진 비즈니스 규칙·수동 작성 테스트 조건 |

## 0. 한 줄 요약

dev 서버에 배포된 백엔드를 **OpenAPI 계약과 PRD/SSOT 근거로 검증**하고, **누가 언제 무엇을 검증했는지 남기는** 얇은 플랫폼.
실행 버튼은 사람이 누르고, 실행 자체는 결정론 러너가 하고, AI(Hermes)는 **스크립트 초안 생성과 실패 진단**만 맡는다.

## 1. 전제 — 조사로 확인한 사실

| 영역 | 사실 | 설계에 미치는 영향 |
| --- | --- | --- |
| 백엔드 배포 | `dev` push → CI → `deploy-aws` → ECS `https://api.dev.moimyeon.plady.io`. PR 프리뷰 환경 없음. `main` 승격은 `promote-live`(현재 vars 게이트로 비활성). | 검증 대상은 항상 **dev 배포분**이다. 플랫폼은 배포를 **감지만** 하고 실행하지 않는다. |
| API 계약 | `api-docs-pages` 워크플로가 REST Docs → `openapi3.yaml`을 GitHub Pages에 브랜치별 발행(dev/main). 오퍼레이션 diff Slack 알림 존재(MOI-484). 83 operations. | 스펙은 백엔드가 이미 발행 → 플랫폼은 **읽기만** 한다. 변경 operation 목록을 검증 범위 제안에 쓴다. |
| dev 인증 | `POST /v1/auth/dev-sessions {memberId}` → 만료 없는 토큰(local/dev 프로파일만, MOI-487). dev DB에 목데이터 회원 존재(`019db000-…-1001~1004`). | 테스트 계정(actor) = 고정 회원 UUID. Google OAuth 우회 불필요. |
| 응답 규약 | `{result: SUCCESS\|ERROR, data, error{code E####, message}}`. 에러 코드 정본은 `CoreErrorType`. | 단언은 status + `error.code` + JSON 경로 3종이면 충분. |
| LLM 위키 | PRD 정본 `raw/product/*.md`, `wiki/policy/_src/상태-SSOT.yaml`(gate/command/transition), `render_tests.py`가 SSOT에서 테스트 뼈대를 뽑음. MCP `wiki_content_read`/`wiki_apply`. | 스크립트 근거 = PRD § + SSOT gate id. 보고서는 `wiki_apply mode=generated`(`managed_by: harness`). |
| 백엔드 하네스 | DR-022: 레포 `qa-reviewer` = 머지 전 정적 diff 리뷰, **플랫폼 qa-engineer = 배포 후 런타임 검증(sanity/smoke)**. `docs/knowledge/qa-review.md`·`release-checklist.md`가 에이전트 중립 지식. | 이 플랫폼이 DR-022가 예약한 자리. 지식 문서를 그대로 소비한다(복제하지 않음). |
| 스프린트 | Linear 주간 사이클(일→일 KST, 현재 Cycle 9). | 사이클 단위로 "이번 스프린트 smoke 실행됨/안 됨"을 판정한다. |
| 플랫폼 관행 | compose 서비스 + Caddy host 라우팅 + wiki-auth 팀 세션 + SSM 이름 계약 + GHA→ECR→SSM 배포(97 KB 페이로드 한도). | 새 서비스도 같은 틀. 소스는 ECR 이미지로 배포. |
| 팀 세션의 한계 | wiki-auth는 **팀 공용 비밀번호** 한 개 → 세션에 개인 식별자가 없다. | "누가 눌렀나"는 인증으로 못 얻는다. 운영자를 **자기 신고**로 받고 그 사실을 명시한다(§6.2). |
| Hermes | `hermes-gateway:8642` OpenAI 호환 `/v1/chat/completions`, `gpt-5.5`, llm-wiki MCP 읽기 16종 + `wiki_apply`. | UI의 AI 호출은 **전부 Hermes**로. 플랫폼이 모델 키를 갖지 않는다. |
| 토스 교훈 | 스크립트 ↔ 런 분리, 런은 스냅샷 불변, Normal/Swagger 두 모드, AI 산출물은 검증 겹. | 그대로 채택. 실기기·시각 검증은 우리 범위 밖. |

## 2. 원칙

1. **실행의 시작은 사람이다.** 자동으로 도는 QA 런은 없다. 플랫폼은 대상·범위·근거를 준비해 두고, 버튼이 눌리기를 기다린다.
2. **모든 사람 행위는 이력으로 남는다.** 런 생성, 초안 승인/반려, 위키 발행, 릴리스 판정, 탐색기 전송 — 운영자·시각·대상이 감사 로그에 남고 UI에서 조회된다.
3. **판정은 결정론이다.** 통과·실패를 LLM이 정하지 않는다. AI는 초안을 쓰고 실패를 설명할 뿐이다.
4. **스크립트의 정본은 git이다.** DB는 실행 이력과 초안만 갖는다.
5. **과거 런은 불변이다.** 실행 시점의 스크립트 본문을 런에 박아 둔다.

## 3. 범위

**1차 범위(이 이슈)**
- HTTP API 레벨 QA — 대상 `dev`. 스크립트 실행·기록·UI·사람 트리거 4종(배포 검증 / 스프린트 smoke / 릴리스 QA / 임의 선택).
- 감사 로그와 조회 UI.
- Swagger 기반 수동 QA(탐색기).
- Hermes 연동: 스크립트 초안 생성(PRD+SSOT+OpenAPI 근거), 실패 진단.
- 기존 backend 지식 소비: `qa-review.md` 위험 신호, `release-checklist.md` 항목.

**비범위(명시적으로 뺀다)**
- 브라우저 E2E·시각 검증, 성능(k6·SLO), 실기기.
- **자동 트리거 일체** — 배포 훅 자동 실행, 크론 자동 실행, CI 게이트 차단.
- live 환경 쓰기 실행(읽기 전용 smoke는 후속 후보).
- 백엔드 레포 코드 수정 — 이 설계는 백엔드 레포에 아무 변경도 요구하지 않는다.
- 스크립트 편집기 UI(스크립트는 git YAML이 정본, UI는 초안까지만).

## 4. 기능 트리 (top-down)

```text
QA 플랫폼  qa.agent.plady.io  (팀 비밀번호 세션 뒤)
│
├─ 1. 스크립트 — 무엇을 검증하나            정본: git YAML (qa-platform/cases/)
│   ├─ 1.1 스위트  smoke(스프린트·릴리스) / sanity(배포 검증) / manual(탐색기 전용)
│   ├─ 1.2 스크립트 = HTTP 단계 열 + 기대(status·error.code·JSON 경로) + 변수 저장(save)
│   ├─ 1.3 근거 링크  PRD § · SSOT gate id · operationId  (선택 기준이자 추적 근거)
│   ├─ 1.4 테스트 계정(actor)  dev-sessions 토큰으로 얻는 고정 QA 회원 (qa-host / qa-guest)
│   └─ 1.5 초안  Hermes 생성 → 결정론 검증 → 탐색기로 확인 → 사람 승인 → YAML → PR
│
├─ 2. 검증할 거리 — 사람에게 보여주는 것    플랫폼은 읽기만 한다
│   ├─ 2.1 미검증 배포  GitHub Actions 조회로 dev 성공 배포 목록 → 런과 대조 → "미검증" 표시
│   ├─ 2.2 변경 범위  배포 SHA → PR → 변경 파일 → 도메인·operation → 권장 스크립트 집합
│   ├─ 2.3 스프린트 상태  현재 Linear 사이클에 smoke 런이 있는가 → 없으면 배지
│   └─ 2.4 스펙 드리프트  현재 스펙의 operation 중 어느 스크립트도 안 건드리는 것 목록(커버리지 공백)
│
├─ 3. 실행 — 사람이 누르면 그때            결정론 러너, AI 개입 없음
│   ├─ 3.1 트리거(전부 UI 버튼)
│   │     ① 배포 검증(sanity)  미검증 배포 옆 [검증] — 범위는 권장 집합, 사람이 조정 가능
│   │     ② 스프린트 smoke     [스프린트 smoke 실행]
│   │     ③ 릴리스 QA          [릴리스 검증] + release-checklist 체크 + 승격 판단 기록
│   │     ④ 임의 선택          스크립트/스위트 골라 실행
│   ├─ 3.2 운영자 확인  실행 전 운영자·대상·범위를 보여주고 확인 → 감사 로그 기록
│   ├─ 3.3 실행  스크립트 순차, 단계 실패 시 그 스크립트 중단, 런은 큐로 직렬화(dev 데이터 충돌 방지)
│   └─ 3.4 정리  스크립트가 만든 데이터는 스크립트가 닫는다(룸 생성 → 취소). 제목 접두 `[QA]`
│
├─ 4. 기록 — 증발하지 않게                sqlite, 볼륨 qa-data
│   ├─ 4.1 런  트리거·운영자·환경·SHA·PR·시각·판정 + 실행 시점 스크립트 스냅샷(해시+본문)
│   ├─ 4.2 단계 결과  요청/응답(Authorization 마스킹, 8 KB 절단)·단언 결과·소요
│   ├─ 4.3 감사 로그  모든 사람 행위(런 생성·초안 승인·위키 발행·릴리스 판정·탐색기 전송)
│   ├─ 4.4 알림  Slack(`WIKI_SLACK_WEBHOOK_URL`) — 런 시작·완료 요약 + 실패 스크립트 링크
│   └─ 4.5 위키 보고서  사람이 [위키에 발행]을 누를 때만 wiki/qa/ 에 generated 페이지
│
├─ 5. UI — 서버 렌더 HTML, 프레임워크 없음
│   ├─ 5.1 대시보드  미검증 배포 · 스프린트 상태 배지 · 최근 런 · 트리거 버튼 4종
│   ├─ 5.2 런 상세  스크립트·단계별 요청/응답/단언, [Hermes 진단] → 분류(버그 / 스크립트 노후 / 환경) + 근거
│   ├─ 5.3 스크립트  목록·상세(근거 링크, 마지막 판정 이력), 커버리지 공백
│   ├─ 5.4 탐색기(Swagger 모드)  operation 선택 → 스펙 예제 프리필 → actor 선택 → 전송 → [스크립트 단계로 저장]
│   ├─ 5.5 스크립트 초안  [도메인 초안 생성](Hermes) → 목록 → 승인/반려 → YAML 다운로드
│   ├─ 5.6 릴리스  릴리스 런 + release-checklist 항목 체크 + 승격 판단 기록
│   └─ 5.7 활동  감사 로그 조회(운영자·기간·행위 필터)
│
└─ 6. 연동
    ├─ 6.1 GitHub(읽기)  Actions 실행 목록(배포 감지) · PR 변경 파일(범위 제안) · Pages OpenAPI
    ├─ 6.2 백엔드 dev     실행 대상 · dev-sessions 토큰 발급
    ├─ 6.3 LLM 위키(MCP)  PRD·SSOT 읽기(초안 컨텍스트) · 보고서 쓰기(사람이 누를 때만)
    ├─ 6.4 Hermes         초안 생성 · 실패 진단 (플랫폼은 모델 키를 갖지 않음)
    ├─ 6.5 Slack          `WIKI_SLACK_WEBHOOK_URL` 재사용 → `_wiki-alert`
    └─ 6.6 Linear         현재 사이클 조회(스프린트 판정), 런 링크 코멘트는 후속
```

## 5. 연계도 — GitHub 코드베이스 · dev 서버 · LLM 위키 · QA 플랫폼

```text
            moimyeon-backend (GitHub, public)                plady-agent-platform (EC2, compose)
 ┌──────────────────────────────────────────┐        ┌──────────────────────────────────────────────────┐
 │ PR → dev 머지                            │        │  caddy ── qa.agent.plady.io ──▶ forward_auth      │
 │   ├─ CI(test) ─▶ deploy-aws ─▶ ECS dev   │        │            (wiki-auth 팀 세션)     │              │
 │   │      (성공 실행 기록)                 │        │                                    ▼              │
 │   └─ api-docs-pages ─▶ GitHub Pages      │        │   ┌───────────────────────────────────────────┐  │
 │        openapi3.yaml (dev/main)          │        │   │      qa-platform :8800                    │  │
 └───────┬──────────────────────┬───────────┘        │   │   UI(서버 렌더)  ◀── 팀원 브라우저         │  │
         │ ① Actions·PR 조회     │ ② 스펙 읽기        │   │        │  사람이 버튼을 누른다            │  │
         │    (읽기 전용)        │                    │   │        ▼                                  │  │
         └──────────────────────┴───────────────────▶│   │   runner(HTTP) ── sqlite qa-data          │  │
                                                     │   │        │      (런·단계·감사 로그)          │  │
 ┌──────────────────────────┐                        │   └────────┼──────────────────────────────────┘  │
 │ 백엔드 dev 서버 (ECS)      │◀── ③ 스크립트 실행 ──────┼────────────┤                                      │
 │ api.dev.moimyeon.plady.io │   (dev-sessions 토큰)  │            │                                      │
 └──────────────────────────┘                        │            ├─④ PRD·SSOT 읽기 ─▶ mcp-proxy:18765 ──▶ llm-wiki
 ┌──────────────────────────┐                        │            ├─⑤ 보고서 쓰기(사람이 누를 때만)      │   (team-wiki-v2)
 │ Slack  _wiki-alert       │◀── ⑦ 런 요약 ──────────┼────────────┤    wiki_apply mode=generated         │
 └──────────────────────────┘                        │            └─⑥ AI ─▶ hermes-gateway:8642          │
 ┌──────────────────────────┐                        │                 (gpt-5.5 · 위키 MCP 보유)          │
 │ Linear  현재 사이클 조회   │◀───────────────────────┼─────────────                                      │
 └──────────────────────────┘                        └──────────────────────────────────────────────────┘

   inbound 은 브라우저 하나뿐이다. 외부에서 이 플랫폼을 실행시킬 수 있는 경로는 없다.
```

- ① **읽기 전용 조회**다. 공개 레포라 토큰 없이 된다(미인증 60 req/h). 대시보드 렌더 시 60초 캐시로 가져오고, 토큰이 SSM에 있으면 그걸 쓴다.
- ② 스펙은 브랜치별 URL을 그대로 읽는다. 플랫폼이 스펙을 생성하거나 보관하지 않는다(캐시만).
- ③ 스크립트는 dev에만 쓴다. `[QA]` 접두·QA 전용 회원으로 사람 데이터와 분리한다.
- ④⑤ 위키 접근은 내부 `mcp-proxy` 경유(기존 bearer). 쓰기는 `generated` 모드 한 가지, 사람이 누를 때만.
- ⑥ Hermes는 이미 위키 MCP 도구를 갖고 있으므로, 초안 프롬프트에 PRD 본문을 넣어 주되 Hermes가 `wiki_context`로 보강할 수 있다.

## 6. 사람 트리거와 이력

### 6.1 트리거 흐름

```text
대시보드
  "미검증 배포 2건"
    ├ PR #128 fix(harness) … 09-20 17:31  dev  [검증]
    └ PR #127 feat(logging) … 09-20 16:50  dev  [검증]
         │
         │ 사람이 [검증] 클릭
         ▼
  확인 화면 — 실행 전에 무엇을 하는지 보여준다
    대상    https://api.dev.moimyeon.plady.io  @ 7c1d9ab (PR #127)
    범위    sanity 4건 (변경 파일 → logging·member 도메인)  [전체 sanity로 넓히기] [스크립트 직접 고르기]
    운영자  bebe ▾                                  ← 자기 신고. 쿠키에 기억한다
    [실행]  [취소]
         │
         ▼
  런 생성 → 감사 로그 기록 → Slack "bebe 가 PR #127 sanity 실행" → 실행 → 완료 요약
```

같은 모양으로 스프린트 smoke·릴리스 QA·임의 선택이 돈다. 확인 화면 없이 실행되는 경로는 없다.

### 6.2 "누가"를 어떻게 아는가 — 정직한 한계

wiki-auth는 팀 공용 비밀번호 하나로 세션을 준다. 세션에 개인 식별자가 없으므로 **운영자는 인증된 신원이 아니라 자기 신고**다. 확인 화면의 드롭다운(팀원 목록 `QA_OPERATORS`)에서 고르고 쿠키에 기억된다. 감사 로그에는 자기 신고 운영자와 함께 세션 id 해시·시각·IP를 남겨, 나중에 누가 무엇을 했는지 다투게 되면 대조할 재료는 남긴다.

이걸 진짜 신원으로 올리려면 wiki-auth에 개인 계정 개념이 필요하다 — 이 이슈 밖이고, 2인 팀에서 비용이 이득을 넘는다고 판단했다. 필요해지면 §11-4로 올린다.

### 6.3 감사 로그에 남는 행위

| 행위 | 남는 것 |
| --- | --- |
| `run.create` | 운영자, 트리거 종류, 대상 SHA/PR, 선택된 스크립트 목록과 선택 근거 |
| `run.cancel` | 운영자, 런 id, 진행 단계 |
| `draft.generate` / `draft.approve` / `draft.reject` | 운영자, 도메인, 초안 id, 반려 사유 |
| `wiki.publish` | 운영자, 런 id, 쓴 페이지 경로, 위키 커밋 sha |
| `release.decide` | 운영자, 릴리스 런 id, 체크리스트 결과, 승격 판단(go/no-go)과 사유 |
| `explorer.send` | 운영자, operation, 테스트 계정, 응답 status |

`/activity`에서 운영자·기간·행위로 필터해 본다. 보존은 런 기록과 같다(무기한, 볼륨).

## 7. 워크플로우

### 7.1 개발 워크플로우에 끼는 지점

```text
이슈(MOI) → 구현(하네스: requirement-implementation, qa-reviewer 정적 리뷰) → PR → 리뷰·머지(dev)
   → CI → deploy-aws → ECS dev 반영
   → [QA 플랫폼] 대시보드에 "미검증 배포"로 뜸           ← 여기까지는 자동
   → 사람이 [검증] 클릭 → 확인 → 실행                    ← 여기부터 사람
   → Slack: "bebe 가 PR #128 sanity 실행 → 6/6 통과"
   → 실패면: 런 상세에서 [Hermes 진단] → 버그면 Linear 이슈, 스크립트 노후면 스크립트 PR
```

개발자가 PR·머지 절차에서 새로 하는 일은 없다. 배포 후 대시보드를 열어 검증을 누르는 것이 추가되는 유일한 동작이다.

### 7.2 QA 워크플로우

| 시점 | 무엇 | 누가 | 산출 |
| --- | --- | --- | --- |
| 스프린트 시작 | smoke 전체 실행 | 사람(버튼) | 런 + Slack + 감사 로그 |
| 머지·배포 후 | 배포 검증(sanity) | 사람(버튼) | 런 + Slack + 감사 로그 |
| 기능 추가 시 | 초안 생성 → 탐색기 확인 → 승인 → YAML PR | 사람 + Hermes | 스크립트 증가 |
| 릴리스 전(main 승격) | 릴리스 런 + 체크리스트 + 승격 판단 | 사람 | 릴리스 기록(승격 근거) |
| 실패 시 | Hermes 진단 → 분류 | 사람 | 버그 이슈 / 스크립트 수정 / 환경 조치 |

플랫폼이 압박하는 유일한 수단은 **배지**다. 미검증 배포가 쌓이거나 현재 사이클에 smoke가 없으면 대시보드가 그렇게 표시한다. 실행하지는 않는다.

### 7.3 스크립트가 늘어나는 경로 (AI 검증 겹)

1. 사람이 도메인(예: `room`)을 골라 [초안 생성].
2. 플랫폼이 PRD(`raw/product/룸-생성` 등) + SSOT의 해당 gate/command + OpenAPI 해당 operation(요약·요청 예제·에러 코드)을 모아 Hermes에 넘긴다.
3. Hermes가 스크립트 JSON 목록을 낸다. 플랫폼이 **결정론 검증**: 스키마 유효성, operationId 실재, 에러 코드가 스펙 예시에 존재, 테스트 계정 지정 여부, 쓰기 스크립트의 정리 단계 존재.
4. 통과한 것만 스크립트 초안에 들어간다. 사람이 탐색기로 한 번 돌려보고 승인 → 플랫폼이 main 에 커밋(2026-09-23 부터, [`qa-platform-editor.md`](qa-platform-editor.md) §6. 그 전에는 사람이 YAML 을 PR).
5. **승인 없이 실행 스위트에 들어가는 스크립트는 없다.**

## 8. 스크립트 형식

> 2026-09-24: 스크립트에 `variant:`(구현하는 시나리오 케이스)와 `uses:`(앞에 붙일 테스트 데이터 만들기 카드) 칸이 더해졌다. [`qa-platform-scenarios.md`](qa-platform-scenarios.md) §5, §8.

```yaml
id: room.create-and-cancel
title: 방장이 룸을 만들고 취소하면 CANCELED 가 된다
suite: sanity                 # smoke | sanity | manual
domains: [room]               # 변경 범위 → 권장 스크립트 선택 키
operations: [createRoom, roomDetail, cancelRoom]
source: ["PRD/룸 생성 §4.8", "PRD/룸 참여 §4.9", "G.room.cancel"]
actor: qa-host                # 기본 테스트 계정. 단계별 actor 로 덮어쓴다. 없으면 비로그인
steps:
  - name: 룸 생성
    request:
      method: POST
      path: /v1/rooms
      body:
        postingId: "{{fixture.postingId}}"
        jobRoleId: 2
        round: FIRST
        type: JOB
        method: ONLINE
        minParticipants: 2
        maxParticipants: 4
        schedule: { date: "{{date:+7}}", startTime: "14:00", durationMinutes: 90 }
        title: "[QA] 룸 생성 sanity"
        resumeId: "{{fixture.qa-host.resumeId}}"
        resumePublic: true
    expect: { status: 200, result: SUCCESS, json: { "data.status": RECRUITING } }
    save: { roomId: data.roomId }
  - name: 상세 조회
    request: { method: GET, path: "/v1/rooms/{{roomId}}" }
    expect: { status: 200, json: { "data.hostMemberId": "{{actor.qa-host.memberId}}" } }
  - name: 취소
    request: { method: POST, path: "/v1/rooms/{{roomId}}/cancellation" }
    expect: { status: 200 }
  - name: 취소 후 재취소는 E1410
    request: { method: POST, path: "/v1/rooms/{{roomId}}/cancellation" }
    expect: { status: 409, error_code: E1410 }
```

- 기대(expect): `status`, `result`, `error_code`, `json`(경로→값), `exists`(경로 목록). 이 5개로 시작하고 늘리지 않는다.
- 치환: `{{var}}`(save), `{{actor.X.memberId}}`, `{{fixture.*}}`(환경 설정), `{{date:+N}}`, `{{uuid}}`.
- 픽스처(공고 id, 이력서 id)는 스크립트가 아니라 **환경 설정**에 둔다 — dev 데이터가 바뀌면 설정만 고친다.

### 8.1 초기 스크립트(시드) — dev에서 실제로 확인된 응답 기준

| id | suite | 테스트 계정 | 요지 |
| --- | --- | --- | --- |
| platform.health | smoke | – | `/actuator/health` 200 |
| catalog.terms / job-roles / regions | smoke | – | 카탈로그 3종 200 + `data` 존재 |
| room.form-options / room.explore | smoke | – | 폼 선택지·탐색 목록 200 |
| auth.me-without-token | smoke | – | `/v1/members/me` → 401 E1102 |
| auth.dev-session-unknown | smoke | – | 없는 회원 → 404 E1006 |
| member.me | smoke | qa-host | 200, `data.memberId == 테스트 계정` |
| room.create | sanity | qa-host | 생성 → 상세 → 정리(취소). 옛 `room.create-and-cancel` 을 2026-09-24 셋으로 나눴다 |
| room.cancel / room.cancel-not-recruiting | sanity | qa-host | `uses: setup.room-open` 뒤 취소 200 / 재취소 409 E1410 |
| room.apply-and-withdraw | sanity | qa-host, qa-guest | 생성 → 신청(201 PENDING) → 철회 → 취소 |
| room.create-limit | sanity | qa-host | 같은 공고·직무 활성 3개 → 4번째 409 E1427 (정리: 3개 취소) |

비로그인 스크립트 6건은 이미 dev 서버에서 응답을 확인했다. 테스트 계정이 필요한 스크립트는 `qa-actors` 주입 후 검증한다.

## 9. 데이터 모델 (sqlite)

```text
runs        id, created_at, finished_at, trigger(deploy-sanity|sprint-smoke|release|manual),
            operator, suite, env, base_url, ref, sha, pr_number,
            verdict(pass|fail|error|canceled), total, passed, failed, skipped,
            meta(json: 선택 근거, 체크리스트, 릴리스 판단)
run_cases   run_id, case_id, case_hash, case_yaml(스냅샷), verdict, duration_ms, error, triage(진단 결과)
run_steps   run_case_id, idx, name, request(json, 마스킹), response(json, 절단), checks(json), verdict, duration_ms
events      id, at, operator, session_hash, ip, action, target, detail(json)   ← 감사 로그
drafts      id, created_at, operator, status(draft|approved|rejected), source(hermes|explorer), yaml, note
```

스크립트 정본은 DB가 아니라 git이다. DB는 **실행 이력·감사 로그·초안**만 갖는다. 실행 시점의 스크립트 본문을 런에 박아 두므로 스크립트 YAML을 고쳐도 과거 런은 그대로다(토스 스냅샷 원칙).

## 10. 계약

### 10.1 엔드포인트 (`https://qa.agent.plady.io`)

| 경로 | 인증 | 용도 |
| --- | --- | --- |
| `/` `/runs` `/runs/{id}` `/cases` `/explorer` `/drafts` `/release` `/activity` | 팀 세션(wiki-auth forward_auth) | UI |
| `POST /api/runs` `POST /api/runs/{id}/cancel` `POST /api/runs/{id}/triage` `POST /api/runs/{id}/publish` `POST /api/drafts/generate` `POST /api/explorer/send` | 팀 세션 | UI가 쓰는 JSON API. 모두 운영자 필드 필수 |
| `GET /health` | 없음 | 배포 smoke |

**inbound webhook 없음.** 외부에서 런을 시작시킬 수 있는 경로가 설계상 존재하지 않는다.

### 10.2 환경 변수 / SSM 이름 (`/plady/agent-platform/<env>/…`)

| 이름 | 비밀 | 용도 |
| --- | --- | --- |
| `qa-actors` | SSM | `{"qa-host": "<uuid>", "qa-guest": "<uuid>"}` — dev 목데이터 회원 2개 지정 |
| `qa-fixtures` | SSM | `{"postingId": …, "qa-host.resumeId": …}` |
| `qa-github-token` | SSM, 선택 | 있으면 GitHub 조회 rate limit 완화. 없으면 미인증 + 캐시 |
| `QA_TARGET_BASE_URL` | 평문 | `https://api.dev.moimyeon.plady.io` |
| `QA_SPEC_URL` | 평문 | GitHub Pages `openapi3.yaml` (dev 브랜치) |
| `QA_SPEC_TTL` | 평문(선택) | API 문서 캐시 초, 기본 600. 화면의 [API 문서 다시 읽기]가 캐시를 무시하고 앞당긴다 |
| `QA_BACKEND_REPO` | 평문 | `100Thieves-team/moimyeon-backend` |
| `QA_OPERATORS` | 평문 | 확인 화면 드롭다운 목록 (예 `bebe,중곤,dbwp031`) |
| `HERMES_API_URL` / `HERMES_API_KEY` / `HERMES_MODEL` | 기존 재사용 | AI 호출 |
| `LLM_WIKI_MCP_URL` / `LLM_WIKI_MCP_BEARER_TOKEN` | 기존 재사용 | PRD·SSOT 읽기, 보고서 쓰기 |
| `WIKI_SLACK_WEBHOOK_URL` | 기존 재사용 | `_wiki-alert` 알림 (사용자 결정) |

### 10.3 이 레포 변경 목록

- `qa-platform/` 소스(Python 3.12, 표준 라이브러리 + PyYAML), `qa-platform/cases/*.yaml`, `docker/qa-platform.Dockerfile`
- `compose.yaml` / `compose.ec2.yaml`: `qa-platform` 서비스(profile `qa`, `expose 8800`, 볼륨 `qa-data`), Caddy `@qa` 블록
- `.github/workflows/deploy-agent-platform.yml`: 세 번째 ECR 이미지 빌드, 트리거 paths에 `qa-platform/**`, 스모크에 `qa` 1건 추가
- `scripts/ec2-deploy.sh`: SSM 3개 읽기(`qa-actors`·`qa-fixtures`·`qa-github-token`), `.env.ec2`, `--profile qa`
- `infra/terraform/platform/variables.tf`: `service_subdomains`에 `qa` 추가
- `docs/platform-contract.md` 엔드포인트 표에 `qa.agent.plady.io` 추가, 이 문서를 런북으로 갱신

**백엔드 레포 변경 없음.**

사람이 해야 하는 일: Cloudflare에 `qa.agent.plady.io` CNAME 1건, SSM 파라미터 2~3개 주입(QA 회원 UUID·픽스처 id), 첫 배포 후 테스트 계정 스크립트 1회 확인.

## 11. 기술 선택과 이유

| 선택 | 이유 | 버린 대안 |
| --- | --- | --- |
| Python 3.12 표준 라이브러리 + PyYAML, sqlite | `wiki-auth`·`policy-renderer`와 같은 결. 의존성 관리 없음, t3.small에서 가벼움 | FastAPI(의존 트리), Node(n8n 코드 노드와 결이 다름), Kotlin(백엔드 레포에 QA 실행기를 넣으면 DR-022 경계가 무너짐) |
| 스크립트 = 이 레포의 git YAML | 리뷰 가능, 에이전트가 PR로 제안, 플랫폼 이미지와 함께 배포되어 백엔드 레포 의존이 없다 | 백엔드 레포 `qa/`(코드와 같은 PR에 실리는 장점, 대신 플랫폼이 남의 레포를 체크아웃해야 함), DB 편집기(정본 둘) |
| GitHub **조회**로 배포 감지 | 읽기 전용. 백엔드 레포 변경·시크릿·inbound 엔드포인트가 전부 불필요해진다. 어차피 실행은 사람이 하므로 실시간성이 필요 없다 | inbound webhook(백엔드 PR + HMAC + 공개 엔드포인트) |
| 사람 트리거 전용, 자동 실행 없음 | 사용자 결정. 덤으로 dev 데이터 오염·런 폭주·실패 알림 피로가 구조적으로 막힌다 | 배포 훅 자동 실행, 크론 |
| 결정론 러너, AI는 초안·진단만 | 매 실행에 LLM을 쓰면 비용·비결정성. 이슈 요구 "매번 모든 스크립트를 계산하는 비용" 회피 | 에이전트가 매번 탐색 실행 |
| Hermes 경유 AI | 모델 키·위키 도구가 이미 Hermes에 있다. 플랫폼은 키를 갖지 않는다(사용자 지시) | 플랫폼 직접 OpenAI 호출 |
| 서버 렌더 HTML | 2인 팀, 빌드 파이프라인 없이 배포. 탐색기 폼도 스펙에서 생성 | SPA |

## 12. 단계

| 단계 | 내용 |
| --- | --- |
| P0 ✅ | 러너·스크립트 형식·시드 13종·런/단계 기록·감사 로그·대시보드·런 상세·스크립트·임의 실행·Slack·compose/배포 배선 |
| P1 ✅ | 배포 감지(GitHub 조회)·변경 범위 제안·배포 검증 버튼·스프린트 배지·릴리스 화면(체크리스트 + 판단 기록)·활동 화면·테스트 계정/픽스처 SSM 주입·Hermes 실패 진단(P2 에서 앞당김) |
| P2 ✅ | 테스트 조건 카탈로그(SSOT·OpenAPI·서술 파생)·`covers` 검증·커버리지·드리프트 배지·Hermes 초안 생성·스크립트 초안·탐색기(Swagger 모드)·위키 보고서 발행 버튼·가이드 화면 — 설계·구현 결과 [`qa-platform-tc.md`](qa-platform-tc.md) |
| P3 | 커버리지 공백 화면 ✅(P2 기준 화면) · 스프린트 리마인더 Slack ✅(알림만, `qa/reminder.py`) · Linear 코멘트(연결 인증 후). live 읽기 전용 smoke 는 **뺐다** — QA 는 live 와 무관하게 간다(사용자 결정 2026-09-21) |
| P4 | QA MCP 도구 ✅(P4a, `qa/mcp_server.py` — Hermes 가 기준·스크립트·런을 읽고 초안을 낸다) · Hermes 채팅창 ✅(P4b, `/chat`, `qa/chat.py`, Hermes `/v1/responses`) · 바뀐 테스트 조건에 맞게 스크립트 다시 쓰기 ✅(P4c, `POST /cases/{id}/revise`, 초안 source hermes-revise + diff) · PRD 절에서 수동 작성 테스트 조건 제안 ✅(P4d, `POST /catalog/propose-tc`, 초안 kind tc) — 설계 [`qa-platform-hermes.md`](qa-platform-hermes.md) |
| P5 | 토스식 호출 카드 ✅(P5a, Normal 폼 / Swagger 요청 원문 토글, `/explorer` 재구성, op 별 QA 배지, CSS 손질) · 실행 결과 요약 ✅(P5d, 카드 4·통과율 도넛·도메인별 진행 막대·판정 필터) · API 별로 테스트 조건·스크립트·최근 호출을 모아 보는 화면 ✅(P5b, `/apis`, `run_steps.op_id`, MCP `qa_api_get`), API 호출 화면 마찰 줄이기 ✅(P5a 에 포함: 최근 값·즐겨찾기·프리필), 버튼 하나로 테스트 데이터 만들기 ✅(P5c, `/setup`, suite setup·inputs·outputs, 시드 3개 — 확정 시드는 dev 미확인), 통과율·평균 소요·불안정(flaky) 배지 ✅(P5e, 스크립트·API 화면) — **P5 전부 완료** — 설계 [`qa-platform-api.md`](qa-platform-api.md) (토스 QA Platform·Tossion 참고) |
| P6 ✅ | 폼으로 스크립트·수동 작성 테스트 조건 만들기·고치기·지우기(초안을 거쳐 승인하면 main 에 `[skip ci]` 커밋, 플랫폼 즉시 반영) — 설계 [`qa-platform-editor.md`](qa-platform-editor.md) · Hermes 작업 진행을 SSE 로(초안 생성·테스트 조건 제안·고치기·실패 분석) — 설계 [`qa-platform-progress.md`](qa-platform-progress.md) (2026-09-23, 사용자 요청) |

P0·P1 이 이 이슈(estimate 16pt). P2 이후는 후속 이슈로 쪼갠다.

## 13. 남은 결정

1. **스크립트 정본 위치** — 이 레포 `qa-platform/cases/`로 정했다(백엔드 레포 무변경 원칙 유지). 스크립트가 API 변경과 같은 PR에 실려야 한다는 요구가 나오면 재검토한다.
2. **dev QA 회원** — 기존 목데이터 회원 2개(`…1001` `…1003`)를 테스트 계정으로 쓰는 것으로 제안한다. 이 회원들이 다른 목적으로 쓰이고 있어 QA가 상태를 바꾸면 곤란하다면, 전용 회원 2개를 만들어 UUID를 알려주면 된다.
3. **위키 보고서** — `wiki/qa/`에 generated 페이지, 사람이 [위키에 발행]을 누를 때만. 기본은 안 쓴다.
4. **운영자 신원** — 자기 신고(§6.2). 진짜 신원이 필요하면 wiki-auth에 개인 계정을 얹는 별도 작업.
5. **릴리스 게이트** — 사람이 릴리스 화면을 보고 승격을 판단하고 그 판단을 기록만 한다. `promote-live` 연동은 **하지 않는다** — QA 플랫폼은 live 환경과 무관하게 둔다(사용자 결정 2026-09-21).

## 14. 구현 결과와 운영 절차 (2026-09-21)

### 14.1 무엇이 들어갔나

| 위치 | 내용 |
| --- | --- |
| `qa-platform/app.py`, `qa-platform/qa/*.py` | 서버·러너·저장소·GitHub 조회·Hermes 진단·Slack·UI. 표준 라이브러리 + PyYAML |
| `qa-platform/cases/{platform,auth,room}.yaml` | 시드 13건 — smoke 10(비로그인 9 + 테스트 계정 1), sanity 3(테스트 계정·픽스처 필요) |
| `qa-platform/tests/test_core.py` | 15 테스트(치환·단언·스크립트 검증·선택·도메인 매핑·스프린트·러너·감사 로그·Hermes) |
| `docker/qa-platform.Dockerfile` | `python:3.12-alpine` + PyYAML, `/data` 볼륨, HEALTHCHECK |
| `compose.yaml` / `compose.ec2.yaml` | `qa-platform` 서비스(profile `qa`, `expose 8800`, 볼륨 `qa-data`), Caddy `@qa` = `qa.agent.plady.io`(팀 세션, `/health` 만 무인증) |
| `.github/workflows/deploy-agent-platform.yml` | 세 번째 ECR 이미지 `plady-agent-platform/qa-platform`, 트리거 paths `qa-platform/**`, 공개 smoke 에 `qa/health` |
| `scripts/ec2-deploy.sh` | SSM `qa-actors`·`qa-fixtures`·`qa-github-token`(전부 선택) → `.env.ec2`, `--profile qa` 상시 |
| `infra/terraform/platform/variables.tf` | `service_subdomains` 에 `qa` |
| `docs/platform-contract.md` | 엔드포인트 표·SSM 이름 표에 qa 항목 |

### 14.2 검증한 것

- 단위 테스트 15/15. 도커 이미지 빌드·기동·`/health` OK.
- dev 서버 상대 실제 실행: 스프린트 smoke 런 **통과 9 · skip 1**(테스트 계정 미설정 스크립트 `member.me`) — 대시보드 → 확인 화면 → 실행 → 런 상세 → 활동 로그까지 브라우저로 확인.
- 테스트 계정 흐름: 로컬에서 dev 목데이터 회원을 `QA_ACTORS` 로 주고 `member.me`·`room.creation-limit` 읽기 전용 스크립트 실행 → dev-sessions 토큰 발급 → **통과**. 기록의 Authorization 은 `Bearer ***` 로 마스킹됨.
- 릴리스 흐름: 릴리스 런 → 백엔드 `release-checklist.md` 6항목을 raw 로 읽어 표시 → GO 판단 기록(meta + `release.decide` 이벤트). 릴리스가 아닌 런에 판단하면 400.
- 운영자 없이 런 생성 시 400. GitHub 미인증 조회로 dev 배포 10건 + PR 제목 표시.
- 테스트 계정·픽스처 주입 후(2026-09-21, 전용 QA 회원): 테스트 계정 스크립트 4건 전부 통과 — 쓰기 sanity 2건은 dev 에 `[QA]` 룸을 만들고 신청·철회·취소까지 스스로 정리했다. 남은 미검증은 Hermes 진단(키가 없어 대역으로만)뿐이다.

### 14.3 사람이 해야 하는 일 (배포 순서)

0. **ECR 저장소 + push/pull 권한 (push 전, 차단 항목).** 저장소 `plady-agent-platform/qa-platform` 이 없고, GHA push 정책(`plady-agent-platform-ecr-push`)과 EC2 pull 정책(`plady-agent-platform-ecr-pull`)이 기존 두 저장소 ARN 에만 묶여 있어 그대로 push 하면 이미지 push 단계에서 배포가 실패한다. terraform 에는 codify 돼 있다(`main.tf` `aws_ecr_repository.qa_platform`, `iam.tf`·`compute.tf` ARN 추가). `terraform apply` 가 가능하면 그걸로, 아니면 아래 CLI 로 같은 상태를 만든다(`AWS_PROFILE=plady-service`, 멱등):

   ```bash
   export AWS_PROFILE=plady-service AWS_REGION=ap-northeast-2
   aws ecr create-repository --repository-name plady-agent-platform/qa-platform --image-scanning-configuration scanOnPush=true
   aws ecr put-lifecycle-policy --repository-name plady-agent-platform/qa-platform --lifecycle-policy-text \
     '{"rules":[{"rulePriority":1,"description":"Keep last 10 images","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}'
   # zsh 는 `set -- $var` 로 단어를 쪼개지 않는다 — 함수 인자로 넘긴다. put 은 stdin 대신 임시 파일로.
   ARN=arn:aws:ecr:ap-northeast-2:781897847312:repository/plady-agent-platform/qa-platform
   add_arn() {
     aws iam get-role-policy --role-name "$1" --policy-name "$2" --query PolicyDocument --output json \
       | jq --arg arn "$ARN" '.Statement |= map(if (.Resource|type)=="array" and ((.Resource|index($arn))==null) then .Resource += [$arn] else . end)' \
       > /tmp/qa-policy.json
     aws iam put-role-policy --role-name "$1" --policy-name "$2" --policy-document file:///tmp/qa-policy.json
   }
   add_arn plady-agent-platform-github-actions-ecr plady-agent-platform-ecr-push
   add_arn plady-agent-platform-ec2-role plady-agent-platform-ecr-pull
   # 확인: 두 정책 모두 1 이 나와야 한다
   for r in "plady-agent-platform-github-actions-ecr plady-agent-platform-ecr-push" "plady-agent-platform-ec2-role plady-agent-platform-ecr-pull"; do
     aws iam get-role-policy --role-name "${r%% *}" --policy-name "${r#* }" --query PolicyDocument --output json | jq '[.Statement[].Resource] | flatten | map(select(test("qa-platform"))) | length'
   done
   ```

1. **Cloudflare** `agent.plady.io` 존에 `qa` CNAME → `plady-agent-platform-alb-1366645660.ap-northeast-2.elb.amazonaws.com` (기존 `n8n` 레코드와 같은 프록시 설정으로). ACM 은 `*.agent.plady.io` 와일드카드라 인증서 작업은 없다. ALB 리스너 규칙은 host 무관 단일 Caddy origin 이라 추가 없음. terraform `service_subdomains` 는 이미 갱신.
2. **SSM** (`/plady/agent-platform/dev/`) — **2026-09-21 주입 완료** (`qa-actors` v3, `qa-fixtures` v2). 테스트 계정 = dev 에 새로 가입한 **전용 QA 회원 2명**(`영리한 라쿤 95` = qa-host, `차분한 라쿤 69` = qa-guest), 픽스처 = 공고 2889 / 직무 1 / 각자의 이력서. 값은 SSM 에만 있다.
   - 처음엔 목데이터 회원(`고래 05`·`곰 04`)을 썼는데 목데이터 5명 전원이 참여 슬롯 한도(3)를 넘긴 상태라 룸 생성이 **409 E1425** 로 거부됐다 — 스크립트가 아니라 dev 데이터 전제 조건 문제였고, 전용 회원으로 바꾸자 해소됐다.
   - 이 값으로 dev 에 돌린 결과: `member.me`·`room.creation-limit`·`room.create-and-cancel`·`room.apply-and-withdraw` **4/4 통과**. 쓰기 스크립트는 `[QA]` 룸을 만들고 스스로 취소했다.
   - 테스트 계정 회원을 바꾸면 `aws ssm put-parameter --overwrite` 로 두 값을 갱신하고 재배포한다. 목데이터 회원의 룸을 정리해 슬롯을 비우는 방법은 다른 용도의 데이터를 건드리므로 쓰지 않는다.
3. **머지 → main** — 워크플로가 이미지를 빌드·배포하고 `https://qa.agent.plady.io/health` 를 smoke 한다.
4. 배포 후 `https://qa.agent.plady.io` 에서 팀 비밀번호 로그인 → 스크립트 화면에서 13건 보이는지 → 스프린트 smoke 1회 실행 → 테스트 계정 스크립트가 pass 로 바뀌는지 확인. 쓰기 sanity 3건은 대시보드의 미검증 배포 [검증] 또는 임의 실행으로 1회 돌려 dev 에 `[QA]` 룸이 만들어졌다 취소되는지 본다.

### 14.4a 담당자 고르기와 기능별 도움말 (2026-09-22, 사용자 요청)

- **처음 들어오면 "누구세요?"** — HTML 화면은 담당자 쿠키(`qa_operator`, 목록 `QA_OPERATORS` 안의 이름)가 없으면 `/whoami` 로 보낸다(API·정적 파일·MCP 제외). 고르면 쿠키를 심고 원래 화면으로. 감사 로그 `operator.pick`. 여전히 자기 신고(§6.2)다 — 인증 신원이 아니라 이름을 고르는 것. 오른쪽 위 [바꾸기].
- **사람별 저장**: 즐겨찾기·최근에 넣은 값(API 호출)·열어 둔 Hermes 대화는 브라우저 localStorage 키에 담당자 이름을 붙여(`qa_fav:bebe`) 같은 브라우저에서도 사람별로 나뉜다. 서버 저장은 없다.
- **기능별 도움말 "?"**: 화면의 제목·표 머리·버튼 옆 `?` 를 누르면 모달 — 무엇인지 · 언제 쓰는지 · 어떻게 하는지. 내용은 `qa/help.py` 의 `HELP` 표(70여 개), `ui.h("키")` 가 버튼, `/static/help.js` 가 모달. 테스트가 화면이 쓰는 키가 전부 표에 있는지 검사한다. 특히 "자동화됨 · 미자동화" 도움말이 미자동화 테스트 조건을 자동화하는 길(초안 생성 → 한 번 실행 → 승인 → PR, 또는 exclusions)을 적는다.

### 14.4b QA 데이터 정리 (2026-09-23)

백엔드 PR #135 의 dev 전용 API(`/v1/dev/…`)로 "테스트 데이터 만들기" 화면에서 `[QA]` 룸 삭제·일괄 삭제·테스트 계정 초기화·QA 회원 삭제를 한다(qa-host 토큰, 감사 로그 `qa_data.*`, 실행 기록 아님). `/v1/dev/` 는 테스트 조건·API 화면에서 빠지고 API 호출 화면에만 `qa-dev` 도메인으로 남는다. 자세한 것은 [`qa-platform-api.md`](qa-platform-api.md) §11.6.

### 14.4c 폼 편집과 Hermes 작업 (2026-09-23, 사용자 요청)

- **폼 편집**: `/cases/new` · `/cases/{id}/edit` · `/drafts/{id}/edit`(스크립트), `/catalog/manual/new` · `/catalog/tc/edit`(수동 작성 테스트 조건), 삭제 요청. 전부 초안이 되고 승인하면 `QA_REPO_TOKEN` 으로 이 레포 main 에 커밋한다. 자세한 것은 [`qa-platform-editor.md`](qa-platform-editor.md) §11.
- **Hermes 작업**: 초안 생성·수동 작성 테스트 조건 제안·고치기·실패 분석이 `/jobs/{id}` 진행 카드로 바뀌었다. 진행은 `/api/jobs/{id}/events` SSE. 자세한 것은 [`qa-platform-progress.md`](qa-platform-progress.md) §8.
- **사람 작업**: SSM `/plady/agent-platform/dev/qa-repo-token` 에 이 레포 contents: write fine-grained PAT 를 넣는다. 없으면 승인 뒤 [반영된 파일 받기]로 끝난다.

### 14.4d 초안·승인 없이 바로 저장 (2026-09-24, 사용자 결정)

- 폼 저장, Hermes 생성·고치기·테스트 조건 제안, Hermes 채팅 도구, 삭제가 모두 검증을 통과하면 main 에 바로 커밋된다. `/drafts` 는 "변경 기록" 이 됐다. Hermes 가 쓴 항목에는 `written_by: hermes` 가 붙고 사람이 폼으로 저장하면 사라진다. 자세한 것은 [`qa-platform-scenarios.md`](qa-platform-scenarios.md) §9, §17.

### 14.4 운영 메모

- 스크립트 추가·수정은 `qa-platform/cases/*.yaml` PR. 배포되면 새 이미지에 실린다. 로컬 확인은 UI 스크립트 화면의 [파일에서 다시 읽기].
- dev 데이터가 바뀌어 스크립트가 깨지면 스크립트가 아니라 `qa-fixtures` 값을 먼저 의심한다.
- 스프린트 번호는 앵커(`QA_SPRINT_ANCHOR=2026-09-13T15:00Z` = Cycle 9, 7일 주기)로 계산한다. Linear 사이클 주기가 바뀌면 이 두 값을 바꾼다.
- 런 기록은 `qa-data` 볼륨(sqlite)에 무기한. 백업은 볼륨 단위.
- Hermes 진단은 `HERMES_API_SERVER_KEY` 가 `.env.ec2` 에 있으면 켜진다(이미 hermes 프로필용으로 존재). 모델은 `HERMES_MODEL`(기본 gpt-5.5).
- 스프린트 smoke 리마인더: 마감 `QA_SPRINT_REMIND_DAYS`(기본 1)일 전부터 이번 스프린트에 smoke 런이 없으면 Slack 에 **한 번** 알린다(events `sprint.remind`). 알림만 하고 실행하지 않는다. 끄려면 `QA_SPRINT_REMINDER=0`.
