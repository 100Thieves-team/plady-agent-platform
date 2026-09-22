# QA 플랫폼 P5 — API 중심 보기 (토스 QA Platform · Tossion 참고)

> 상태: **설계 초안 v2 — 검토 대기** (2026-09-22). 사용자 지시 "토스처럼 Swagger UI 기반으로 뭔가 하거나, API 별로 TC 를 모아서 본다든지". v1 은 Swagger UI 를 안 붙이자고 했으나 사용자가 뒤집었다: **"Swagger UI 는 사람이 그냥 API 호출해 보기 위한 것 — 기록 우회는 괜찮다"**. v2 는 그 결정을 반영한다.
> 선행 문서: [`qa-platform.md`](qa-platform.md)(P0·P1) · [`qa-platform-tc.md`](qa-platform-tc.md)(P2·TC) · [`qa-platform-hermes.md`](qa-platform-hermes.md)(P4). 원칙·용어는 그대로다.
> 참고한 글: [토스인컴 QA Platform](https://toss.tech/article/income-qa-platform) · [Tossion](https://toss.tech/article/tossion).

## 0. 한 줄 요약

둘을 더한다. **① Swagger UI** — 사람이 그냥 API 를 호출해 보는 화면. 기록하지 않는다. 플랫폼이 스펙을 넘겨주고(브라우저가 dev 로 직접 호출 — CORS 는 백엔드가 연다), op 마다 QA 배지(TC 수·자동화·마지막 결과)를 얹는다. **② API 별로 모아 보기** — 지금 플랫폼은 TC(무엇을 확인하나)·스크립트(어떻게 확인하나)·실행 기록(언제 어땠나)을 따로 보여 주는데, API 하나를 축으로 셋을 한 화면에 모은다 — "`createRoom` 은 TC 가 몇 개고, 어느 스크립트가 부르고, 지난번엔 어땠나". 그 위에 토스인컴 글의 "사소한 마찰"(값 다시 찾기, 순서대로 여러 번 호출)을 버튼 하나짜리 준비 작업으로 줄인다.

## 1. 전제 — 확인한 사실

1. 백엔드 API 문서(GitHub Pages `…/api/branches/dev/`)는 **Spring REST Docs 의 AsciiDoc HTML 한 장 + `openapi/openapi3.yaml`** 이다. Swagger UI 는 없다. 플랫폼은 이미 이 yaml 을 1시간 캐시로 읽는다(`qa/spec.py`).
2. dev 스펙은 op 83개. `tags` 는 79개가 `v1`, 나머지 `Auth`·`get`·`post` — **태그로는 묶을 수 없다.** 묶음은 경로 세그먼트 → 도메인 표(`catalog.PATH_DOMAIN`, 이미 TC 목록이 쓰는 것)로 한다.
3. TC 레코드는 op 를 이미 안다: API 계약 TC 는 `operation`, 비즈니스 규칙 TC 는 `binding.operations`(bindings.yaml), 수동 작성 TC 는 `binding.operations`(manual-tc.yaml 의 `operations`). 스크립트는 `operations:` 선언 + 단계 `request.method/path`. 실행 기록의 단계는 `request.method/path` 만 있고 op id 는 없다 — `spec.op_for(method, path)` 로 경로 템플릿 매칭이 된다(API 호출 화면이 쓰는 함수).
4. 실행 기록은 스크립트 스냅샷(`run_cases.case_yaml`)과 단계별 요청·응답·검증 항목·소요를 이미 남긴다. Tossion 의 "런은 그 시점 스냅샷" 은 이미 돼 있다.
5. API 호출 화면(`/explorer`)은 op 하나를 골라 폼으로 보내고, 전송을 실행 기록(`trigger=explorer`, 목록 기본 숨김)으로 남긴다. 값 기억·즐겨찾기·프리필은 없다.
6. **dev 는 지금 `https://qa.agent.plady.io` 오리진의 브라우저 요청을 CORS 로 막는다** — `OPTIONS /v1/terms` 프리플라이트도, `Origin` 헤더를 단 단순 GET 도 403(Spring 의 허용 안 된 오리진 응답). **사용자가 백엔드 CORS 허용 목록에 qa 오리진을 넣기로 했다(2026-09-22)** — 플랫폼은 전달 프록시를 만들지 않고 Swagger 가 dev 로 직접 호출한다. 백엔드에 필요한 허용: origin `https://qa.agent.plady.io`, 메서드 GET·POST·PUT·PATCH·DELETE·OPTIONS, 헤더 `Authorization`·`Content-Type`·`Accept`. 쿠키는 안 쓰므로 credentials 는 필요 없다. 로컬에서 Swagger 를 띄우려면 `http://localhost:8800` 도(선택).
7. 스펙에 `servers`(`localhost:8080`, dev)와 `securitySchemes`(`BearerAuth` http bearer JWT · `AccessTokenCookie`)가 있다. Swagger UI 의 [Authorize] 가 그대로 쓰인다. op 별 `security` 는 비어 있다(전역도 없음) — Authorize 로 넣은 토큰은 Swagger UI 가 모든 요청에 붙인다.
8. Swagger UI 는 op 를 태그로 묶는다. 태그가 전부 `v1` 이라(전제 2) 그대로 주면 한 덩어리 83개다 — 넘겨주는 스펙에서 태그를 도메인으로 바꿔 준다.

## 2. 토스 글에서 가져오는 것과 안 가져오는 것

### 2.1 토스인컴 QA Platform — 가져오는 것
- **"어떤 API 를 쓸지, 어떤 값을 넣을지, 어떤 순서로" 를 UI 가 대신 안다.** → 순서 있는 호출 묶음을 버튼 하나로(§5.4). 우리 스크립트 형식(단계 열 + `save`)이 그대로 묶음이다. 빠진 건 **입력을 화면에서 받는 것** 과 **결과값을 돌려주는 것** 뿐이다.
- **Normal 모드 / Swagger 모드** → 준비 작업 화면(폼) / API 호출 화면(JSON). 둘 다 같은 실행 기록으로 남는다.
- **사소한 마찰 제거**(최근 값 기억, 자주 쓰는 것 위로, 화면 크기 대응) → §5.3.
- 진화 순서(Test API 버튼화 → 자동화 스크립트 버튼화 → 테스트 관리 통합)는 우리가 거꾸로 왔다. 관리(P2)·AI(P4)가 먼저 있고 "버튼 하나로 데이터 만들기" 가 없다. P5c 가 그 빈칸이다.

### 2.2 Tossion — 가져오는 것
- **"이 기능, 지난번 테스트 결과 어땠죠?" 에 바로 답하기** → API 상세의 최근 호출 기록(§5.2). 우리 데이터로 이미 답할 수 있는데 화면이 없다.
- **누적 통과율 · flaky · 평균 소요** → 스크립트와 API 에 배지(§5.5).
- 계층(Project → Suite → Section → TC)은 우리 도메인 × 층 × TC 로 이미 대응된다. 새 계층을 만들지 않는다.

### 2.3 Swagger UI — 붙인다 (사용자 결정 2026-09-22)
- 토스인컴의 "Swagger 모드" 그대로: **사람이 그냥 API 를 호출해 보는 자리.** 실행 기록·감사 로그·마스킹을 거치지 않는다 — 그건 "검증" 이 아니라 "만져 보기" 라서. 기록이 필요한 호출은 지금처럼 [API 호출] 화면으로.
- 플랫폼이 더하는 것은 둘. 스펙을 **도메인 태그·dev 서버·QA 요약(`x-qa`)** 을 얹어 넘겨 주고, [Authorize] 에 넣을 **테스트 계정 토큰을 버튼 하나로** 준다. 호출은 브라우저가 dev 로 직접 한다(CORS 는 백엔드가 연다 — 전제 6). 플랫폼은 요청 경로에 없다.
- 화면은 `swagger-ui-dist` 를 그대로 쓴다. 플랫폼의 "프레임워크 없는 서버 렌더" 원칙은 **플랫폼 화면** 에 대한 것이고, Swagger UI 는 남의 화면을 한 장 끼우는 것이다. 우리 CSS 를 덧씌우지 않는다.

### 2.4 안 가져오는 것
- 실기기 자동화, 공동 편집(아바타·잠금), PR 위험도 AI 판정. 범위 밖.
- AI TC 생성의 3중 검증. 우리 초안 생성은 이미 결정론 검증(§7.2)을 통과한 것만 받는다. 더 얹지 않는다.

## 3. 원칙 (기존 것에 더한다)

1. **새 정본을 만들지 않는다.** API 화면은 OpenAPI·TC 목록·스크립트·실행 기록을 op 로 묶어 **읽기만** 한다. 저장하는 건 단계의 op id 하나(§6).
2. **실행은 여전히 사람이 버튼을 누를 때만.** 준비 작업도 테스트 실행이다 — 실행 기록·감사 로그·Slack 규칙 동일.
3. **브라우저에만 남는 편의값**(최근 입력값·즐겨찾기)은 localStorage 로 두고 서버에 저장하지 않는다. 감사 대상이 아니다.
4. **Swagger UI 의 호출은 기록하지 않는다**(사용자 결정). 플랫폼은 요청 경로에 있지도 않다. 단 테스트 계정 토큰을 내주는 버튼은 사람 행위라 감사 로그에 남긴다(`swagger.token`).
5. 용어는 화면 용어표(선행 문서 "용어" 절)를 따른다. 새 말은 "Swagger", "API", "준비 작업", "최근 호출" 넷뿐이고 각각 설명을 붙인다.

## 4. 기능 트리

```text
P5 API 중심 보기
├─ 0. Swagger UI  /swagger                              nav "Swagger". 기록 없음
│   ├─ 스펙 /swagger/openapi.yaml: 캐시한 OpenAPI 에 servers → dev 하나 · tags → 도메인 · x-qa(op 별 TC·자동화·마지막 결과)
│   ├─ Try it out → 브라우저가 dev 로 직접 (CORS 는 백엔드가 연다. 플랫폼은 요청 경로에 없음, 기록 없음)
│   ├─ [qa-host 로 인증] 버튼 → 서버가 dev-sessions 토큰 발급 → Swagger Authorize 에 자동 주입 (감사 로그 swagger.token)
│   └─ 플러그인: op 요약 줄에 QA 배지 "TC 5 · 자동화 3/5 · 마지막 pass" → /apis/{op} 링크
├─ a. API 화면  /apis · /apis/{operationId}            읽기 전용. nav "API"
│   ├─ 목록: 도메인 탭 × 검색 · 행 = METHOD path · 요약 · TC (계약/규칙/수동) · 자동화 n/m · 부르는 스크립트 · 마지막 호출
│   ├─ 필터: 부르는 스크립트 없음(커버리지 공백) · 미자동화 TC 있음 · 문서화된 에러 없음
│   ├─ 상세: 스펙(파라미터·요청 예시·응답·에러 코드) · 이 API 의 TC(층별, 체크 → 초안 생성) · 부르는 스크립트 · 최근 호출 20건
│   └─ MCP 도구 qa_api_get 하나 추가 (상세와 같은 묶음)
├─ b. API 호출 화면 마찰 줄이기  /explorer               (Swagger 가 생겨 범위를 줄였다 — 프리필·반응형만)
│   ├─ 프리필 링크 (/explorer?op=X&p.roomId=…) · 최근 호출에서 [같은 요청으로 열기]
│   ├─ 도메인별 접기 · 좁은 화면 1열
│   └─ (뒤로 미룸) 파라미터 최근 값 · 즐겨찾기 — Swagger UI 가 그 자리를 대신하면 안 만든다
├─ c. 준비 작업 — 버튼 하나로 테스트 데이터 만들기  /setup
│   ├─ 스크립트 형식: suite setup · inputs(화면 입력) · outputs(돌려줄 값)
│   ├─ 화면: 카드(제목·설명·입력 폼·[실행]) → 실행 기록 → 결과값 표 + [API 호출에서 쓰기]
│   └─ 시드 3개 (모집 중 룸 · 신청 들어온 룸 · 확정된 룸)
└─ d. 통계 배지  스크립트·API 에 최근 20회 통과율 · 평균 소요 · flaky
```

## 5. 화면

### 5.1 API 목록 `/apis`

- 도메인 탭(TC 목록과 같은 순서·같은 표 `PATH_DOMAIN`) × 검색(operationId · 경로 · 요약). `/v1/*` 와 `/actuator/*` 만(TC 목록과 같은 범위).
- 행: `METHOD /v1/rooms/{roomId}` · 요약 · **TC** `계약 3 · 규칙 2 · 수동 1` · **자동화** `4/6`(제외는 분모에서 빼고 `(제외 1)`) · **스크립트** n(이 op 를 부르는 단계가 있는 스크립트 수) · **마지막 호출** 판정 배지 + 시각(이 op 를 부른 가장 최근 단계, API 호출 화면 전송 포함) · 문서화된 에러 코드 수.
- 필터 탭: 모두 · **부르는 스크립트 없음**(어느 스크립트도 안 부르는 op — 선행 문서 기능 트리 2.4 "커버리지 공백" 을 여기서 닫는다) · 미자동화 TC 있음 · 문서화된 에러 없음(스펙에 4xx 예시가 없는 op — 계약 TC 가 성공 하나뿐인 것).
- 머리에 스펙 버전(해시·출처 url/file/cache·읽은 시각)과 REST Docs 링크.

### 5.2 API 상세 `/apis/{operationId}`

위에서 아래로:

1. **머리** — `METHOD path` · 요약 · 도메인 · 버튼 [Swagger 에서 열기](`/swagger#/{domain}/{operationId}`) · [API 호출 화면에서 열기](§5.3 프리필, 기록 남는 쪽) · [Hermes 와 이야기](위젯 context `{"op": id}`) · REST Docs 앵커 링크.
2. **스펙** (Swagger 가 보여주는 것) — 파라미터 표(이름·위치·필수·설명), 요청 예시(JSON), 성공 응답(status 별 예시 접기), 문서화된 에러 코드 표(코드·status·메시지). 전부 `spec.Op` 에 이미 있다.
3. **이 API 의 TC** — 층별 세 묶음. 각 행: TC id(링크) · 제목 · 자동화 배지 · 검증하는 스크립트 · 마지막 결과. 체크박스 + [고른 TC 로 스크립트 초안 생성 (Hermes)] — TC 목록의 폼을 그대로 쓴다(같은 도메인 1~10건 제약 동일).
   - API 계약: `record.operation == id`.
   - 비즈니스 규칙: `binding.operations` 에 id 포함. 거절 TC 는 매핑된 에러 코드도 같이.
   - 수동 작성: `binding.operations` 에 id 포함.
4. **부르는 스크립트** — 행: 스크립트 id · 단계 이름(그 op 를 부르는 단계만) · 스위트 · 마지막 결과. 판별은 단계 `request.method/path` 를 `spec.op_for` 로 매칭. `operations:` 에 선언은 했는데 부르는 단계가 없거나, 부르는데 선언이 없으면 회색 글씨로 "선언과 다름" — 정합성 경고에 얹지는 않는다(범위 유지).
5. **최근 호출** — 이 op 를 부른 단계 최근 20건: 시각 · 실행 기록(링크) · 실행 종류 · 스크립트(또는 "API 호출") · 담당자 · status · 판정 · 소요 ms · 실패면 검증 항목 한 줄. [같은 요청으로 열기] → §5.3. Tossion 의 "지난번 어땠죠" 가 이 표다.
6. **통계**(P5d) — 최근 30일 호출 수 · 통과율 · 평균 소요 · flaky 배지.

### 5.3 API 호출 화면 개선 `/explorer`

Swagger UI(§5.6)가 "그냥 호출" 을 맡으므로 이 화면의 역할은 **기록이 남는 호출 + 스크립트 초안으로 담기** 로 좁아진다. 머리에 한 줄: "기록 없이 만져 보려면 [Swagger]".

- **프리필 링크**: `/explorer?op=X&p.roomId=…&q.page=1&actor=qa-host&body=<urlencoded json>` 을 받아 폼을 채운다. API 상세와 최근 호출, 준비 작업 결과가 이 링크를 만든다. **보내지는 않는다** — 사람이 [보내기].
- **목록**: 도메인별 `<details>` 접기(검색 중엔 전부 펼침).
- 화면 폭: 좁으면 목록이 위로(그리드 1열). 지금 380px 고정 2열이 모바일에서 깨진다.
- 뒤로 미룸: 파라미터 이름별 최근 값(localStorage) · 즐겨찾기 ★. Swagger UI 가 그 쓰임을 흡수하는지 보고 정한다.

### 5.4 준비 작업 `/setup` — 버튼 하나로 테스트 데이터 만들기

토스인컴 Phase 1 의 우리 판. "모집 중인 룸 하나 필요한데" 를 API 세 번 순서대로 부르지 않고 버튼 하나로.

- **스크립트 형식 확장** (선행 문서 §8 에 더한다):
  ```yaml
  - id: setup.room-open
    title: 모집 중인 룸 하나 만들기
    suite: setup                        # 새 스위트. covers 불필요. 커버리지·스프린트 집계에서 제외
    description: qa-host 가 룸을 만들고 확정한다. 만든 데이터는 지우지 않는다 — 제목 [QA] 로 남는다
    actor: qa-host
    inputs:                             # 화면 폼. {{input.title}} 로 치환
      title: { label: 룸 제목, default: "[QA] 준비 작업 룸", required: true }
      capacity: { label: 정원, default: 4 }
    outputs: [roomId]                   # 끝나면 화면에 돌려줄 save 변수
    steps:
      - name: 룸 생성
        request: { method: POST, path: /v1/rooms, body: { title: "{{input.title}}", capacity: "{{input.capacity}}", … } }
        expect: { status: 200, result: SUCCESS }
        save: { roomId: data.roomId }
      - name: 룸 확정
        request: { method: POST, path: /v1/rooms/{{roomId}}/confirm }
        expect: { status: 200 }
  ```
  - `inputs` 는 `setup` 에서만 허용(다른 스위트는 로더가 거부 — 스크립트는 사람 입력 없이 돌아야 한다는 원칙 유지).
  - `outputs` 는 `save` 로 만든 변수 이름만.
- **화면**: 카드 하나 = 스크립트 하나(제목·설명·입력 폼·테스트 계정·담당자·[실행]). 실행 = `create_run(trigger="setup", cases_override=[입력을 넣은 스크립트])`, 큐 안 거치고 `execute_now`(API 호출 화면과 같은 방식). 끝나면 같은 화면에 **결과값 표**(`roomId = …` 복사 버튼) + [API 호출에서 쓰기](§5.3 프리필: `roomId` 최근 값에 넣기) + 실행 기록 링크. 실패면 실패한 단계와 검증 항목이 보인다(실행 상세와 같은 렌더).
- **기록**: 실행 기록에 남고(목록에 보인다 — explorer 처럼 숨기지 않는다), 감사 로그 `run.create`(detail 에 inputs, 값은 마스킹 안 함 — 룸 제목·정원 같은 것뿐), Slack 은 보내지 않는다(준비 작업은 알림 가치가 없다).
- **입력값 보관**: 실행 기록의 스크립트 스냅샷에 치환된 값이 들어가므로 따로 저장하지 않는다.
- **시드 3개**(dev 응답을 실제로 확인하고 적는다): `setup.room-open`(모집 중 룸), `setup.room-with-application`(룸 + qa-guest 신청), `setup.room-confirmed`(참여 확정까지). SSOT 의 룸 상태 전이와 맞춰야 하니 구현 때 `상태-SSOT.yaml` 을 본다.
- **원칙 3.4 와의 관계**: "스크립트가 만든 데이터는 스크립트가 닫는다" 의 **명시적 예외** 다. 준비 작업은 데이터를 남기는 게 목적이다. 제목 접두 `[QA]` 는 유지하고, 사람이 지운다. → §9-2 결정.

### 5.5 통계 배지 (스크립트 · API)

- 스크립트 목록·상세, API 목록·상세에: **최근 20회 통과율**(`pass / (pass+fail)`, skipped·error 제외) · **평균 소요** · **flaky**(최근 10회 안에서 pass↔fail 이 2번 이상 뒤집힘, **같은 스크립트 해시** 안에서만 — 스크립트를 고친 뒤의 결과 변화는 flaky 가 아니다).
- SQL 집계로 매 요청 계산. 규모(수천 행)에서 캐시가 필요 없다. 필요해지면 그때.
- 대시보드에는 안 넣는다(카드가 이미 많다).

### 5.6 Swagger UI `/swagger` — 사람이 그냥 호출해 보는 자리

- **화면**: `swagger-ui-dist` 5.x 를 jsDelivr CDN 에서 버전 고정으로 읽는 HTML 한 장(플랫폼이 서빙, 팀 세션 뒤). 설정: `url: /swagger/openapi.yaml`, `docExpansion: none`, `filter: true`, `persistAuthorization: true`, `tryItOutEnabled: true`, `displayOperationId: true`. 우리 nav 는 위에 한 줄만 얹는다(플랫폼으로 돌아가는 링크 + [qa-host 로 인증] [qa-guest 로 인증] + "여기서 보낸 요청은 기록에 남지 않는다. 남기려면 [API 호출]").
- **스펙 `GET /swagger/openapi.yaml`**: 플랫폼이 캐시한 원본(`qa/spec.py` 가 읽은 그 텍스트)을 파싱해 세 가지만 덧씌운 **파생본**. 정본은 여전히 백엔드 Pages 다.
  1. `servers: [{url: QA_TARGET_BASE_URL}]` 하나만 — 원본의 `localhost:8080` 을 빼서 서버 드롭다운에서 실수로 고르지 못하게. Try it out 은 브라우저에서 dev 로 직접 간다(전제 6).
  2. op 마다 `tags: [<도메인>]` — `catalog.domain_of_path` 로. Swagger 가 도메인별로 접는다(전제 8). `/v1/`·`/actuator/` 밖의 op 는 뺀다(TC 목록과 같은 범위).
  3. op 마다 `x-qa: {tc: n, covered: m, excluded: k, scripts: s, last: {verdict, at, run_id}|null, url: "/apis/<op>"}` — §5.2 와 같은 계산.
- **호출**: 브라우저 → dev 직접. 플랫폼 코드 없음. CORS 허용 전에는 Try it out 이 브라우저 콘솔의 CORS 오류로 실패한다 — 페이지 머리에 "안 되면 백엔드 CORS 허용(qa 오리진) 확인" 한 줄.
- **인증**: 스펙의 `BearerAuth` 가 Swagger [Authorize] 에 뜬다. 토큰은 [qa-host 로 인증] 버튼 → `POST /api/swagger/token {actor, operator}` → 플랫폼이 `ActorPool.token()`(dev-sessions, memberId 는 서버에만) → 응답 `{token}` → 페이지 JS 가 `ui.preauthorizeApiKey("BearerAuth", token)`. 감사 로그 `swagger.token {actor}`. 토큰이 브라우저에 가지만 dev 테스트 계정이고 팀 세션 뒤다 — API 호출 화면이 이미 같은 계정으로 쓰기 op 를 허용하므로 노출 범위가 늘지 않는다. `persistAuthorization` 으로 새로고침해도 남는다.
- **QA 배지 플러그인**: Swagger UI 플러그인 `wrapComponents.OperationSummary` — op 의 `x-qa` 를 읽어 요약 줄 오른쪽에 `TC 5 · 자동화 3/5 · 마지막 pass 09-21` 배지, 클릭하면 `/apis/{op}`. TC 가 0 이면 회색 "TC 없음", 미자동화가 있으면 노란색. 이것이 "Swagger UI 기반으로 뭔가" 의 우리 판이다 — Swagger 를 보다가 "이 API 는 검증이 어디까지 됐나" 를 바로 안다.
- **API 호출 화면과의 역할 나눔**: Swagger = 기록 없이 만져 보기(응답 절단·마스킹 없음, 쓰기 op 도 그대로). API 호출 = 기록 남기고 스크립트 초안으로 담기. 둘 다 같은 스펙·같은 dev·같은 테스트 계정.
- **로컬**: `python3 qa-platform/app.py` 로도 그대로 뜬다(CDN 만 필요, Try it out 은 백엔드가 localhost 오리진을 허용할 때만). 테스트는 스펙 파생(`servers`·`tags`·`x-qa`)과 토큰 버튼(`httpx` 바꿔 끼움)을 확인.

## 6. 데이터 모델 변경

| 대상 | 변경 | 이유 |
| --- | --- | --- |
| `run_steps` | `op_id TEXT` 열 추가(ALTER, 기존 행 NULL) + 인덱스 `(op_id, id)` | 최근 호출·통계를 SQL 한 번으로. 러너가 `add_step` 때 `spec.op_for` 로 채운다. NULL 행(이전 기록)은 조회 때 method/path 로 폴백 매칭 — 백필 안 함 |
| `runs.trigger` | `setup` 추가(`TRIGGERS`) | 준비 작업 실행. `HIDDEN_TRIGGERS` 는 `explorer` 그대로 |
| 스크립트 형식 | `suite: setup` · `inputs` · `outputs` · `{{input.x}}` | §5.4. 로더 검증: setup 외 스위트에 inputs 금지, outputs 는 save 변수만 |
| 브라우저 | Swagger UI 의 `persistAuthorization`(localStorage) | 서버 저장 없음. 최근 값·즐겨찾기는 뒤로 미룸 |
| `events.action` | `swagger.token` 추가 | 토큰 발급만 남긴다. Swagger 호출은 플랫폼을 거치지 않으니 남을 것이 없다 |

카탈로그·TC 레코드·초안·대화 테이블은 그대로다.

## 7. 계약 변경

### 7.1 엔드포인트
- `GET /swagger` (HTML) · `GET /swagger/openapi.yaml` (파생 스펙) · `POST /api/swagger/token` (form/JSON `actor`, `operator` → `{token}`).
- Caddy `@qa`: 추가 없음 — 전부 `handle {}`(팀 세션) 아래로 간다.
- **백엔드(사람 작업, 사용자)**: CORS 허용에 `https://qa.agent.plady.io` 추가(전제 6). 플랫폼 배포와 순서 무관 — 허용 전엔 Swagger 의 Try it out 만 안 된다.
- `GET /apis` · `GET /apis/{operationId}` (HTML) · `GET /api/apis/{operationId}` (JSON, 상세와 같은 묶음).
- `GET /explorer` 가 프리필 쿼리(`p.*`, `q.*`, `actor`, `body`)를 받는다. `POST /explorer/send` 는 그대로.
- `GET /setup` · `POST /setup/run` (form: `case_id`, `input.*`, `operator`).
- MCP 도구 `qa_api_get(operation_id)` → `{op, tcs: {contract, policy, manual}, scripts, recent_calls, stats}`. 도구 14개. `hermes-config-init` 의 `tools.include` 목록에 추가(compose).

### 7.2 이 레포 변경 목록
`qa/spec.py`(원본 텍스트 보관 → 파생 스펙) · `qa/swagger.py`(신규: 파생 스펙·토큰) · `qa/catalog.py`(op → TC 역색인 함수) · `qa/store.py`(op_id 열, 최근 호출·통계 쿼리) · `qa/runner.py`(op_id 기록) · `qa/cases.py`(setup·inputs·outputs 검증) · `qa/templating.py`(`input.` 네임스페이스) · `qa/ui.py`(apis·setup 화면, explorer 개선, 배지, 가이드 절) · `qa/mcp_server.py`(도구 1개) · `app.py`(라우트) · `cases/setup.yaml`(시드) · `compose.ec2.yaml`(tools.include) · `docs/qa-platform.md` §12 · 이 문서 §10.

## 8. 단계

| 단계 | 내용 | 의존 |
| --- | --- | --- |
| **P5a Swagger UI** | `/swagger` 페이지, 파생 스펙(servers·도메인 태그·x-qa), 토큰 버튼, QA 배지 플러그인, nav, 가이드 | op → TC 역색인(P5b 와 공용, 여기서 먼저 만든다). 백엔드 CORS 허용은 사용자 |
| **P5b API 화면** | `run_steps.op_id`, `/apis` 목록·상세, `qa_api_get`, 가이드 | P5a 의 역색인 |
| **P5c API 호출 개선** | 프리필·도메인 접기·반응형·Swagger 링크 | 없음 |
| **P5d 준비 작업** | 형식 확장·로더·`/setup`·시드 3개(dev 확인) | P5c 프리필 |
| **P5e 통계 배지** | 통과율·평균·flaky, 스크립트·API 화면·x-qa | P5b |

각 단계 = 커밋 하나(응집). P5a 를 먼저 배포한다 — 사용자가 Swagger 를 콕 집었고, 팀이 "그냥 호출" 을 어디서 하는지에 따라 P5c 의 남은 범위가 정해진다.

## 9. 결정 필요

0. **Swagger UI 는 붙인다** — 확정(사용자, 2026-09-22). 남은 세부 셋:
   - (a) **CORS 는 백엔드가 연다 — 확정(사용자, 2026-09-22 "CORS 내가 추가할게")**. 플랫폼은 전달 프록시를 만들지 않는다. v2 초안의 `/swagger/proxy` 는 없던 일. 허용 내용은 전제 6.
   - (b) **swagger-ui-dist 는 CDN(jsDelivr, 버전 고정)** — 이미지에 안 넣는다(~1.5 MB, 갱신 번거로움). 오프라인 요구는 없다.
   - (c) **테스트 계정 토큰을 브라우저에 준다** — dev 전용·팀 세션 뒤·API 호출 화면과 같은 노출 범위. 감사 로그엔 발급만 남긴다.
1. **nav 이름과 위치** — "Swagger" · "API" 를 "API 호출" 왼쪽에 둔다(Swagger → API → API 호출 순). "API 호출" 을 없애지는 않는다(기록·초안 담기 경로). 다른 이름이 좋으면 말해 달라.
2. **준비 작업이 만든 데이터를 남긴다** — 원칙 3.4 의 예외. 대안은 "n 시간 뒤 자동 취소" 인데 자동 실행 금지 원칙과 부딪혀 **채택하지 않는다**. 사람이 지우는 것으로 간다(제목 `[QA]`).
3. **최근 값을 서버에 둘까** — 팀 공용 세션이라 서버에 두면 남의 값이 섞인다. localStorage(브라우저별)로 간다. 서버 저장은 하지 않는다.
4. **flaky 기준** — 최근 10회 중 뒤집힘 2회, 같은 스크립트 해시. 너무 민감하면 숫자만 바꾼다(설정값으로 두지 않는다).
5. **API 호출 화면의 최근 값·즐겨찾기는 뒤로** — Swagger 가 "그냥 호출" 을 가져가면 필요 없어질 수 있다. P5a 배포 뒤 결정.

## 10. 리스크

- **Swagger 로 만든 데이터는 누가 만들었는지 모른다**(기록 없음 — 사용자 결정). 제목 `[QA]` 관례와 테스트 계정 2개뿐이라는 범위로 버틴다. 필요해지면 전달 프록시에 "op·status·시각·담당자 쿠키" 한 줄 카운트만 남기는 것은 나중에 켤 수 있다(요청·응답 본문은 안 남김).
- **CORS 허용이 늦으면 Try it out 만 실패**: 나머지(스펙 보기·배지·토큰)는 된다. 화면에 안내 한 줄.
- **CDN 장애·버전 변경**: 버전 고정 URL. CDN 이 죽으면 Swagger 만 안 뜨고 플랫폼은 멀쩡하다.
- **파생 스펙과 정본의 혼동**: `/swagger/openapi.yaml` 은 `info.description` 앞에 "QA 플랫폼 파생본 — servers·tags·x-qa 만 다르다. 정본은 <Pages URL>" 한 줄을 넣는다.

- **경로 매칭 오판**: `/v1/rooms/creation-limit` 대 `/v1/rooms/{roomId}` 같은 충돌은 `op_for` 가 템플릿 세그먼트가 적은 쪽을 고른다(이미 있음). 기록 시점에 op_id 를 박아 두면 스펙이 바뀌어도 과거 기록의 해석이 안 바뀐다(런 불변).
- **준비 작업 남용으로 dev 데이터 누적**: 제목 `[QA]` + 실행 기록으로 누가 언제 만들었는지 남는다. 회원은 QA 계정 2개뿐이라 범위가 좁다.
- **`inputs` 가 스크립트를 "사람 없이 못 도는 것" 으로 만든다**: setup 스위트에만 허용하고, smoke·sanity 선택 화면에는 setup 이 안 뜬다.
- **localStorage 값이 남의 브라우저엔 없다**: 편의값이라 괜찮다. 공유가 필요한 값은 픽스처(SSM)다.
