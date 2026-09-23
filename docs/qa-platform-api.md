# QA 플랫폼 P5 — API 중심 보기 (토스 QA Platform · Tossion 참고)

> 상태: **설계 초안 v3 — 검토 대기** (2026-09-22). v3: 사용자가 토스 화면 캡처를 보여 주며 "커스텀해서 토스처럼" — 토스의 Swagger 모드는 Swagger UI 를 끼운 게 아니라 **자기 화면 안의 Normal/Swagger 토글**(폼 ↔ 보낼 요청 원문)이다. swagger-ui-dist 임베드(v2)는 버린다. 사용자 지시 "토스처럼 Swagger UI 기반으로 뭔가 하거나, API 별로 TC 를 모아서 본다든지". v1 은 Swagger UI 를 안 붙이자고 했으나 사용자가 뒤집었다: **"Swagger UI 는 사람이 그냥 API 호출해 보기 위한 것 — 기록 우회는 괜찮다"**. v2 는 그 결정을 반영한다.
> 선행 문서: [`qa-platform.md`](qa-platform.md)(P0·P1) · [`qa-platform-tc.md`](qa-platform-tc.md)(P2·TC) · [`qa-platform-hermes.md`](qa-platform-hermes.md)(P4). 원칙·용어는 그대로다.
> 참고한 글: [토스인컴 QA Platform](https://toss.tech/article/income-qa-platform) · [Tossion](https://toss.tech/article/tossion).

## 0. 한 줄 요약

둘을 더한다. **① 토스식 호출 카드** — 사람이 그냥 API 를 호출해 보는 자리를 우리 화면 안에 카드로 만든다. 카드마다 **Normal(폼) / Swagger(보낼 요청 원문)** 토글이 있고, 버튼 하나로 보낸다. API 호출 화면과 준비 작업이 같은 카드를 쓴다. Swagger UI 를 끼우지 않으니 CORS 도 필요 없다(요청은 지금처럼 플랫폼이 보낸다). **② API 별로 모아 보기** — 지금 플랫폼은 TC(무엇을 확인하나)·스크립트(어떻게 확인하나)·실행 기록(언제 어땠나)을 따로 보여 주는데, API 하나를 축으로 셋을 한 화면에 모은다 — "`createRoom` 은 TC 가 몇 개고, 어느 스크립트가 부르고, 지난번엔 어땠나". 그 위에 토스인컴 글의 "사소한 마찰"(값 다시 찾기, 순서대로 여러 번 호출)을 버튼 하나짜리 준비 작업으로 줄인다.

## 1. 전제 — 확인한 사실

1. 백엔드 API 문서(GitHub Pages `…/api/branches/dev/`)는 **Spring REST Docs 의 AsciiDoc HTML 한 장 + `openapi/openapi3.yaml`** 이다. Swagger UI 는 없다. 플랫폼은 이미 이 yaml 을 1시간 캐시로 읽는다(`qa/spec.py`).
2. dev 스펙은 op 83개. `tags` 는 79개가 `v1`, 나머지 `Auth`·`get`·`post` — **태그로는 묶을 수 없다.** 묶음은 경로 세그먼트 → 도메인 표(`catalog.PATH_DOMAIN`, 이미 TC 목록이 쓰는 것)로 한다.
3. TC 레코드는 op 를 이미 안다: API 계약 TC 는 `operation`, 비즈니스 규칙 TC 는 `binding.operations`(bindings.yaml), 수동 작성 TC 는 `binding.operations`(manual-tc.yaml 의 `operations`). 스크립트는 `operations:` 선언 + 단계 `request.method/path`. 실행 기록의 단계는 `request.method/path` 만 있고 op id 는 없다 — `spec.op_for(method, path)` 로 경로 템플릿 매칭이 된다(API 호출 화면이 쓰는 함수).
4. 실행 기록은 스크립트 스냅샷(`run_cases.case_yaml`)과 단계별 요청·응답·검증 항목·소요를 이미 남긴다. Tossion 의 "런은 그 시점 스냅샷" 은 이미 돼 있다.
5. API 호출 화면(`/explorer`)은 op 하나를 골라 폼으로 보내고, 전송을 실행 기록(`trigger=explorer`, 목록 기본 숨김)으로 남긴다. 값 기억·즐겨찾기·프리필은 없다.
6. dev 는 `https://qa.agent.plady.io` 오리진의 브라우저 요청을 CORS 로 막는다(`OPTIONS` 프리플라이트·`Origin` 단 GET 모두 403). v2 에서는 이것 때문에 백엔드 CORS 허용이 필요했으나, **v3 은 요청을 지금처럼 플랫폼 서버가 보내므로 CORS 가 필요 없다.** 백엔드 변경 없음(원칙 복귀).
7. 토스 캡처에서 확인한 "Swagger 모드" 의 실체: 카드 안에 `GET /api-internal/v1/…` 메서드 배지 + 경로, **Parameters 표(Name · Value 입력칸)**, **Request Body JSON 편집칸**, 힌트 한 줄, 버튼 하나. Normal 모드는 같은 요청을 라벨 붙은 입력칸 몇 개로 줄인 것. 토글은 우상단 세그먼트(Normal | Swagger). 즉 "Swagger" 는 **보낼 요청을 원문 그대로 보여 주고 고치게 하는 보기** 다.
8. 토스 Tossion 캡처의 실행 결과 화면: 위에 요약 카드 4개(전체·완료·통과·실패, 전주 대비), 도넛(통과율)과 상태별 건수, 아래는 섹션별 진행 막대와 행 목록(정렬·필터·열 선택). 우리 실행 상세는 표만 있다.

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

### 2.3 토스의 "Swagger 모드" 를 그대로 — 우리 화면 안의 토글 (사용자 결정 2026-09-22, v3)
- 토스인컴의 Normal/Swagger 는 한 카드의 두 보기다. **Normal** = "무슨 값을 넣으면 되나" 만 보이는 폼. **Swagger** = "실제로 무엇이 나가나" 가 보이는 요청 원문(메서드·경로·파라미터 표·JSON 본문), 편집 가능. 우리도 이 두 보기를 가진 **호출 카드** 하나를 만들어 API 호출 화면과 준비 작업이 같이 쓴다.
- Swagger UI(`swagger-ui-dist`)는 끼우지 않는다. 캡처를 보면 토스도 안 끼웠다. 끼우면 화면이 둘로 갈라지고(우리 카드 · Swagger 화면), CORS·토큰 노출·CDN 이 따라온다. 카드 방식은 요청이 지금처럼 플랫폼을 거치니 **기록도 그냥 남는다** — 사용자가 "기록 없어도 괜찮다" 고 한 것이지 "없어야 한다" 는 아니므로, 남기는 쪽이 공짜다(API 호출 화면이 이미 그렇게 한다).
- 화면 생김새도 토스를 따른다: 카드, 세그먼트 토글, 라벨 위 입력칸, 필수 표시(빨간 점), 힌트 줄, 가로로 꽉 찬 파란 버튼 하나. 프레임워크 없이 CSS 로 된다(§5.7).

### 2.4 안 가져오는 것
- 실기기 자동화, 공동 편집(아바타·잠금), PR 위험도 AI 판정. 범위 밖.
- AI TC 생성의 3중 검증. 우리 초안 생성은 이미 결정론 검증(§7.2)을 통과한 것만 받는다. 더 얹지 않는다.

## 3. 원칙 (기존 것에 더한다)

1. **새 정본을 만들지 않는다.** API 화면은 OpenAPI·TC 목록·스크립트·실행 기록을 op 로 묶어 **읽기만** 한다. 저장하는 건 단계의 op id 하나(§6).
2. **실행은 여전히 사람이 버튼을 누를 때만.** 준비 작업도 테스트 실행이다 — 실행 기록·감사 로그·Slack 규칙 동일.
3. **브라우저에만 남는 편의값**(최근 입력값·즐겨찾기)은 localStorage 로 두고 서버에 저장하지 않는다. 감사 대상이 아니다.
4. 호출 카드에서 보낸 요청은 지금 API 호출 화면과 같이 실행 기록(`trigger=explorer`, 목록 기본 숨김)으로 남는다. 새 기록 종류를 만들지 않는다.
5. 용어는 화면 용어표(선행 문서 "용어" 절)를 따른다. 새 말은 "Normal/Swagger 보기", "API", "준비 작업", "최근 호출" 넷뿐이고 각각 설명을 붙인다. "Swagger" 는 토스 용례를 따라 "보낼 요청 원문 보기" 라는 뜻으로 쓰고 첫 등장에 설명을 단다.

## 4. 기능 트리

```text
P5 API 중심 보기
├─ 0. 호출 카드 (토스식)                                 API 호출 화면·준비 작업 공용 부품
│   ├─ Normal 보기: 라벨 붙은 입력칸(path·query·본문 최상위 키를 펼침), 필수 표시, 테스트 계정, 버튼 하나
│   ├─ Swagger 보기: METHOD 배지 + 경로 · Parameters 표(Name·Value) · Request Body JSON 편집칸 · 힌트
│   ├─ 두 보기는 같은 값을 공유 (토글해도 입력 유지). 보내기는 플랫폼 서버가 (기록은 지금처럼 explorer 실행)
│   └─ 응답 카드: status 배지 · 소요 · 본문 · [스크립트 단계로 담기] · 카드 위에 QA 배지 "TC 5 · 자동화 3/5 · 마지막 pass" → /apis/{op}
├─ a. API 화면  /apis · /apis/{operationId}            읽기 전용. nav "API"
│   ├─ 목록: 도메인 탭 × 검색 · 행 = METHOD path · 요약 · TC (계약/규칙/수동) · 자동화 n/m · 부르는 스크립트 · 마지막 호출
│   ├─ 필터: 부르는 스크립트 없음(커버리지 공백) · 미자동화 TC 있음 · 문서화된 에러 없음
│   ├─ 상세: 스펙(파라미터·요청 예시·응답·에러 코드) · 이 API 의 TC(층별, 체크 → 초안 생성) · 부르는 스크립트 · 최근 호출 20건
│   └─ MCP 도구 qa_api_get 하나 추가 (상세와 같은 묶음)
├─ b. API 호출 화면을 호출 카드로  /explorer
│   ├─ 왼쪽 op 목록(도메인별 접기·검색·즐겨찾기 ★) · 오른쪽 호출 카드(Normal/Swagger)
│   ├─ 프리필 링크 (/explorer?op=X&p.roomId=…) · 최근 호출에서 [같은 요청으로 열기]
│   ├─ 파라미터 이름별 최근 값 (localStorage datalist) · 응답의 *Id 를 최근 값에 자동 수집
│   └─ 좁은 화면 1열
├─ c. 준비 작업 — 버튼 하나로 테스트 데이터 만들기  /setup
│   ├─ 스크립트 형식: suite setup · inputs(화면 입력) · outputs(돌려줄 값)
│   ├─ 화면: 카드(제목·설명·입력 폼·[실행]) → 실행 기록 → 결과값 표 + [API 호출에서 쓰기]
│   └─ 시드 3개 (모집 중 룸 · 신청 들어온 룸 · 확정된 룸)
├─ d. 통계 배지  스크립트·API 에 최근 20회 통과율 · 평균 소요 · flaky
└─ e. 실행 결과 화면 손보기 (Tossion 식)  요약 카드 4개 · 통과율 도넛 · 도메인별 진행 막대 · 행 필터
```

## 5. 화면

### 5.1 API 목록 `/apis`

- 도메인 탭(TC 목록과 같은 순서·같은 표 `PATH_DOMAIN`) × 검색(operationId · 경로 · 요약). `/v1/*` 와 `/actuator/*` 만(TC 목록과 같은 범위).
- 행: `METHOD /v1/rooms/{roomId}` · 요약 · **TC** `계약 3 · 규칙 2 · 수동 1` · **자동화** `4/6`(제외는 분모에서 빼고 `(제외 1)`) · **스크립트** n(이 op 를 부르는 단계가 있는 스크립트 수) · **마지막 호출** 판정 배지 + 시각(이 op 를 부른 가장 최근 단계, API 호출 화면 전송 포함) · 문서화된 에러 코드 수.
- 필터 탭: 모두 · **부르는 스크립트 없음**(어느 스크립트도 안 부르는 op — 선행 문서 기능 트리 2.4 "커버리지 공백" 을 여기서 닫는다) · 미자동화 TC 있음 · 문서화된 에러 없음(스펙에 4xx 예시가 없는 op — 계약 TC 가 성공 하나뿐인 것).
- 머리에 스펙 버전(해시·출처 url/file/cache·읽은 시각)과 REST Docs 링크.

### 5.2 API 상세 `/apis/{operationId}`

위에서 아래로:

1. **머리** — `METHOD path` · 요약 · 도메인 · 버튼 [호출해 보기](§5.3 프리필) · [Hermes 와 이야기](위젯 context `{"op": id}`) · REST Docs 앵커 링크.
2. **스펙** (Swagger 가 보여주는 것) — 파라미터 표(이름·위치·필수·설명), 요청 예시(JSON), 성공 응답(status 별 예시 접기), 문서화된 에러 코드 표(코드·status·메시지). 전부 `spec.Op` 에 이미 있다.
3. **이 API 의 TC** — 층별 세 묶음. 각 행: TC id(링크) · 제목 · 자동화 배지 · 검증하는 스크립트 · 마지막 결과. 체크박스 + [고른 TC 로 스크립트 초안 생성 (Hermes)] — TC 목록의 폼을 그대로 쓴다(같은 도메인 1~10건 제약 동일).
   - API 계약: `record.operation == id`.
   - 비즈니스 규칙: `binding.operations` 에 id 포함. 거절 TC 는 매핑된 에러 코드도 같이.
   - 수동 작성: `binding.operations` 에 id 포함.
4. **부르는 스크립트** — 행: 스크립트 id · 단계 이름(그 op 를 부르는 단계만) · 스위트 · 마지막 결과. 판별은 단계 `request.method/path` 를 `spec.op_for` 로 매칭. `operations:` 에 선언은 했는데 부르는 단계가 없거나, 부르는데 선언이 없으면 회색 글씨로 "선언과 다름" — 정합성 경고에 얹지는 않는다(범위 유지).
5. **최근 호출** — 이 op 를 부른 단계 최근 20건: 시각 · 실행 기록(링크) · 실행 종류 · 스크립트(또는 "API 호출") · 담당자 · status · 판정 · 소요 ms · 실패면 검증 항목 한 줄. [같은 요청으로 열기] → §5.3. Tossion 의 "지난번 어땠죠" 가 이 표다.
6. **통계**(P5d) — 최근 30일 호출 수 · 통과율 · 평균 소요 · flaky 배지.

### 5.3 API 호출 화면 `/explorer` — 호출 카드로 다시 만든다

오른쪽을 §5.6 의 호출 카드로 바꾼다. 왼쪽 op 목록은 도메인별 접기 + 검색 + 즐겨찾기.

- **프리필 링크**: `/explorer?op=X&p.roomId=…&q.page=1&actor=qa-host&body=<urlencoded json>` 을 받아 카드를 채운다. API 상세와 최근 호출, 준비 작업 결과가 이 링크를 만든다. **보내지는 않는다** — 사람이 버튼을 누른다.
- **최근 값**: path·query 파라미터 **이름별** 최근 값 5개를 localStorage(`qa_recent.<name>`)에 두고 `<datalist>` 로 띄운다. 이름이 같으면 op 가 달라도 공유된다(`roomId` 는 어디서나 `roomId`). 토스인컴의 "최근 userNo 자동 저장".
- **응답에서 자동 수집**: 응답 JSON 의 `data` 안 `*Id`·`id` 값을 그 이름의 최근 값 맨 앞에 넣는다(`data.roomId` → `roomId`). 룸을 만들면 다음 카드에 그 `roomId` 가 바로 뜬다.
- **즐겨찾기**: op 옆 ★(localStorage `qa_fav`), 목록 맨 위 "즐겨찾기" 묶음. 토스인컴의 "자주 쓰는 섹션 위로".
- 화면 폭: 좁으면 목록이 위로(그리드 1열). 지금 380px 고정 2열이 모바일에서 깨진다.

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
- **화면**: 카드 하나 = 스크립트 하나. §5.6 의 호출 카드와 같은 부품 — Normal 보기는 `inputs` 폼(제목·설명·라벨·기본값·필수 점), Swagger 보기는 **단계마다** `METHOD path` + 본문(치환 전 `{{input.title}}` 그대로, 읽기 전용)을 순서대로 — "버튼을 누르면 무엇이 몇 번 나가나" 가 보인다. 테스트 계정·담당자·[실행] 버튼 하나. 토스인컴 "Mock Case 적용" 카드의 프로세스 설명 칸처럼 카드 아래 "이 작업이 하는 일" 세 줄(description). 실행 = `create_run(trigger="setup", cases_override=[입력을 넣은 스크립트])`, 큐 안 거치고 `execute_now`(API 호출 화면과 같은 방식). 끝나면 같은 화면에 **결과값 표**(`roomId = …` 복사 버튼) + [API 호출에서 쓰기](§5.3 프리필: `roomId` 최근 값에 넣기) + 실행 기록 링크. 실패면 실패한 단계와 검증 항목이 보인다(실행 상세와 같은 렌더).
- **기록**: 실행 기록에 남고(목록에 보인다 — explorer 처럼 숨기지 않는다), 감사 로그 `run.create`(detail 에 inputs, 값은 마스킹 안 함 — 룸 제목·정원 같은 것뿐), Slack 은 보내지 않는다(준비 작업은 알림 가치가 없다).
- **입력값 보관**: 실행 기록의 스크립트 스냅샷에 치환된 값이 들어가므로 따로 저장하지 않는다.
- **시드 3개**(dev 응답을 실제로 확인하고 적는다): `setup.room-open`(모집 중 룸), `setup.room-with-application`(룸 + qa-guest 신청), `setup.room-confirmed`(참여 확정까지). SSOT 의 룸 상태 전이와 맞춰야 하니 구현 때 `상태-SSOT.yaml` 을 본다.
- **원칙 3.4 와의 관계**: "스크립트가 만든 데이터는 스크립트가 닫는다" 의 **명시적 예외** 다. 준비 작업은 데이터를 남기는 게 목적이다. 제목 접두 `[QA]` 는 유지하고, 사람이 지운다. → §9-2 결정.

### 5.5 통계 배지 (스크립트 · API)

- 스크립트 목록·상세, API 목록·상세에: **최근 20회 통과율**(`pass / (pass+fail)`, skipped·error 제외) · **평균 소요** · **flaky**(최근 10회 안에서 pass↔fail 이 2번 이상 뒤집힘, **같은 스크립트 해시** 안에서만 — 스크립트를 고친 뒤의 결과 변화는 flaky 가 아니다).
- SQL 집계로 매 요청 계산. 규모(수천 행)에서 캐시가 필요 없다. 필요해지면 그때.
- 대시보드에는 안 넣는다(카드가 이미 많다).

### 5.6 호출 카드 — Normal / Swagger 두 보기 (토스인컴 캡처를 그대로 따른다)

API 호출 화면(§5.3)과 준비 작업(§5.4)이 같은 부품을 쓴다. 서버 렌더 HTML + 작은 JS(토글·값 동기화·최근 값). 프레임워크 없음.

```
┌ 룸 생성  createRoom ─────────────────────────────── [ Normal | Swagger ] ┐
│ POST /v1/rooms · 룸을 만든다                  TC 5 · 자동화 3/5 · 마지막 pass │
│                                                                           │
│  ── Normal ──────────────────────────────────────────────────────────────  │
│  제목 •                       [ [QA] 준비 작업 룸                       ] │
│  정원                         [ 4                                       ] │
│  시작일                       [ 2026-09-25                              ] │
│  questionSetId (JSON)         [ {…}                                     ] │  ← 중첩 값은 그 키만 JSON 칸
│  테스트 계정   (● qa-host  ○ qa-guest  ○ 비로그인)     담당자 [bebe ▾]    │
│                                                                           │
│  ── Swagger ─────────────────────────────────────────────────────────────  │
│  [POST] /v1/rooms                                                         │
│  Parameters                                                               │
│   Name        Value                                                       │
│   (없음)                                                                  │
│  Request Body                                                             │
│  { "title": "[QA] 준비 작업 룸", "capacity": 4, "startDate": "2026-09-25", … } │
│  💡 스펙 예시로 채웠다. 만드는 데이터의 title 은 [QA] 로                    │
│                                                                           │
│  [               보내기 (dev 에 실제로 나간다)                       ]     │
└───────────────────────────────────────────────────────────────────────────┘
┌ 응답  [200]  312 ms · 실행 기록 r-…  ─────────────────────────────────────┐
│ { "result": "SUCCESS", "data": { "roomId": "…" } }                        │
│ [스크립트 단계로 담기 (초안)]   [이 roomId 로 다음 호출 →]                  │
└───────────────────────────────────────────────────────────────────────────┘
```

- **Normal 보기**: path 파라미터 · query 파라미터 · **본문 최상위 키** 를 각각 입력칸으로 펼친다. 값이 문자열·숫자·불린이면 한 줄 입력, 객체·배열이면 그 키만 JSON 칸. 스펙 `required`(파라미터)는 빨간 점. 본문 키의 필수 여부는 REST Docs 스펙에 없어 표시하지 않는다(예시에 있는 키를 전부 보여 준다). 라벨은 스펙 `description` 이 있으면 그것, 없으면 키 이름.
- **Swagger 보기**: 메서드 배지 + 경로(path 값이 채워지면 채워진 경로) · Parameters 표(Name · Value 입력칸, path·query 합쳐서) · Request Body JSON 편집칸 · 힌트 한 줄. 지금 API 호출 화면의 폼이 사실상 이것이다.
- **두 보기는 한 값**: Normal 의 칸을 고치면 Swagger 의 JSON 이 바뀌고, JSON 을 고치면 Normal 칸이 바뀐다(JS 가 양방향 동기화, JSON 이 깨져 있으면 Normal 쪽을 잠그고 빨간 줄). 토글 상태는 localStorage 에 기억.
- **보내기**: `POST /explorer/send`(지금 그대로). 서버가 dev 에 보내고 실행 기록(`trigger=explorer`)으로 남긴다. **CORS 불필요, 토큰이 브라우저에 가지 않음.**
- **QA 배지**: 카드 머리 오른쪽에 `TC n · 자동화 m/n · 마지막 판정` — §5.2 와 같은 계산, 클릭하면 `/apis/{op}`. 이것이 "Swagger 를 보다가 검증 상태를 안다" 의 우리 판이다.
- **응답 카드**: status 배지 · 소요 · 본문(지금과 같은 절단·마스킹) · [스크립트 단계로 담기] · 응답에서 뽑은 id 로 [다음 호출] 링크(§5.3 최근 값).
- **준비 작업에서**: Normal = `inputs` 폼, Swagger = 단계별 요청 목록(읽기 전용). 보내기 = `POST /setup/run`.

### 5.7 화면 생김새 — 토스 캡처에 맞춘 CSS 손질

플랫폼 전체 CSS(`ui.CSS`)를 한 번 손본다. 프레임워크 없이.

- 카드: 흰 배경 · 1px 연한 테두리 · 12px 둥근 모서리 · 20px 안쪽 여백. 지금 카드보다 여백을 키운다.
- 세그먼트 토글(Normal | Swagger, 영구 설정 | 1일간 유지 같은 것): 연한 회색 알약 안에 선택된 쪽만 흰 배경 + 굵게.
- 입력칸: 라벨이 위, 칸은 가로로 꽉, 필수는 라벨 옆 빨간 점, 칸 아래 회색 힌트 한 줄.
- 주 버튼: 가로로 꽉 찬 파란 버튼 하나(카드당 하나). 보조 버튼은 테두리만.
- 메서드 배지: GET 파랑 · POST 초록 · PUT/PATCH 주황 · DELETE 빨강(Swagger 관례).
- 실행 결과 화면(Tossion 캡처): 위에 요약 카드 4개(전체 · 완료 · 통과 · 실패, 통과율 %), 통과율 도넛(SVG 한 개, JS 없음)과 상태별 건수, **도메인별 진행 막대**(스크립트의 `domains` 로 묶어 pass/fail/skip 비율 막대), 아래 행 목록에 판정 필터. "전주 대비" 는 넣지 않는다(스프린트 단위가 맞고, 아직 비교할 데이터가 없다).

## 6. 데이터 모델 변경

| 대상 | 변경 | 이유 |
| --- | --- | --- |
| `run_steps` | `op_id TEXT` 열 추가(ALTER, 기존 행 NULL) + 인덱스 `(op_id, id)` | 최근 호출·통계를 SQL 한 번으로. 러너가 `add_step` 때 `spec.op_for` 로 채운다. NULL 행(이전 기록)은 조회 때 method/path 로 폴백 매칭 — 백필 안 함 |
| `runs.trigger` | `setup` 추가(`TRIGGERS`) | 준비 작업 실행. `HIDDEN_TRIGGERS` 는 `explorer` 그대로 |
| 스크립트 형식 | `suite: setup` · `inputs` · `outputs` · `{{input.x}}` | §5.4. 로더 검증: setup 외 스위트에 inputs 금지, outputs 는 save 변수만 |
| 브라우저 | localStorage `qa_recent.<param>` · `qa_fav` · 보기 토글 | 서버 저장 없음 |

카탈로그·TC 레코드·초안·대화 테이블은 그대로다.

## 7. 계약 변경

### 7.1 엔드포인트
- `GET /explorer` 가 프리필 쿼리(`p.*`, `q.*`, `actor`, `body`, `view=normal|swagger`)를 받는다. `POST /explorer/send` 는 그대로(Normal 에서 보내도 서버는 같은 form — JS 가 Swagger 쪽 JSON 으로 합쳐 보낸다).
- Caddy `@qa`: 추가 없음. **백엔드 변경 없음 — CORS 불필요(v2 의 요청을 거둔다).**
- `GET /apis` · `GET /apis/{operationId}` (HTML) · `GET /api/apis/{operationId}` (JSON, 상세와 같은 묶음).
- `GET /explorer` 가 프리필 쿼리(`p.*`, `q.*`, `actor`, `body`)를 받는다. `POST /explorer/send` 는 그대로.
- `GET /setup` · `POST /setup/run` (form: `case_id`, `input.*`, `operator`).
- MCP 도구 `qa_api_get(operation_id)` → `{op, tcs: {contract, policy, manual}, scripts, recent_calls, stats}`. 도구 14개. `hermes-config-init` 의 `tools.include` 목록에 추가(compose).

### 7.2 이 레포 변경 목록
`qa/catalog.py`(op → TC 역색인 함수) · `qa/store.py`(op_id 열, 최근 호출·통계 쿼리) · `qa/runner.py`(op_id 기록) · `qa/cases.py`(setup·inputs·outputs 검증) · `qa/templating.py`(`input.` 네임스페이스) · `qa/ui.py`(호출 카드 부품, CSS 손질, apis·setup 화면, explorer 재구성, 실행 결과 요약, 배지, 가이드 절) · `qa/mcp_server.py`(도구 1개) · `app.py`(라우트) · `cases/setup.yaml`(시드) · `compose.ec2.yaml`(tools.include) · `docs/qa-platform.md` §12 · 이 문서 §10.

## 8. 단계

| 단계 | 내용 | 의존 |
| --- | --- | --- |
| **P5a 호출 카드** | CSS 손질(§5.7 카드·토글·입력·버튼·메서드 배지), 호출 카드 부품(Normal/Swagger 양방향), API 호출 화면 재구성(목록 접기·즐겨찾기·최근 값·프리필), op → TC 역색인 + QA 배지 | 없음. 사용자가 콕 집은 "토스처럼" 의 본체 |
| **P5b API 화면** | `run_steps.op_id`, `/apis` 목록·상세, `qa_api_get`, 가이드 | P5a 의 역색인 |
| **P5c 준비 작업** | 형식 확장·로더·`/setup`(호출 카드 재사용)·시드 3개(dev 확인) | P5a 카드 |
| **P5d 실행 결과 화면** | 요약 카드 4개·도넛·도메인별 진행 막대·판정 필터 | 없음(P5a 의 CSS) |
| **P5e 통계 배지** | 통과율·평균·flaky, 스크립트·API 화면 | P5b |

각 단계 = 커밋 하나(응집). P5a 를 먼저 배포해 팀이 카드에서 호출해 보게 한 뒤 나머지를 간다.

## 9. 결정 필요

0. **Swagger UI 임베드는 하지 않고, 토스식 Normal/Swagger 카드로 간다** — v3(사용자 캡처 기준). 따라서 v2 의 백엔드 CORS 허용·CDN·토큰 주입은 전부 **필요 없다**. 사용자가 CORS 를 넣기로 했던 것은 거둬도 된다(넣어도 해는 없다).
1. **nav 이름과 위치** — "API" 를 "API 호출" 왼쪽에 둔다(API → API 호출 순). 다른 이름이 좋으면 말해 달라.
2. **준비 작업이 만든 데이터를 남긴다** — 원칙 3.4 의 예외. 대안은 "n 시간 뒤 자동 취소" 인데 자동 실행 금지 원칙과 부딪혀 **채택하지 않는다**. 사람이 지우는 것으로 간다(제목 `[QA]`).
3. **최근 값을 서버에 둘까** — 팀 공용 세션이라 서버에 두면 남의 값이 섞인다. localStorage(브라우저별)로 간다. 서버 저장은 하지 않는다.
4. **flaky 기준** — 최근 10회 중 뒤집힘 2회, 같은 스크립트 해시. 너무 민감하면 숫자만 바꾼다(설정값으로 두지 않는다).
5. **Normal 보기에서 본문 키를 어디까지 펼치나** — 최상위 키만, 중첩은 그 키의 JSON 칸. 더 깊이 펼치면 폼이 스펙 구조에 끌려간다. 토스 캡처도 최상위(User ID, Case ID, Flag Key/Value)만 펼쳤다.
6. **CSS 손질 범위** — 플랫폼 전체를 한 번에(카드·토글·입력·버튼·배지). 화면마다 따로 하면 섞인다. 색은 지금 팔레트 유지, 주 버튼만 파랑.

## 10. 리스크

- **Normal ↔ Swagger 양방향 동기화 버그**: JSON 이 깨지면 Normal 을 잠그고 표시, 보내기는 항상 Swagger 쪽 JSON 을 기준으로(서버는 지금처럼 `body` 하나만 받는다). 값이 두 벌이 아니라 한 벌이라 어긋날 수 없다.
- **CSS 손질이 기존 화면을 흔든다**: 클래스 이름은 유지하고 값만 바꾼다. 브라우저 프리뷰로 화면 9개를 전부 한 번씩 본다.

- **경로 매칭 오판**: `/v1/rooms/creation-limit` 대 `/v1/rooms/{roomId}` 같은 충돌은 `op_for` 가 템플릿 세그먼트가 적은 쪽을 고른다(이미 있음). 기록 시점에 op_id 를 박아 두면 스펙이 바뀌어도 과거 기록의 해석이 안 바뀐다(런 불변).
- **준비 작업 남용으로 dev 데이터 누적**: 제목 `[QA]` + 실행 기록으로 누가 언제 만들었는지 남는다. 회원은 QA 계정 2개뿐이라 범위가 좁다.
- **`inputs` 가 스크립트를 "사람 없이 못 도는 것" 으로 만든다**: setup 스위트에만 허용하고, smoke·sanity 선택 화면에는 setup 이 안 뜬다.
- **localStorage 값이 남의 브라우저엔 없다**: 편의값이라 괜찮다. 공유가 필요한 값은 픽스처(SSM)다.

## 11. 구현 결과

### 11.1 P5a — 호출 카드 (2026-09-22)

- **들어간 것**: `ui.explorer` 를 다시 썼다. 왼쪽 op 목록은 도메인별 `<details>`(선택된 도메인·검색 중엔 펼침) + ☆ 즐겨찾기(localStorage `qa_fav`, 맨 위 "즐겨찾기" 묶음). 오른쪽은 호출 카드 — 머리(요약·operationId·메서드 배지·경로, Normal | Swagger 세그먼트), QA 배지 한 줄, Normal 보기(path·query 입력칸 + 본문 최상위 키 칸, 중첩은 JSON 칸, 예시 타입 힌트), Swagger 보기(메서드 배지 + 채워진 경로, Parameters 표, Request Body JSON), 발(테스트 계정 라디오·담당자·꽉 찬 파란 [보내기]). `ui.EXPLORER_JS` 가 토글·양방향 동기화·최근 값·즐겨찾기·응답 id 수집을 한다.
- **값의 정본은 하나**: path·query 는 Normal 의 `name=p_*/q_*` 칸이 진짜고 Swagger 표의 칸은 `data-mirror` 거울. 본문은 Swagger 의 `name=body` JSON 칸이 진짜고 Normal 의 `data-bk` 칸은 그 키만 읽고 쓴다. JSON 이 깨지면 Normal 을 잠그고 빨간 줄로 이유를 보여 준다. 서버 계약(`POST /explorer/send` 의 `op`·`p_*`·`q_*`·`body`·`actor`·`operator`)은 그대로다.
- **QA 배지**: `Catalog.by_operation()`(op → TC id, 세 층 모두) + `App.op_qa()` → "TC 15 · 자동화 2/14 (제외 1) · 마지막 pass 09-21". 클릭하면 `/catalog?op=<id>` — TC 목록에 op 필터를 더했다(도메인 무시, 그 API 에 걸린 TC 만). P5b 의 `/apis/{op}` 가 생기면 링크를 그쪽으로 옮긴다.
- **프리필**: `/explorer?op=X&p.roomId=…&q.size=…&actor=qa-host&body=<json>&view=swagger`. 응답 카드의 [같은 요청으로 다시 열기] 가 실행 기록의 요청에서 path 파라미터를 되찾아(`ui._path_param_values`) 이 링크를 만든다.
- **최근 값**: 파라미터 이름별 localStorage `qa_recent.<name>` 5개 → `<datalist>`, 비어 있으면 최근 값으로 채움. 응답 `data` 안(깊이 3까지)의 `*Id`·`id` 를 자동으로 기억하고 응답 카드 아래에 "다음 호출을 위해 기억한 값" 한 줄.
- **CSS 손질**(플랫폼 전체): 카드 12px 모서리·18/20px 여백, 주 버튼 파랑(`--info`) + `.wide`, 입력칸 8px 모서리·포커스 링, `.field`(라벨 위·필수 빨간 점·힌트), `.seg` 세그먼트, `.m.get/post/put/patch/delete` 메서드 배지, `.xgrid` 2열→860px 아래 1열, nav 가로 스크롤(좁은 화면에서 글자가 세로로 깨지던 것).
- **설계에서 달라진 것**: 응답 카드를 호출 카드 **위** 에 둔다(§5.6 그림은 아래). 보내고 돌아왔을 때 긴 Normal 폼을 지나치지 않고 응답이 바로 보이는 쪽이 토스인컴의 "결과를 바로 확인" 에 맞다.
- **검증**: 테스트 8건 추가(카드 렌더·정본 하나·프리필·목록 묶음·역색인 세 층·QA 요약·op 필터), 전체 63건. 브라우저: createRoom 카드에서 Normal 칸 → JSON 반영(숫자 타입 유지), 깨진 JSON → Normal 잠김·복구, roomDetail 거울 칸 → 진짜 칸·경로 갱신, 즐겨찾기 토글, `GET /v1/terms` 실전송 → 응답 200·termsId 기억·다시 열기 링크, 모바일 폭 1열, 콘솔 오류 없음.
- **남은 것(P5b 로)**: 배지 링크를 `/apis/{op}` 로, 최근 호출 20건 표.

### 11.2 P5b — API 별로 모아 보기 (2026-09-22)

- **들어간 것**: nav "API" → `/apis` 목록(도메인 탭 × 검색 × 필터 모두 / 부르는 스크립트 없음 / 미자동화 TC 있음 / 문서화된 에러 없음). 행 = 메서드·경로·요약·operationId · TC 수(계약·규칙·수동) · 자동화 m/n(제외) · 부르는 스크립트 수 · 마지막 호출(판정·status·시각·실행 기록 링크) · 에러 코드 수. `/apis/{operationId}` 상세 = 머리(QA 배지, [호출해 보기]·[Hermes 와 이야기]·[REST Docs]) · 스펙(파라미터·요청 예시·성공 응답·에러 코드) · 이 API 의 TC(층별, 체크 → 초안 생성 폼 재사용) · 부르는 스크립트(단계 이름, "선언만"/"선언 없음" 표시) · 최근 호출 20건(시각·실행 기록·스크립트 또는 API 호출·판정·status·소요·[같은 요청으로 열기]). `GET /api/apis/{op}` JSON 이 같은 묶음.
- **데이터**: `run_steps.op_id`(ALTER + 인덱스). 러너가 단계마다 `App.op_of(method, path)`(= `spec.op_for`)로 채운다 — 치환 전 템플릿으로 한 번, 치환 뒤 경로로 한 번 더(더 정확). 옛 행(NULL)은 `store.calls_unresolved(300)` 을 조회 때 method/path 로 매칭해 섞는다 — 백필 없음. 실제로 배포 전 기록(09-21 실행)의 termsList 호출 4건이 폴백으로 잡혔다.
- **집계**: `App.api_overview()`(목록 한 번에), `App.api_detail(op)`(상세·JSON·MCP·대화 첨부 공용), `App.scripts_by_op()`(단계 method/path 로 판별 + `operations:` 선언 따로). `Catalog.by_operation()` 은 P5a 것.
- **Hermes**: MCP 도구 `qa_api_get(operationId)` 추가(14개, compose `tools.include` 갱신). 요청·응답 본문은 안 넘기고 UUID 는 마스킹. 채팅 위젯 첨부에 `{"op": id}` 종류 추가(`/chat/new?op=`, 첨부 텍스트가 `qa_api_get` 을 가리킨다).
- **REST Docs 링크**: 절 앵커는 AsciiDoc 규칙대로 제목에서 만든다(`ui.restdocs_anchor`: 소문자·기호→`_`·앞 `_`). 같은 제목이 둘이면 `_2` 가 붙는데 그건 모른다 — 안 맞으면 문서 맨 위가 열린다. 문서 URL 은 `QA_SPEC_DOCS_URL`(기본: 스펙 URL 의 `/openapi/` 앞까지).
- **호출 카드 QA 배지** 링크를 `/catalog?op=` 에서 `/apis/{op}` 로 옮겼다(op 필터는 남겨 둔다).
- **검증**: 테스트 6건 추가(op_id 기록·최근 호출·NULL 폴백·목록 집계·상세 구조·화면·MCP·대화 첨부), 전체 69건. 브라우저: `/apis?domain=room` 목록·필터, `createRoom` 상세(TC 15 층별), `termsList` 상세(부르는 스크립트 1·최근 호출 4건 중 폴백 3건), 콘솔 오류 없음.
- **남은 것**: 통계(통과율·평균·flaky)는 P5e. 목록의 "마지막 호출" 은 op_id 있는 행 우선, 없으면 폴백 300건 안에서만.

### 11.3 P5c — 준비 작업 (2026-09-22)

- **들어간 것**: 스크립트 형식에 `suite: setup` · `inputs`(이름 → `{label, default, required, hint}`, 스칼라 축약 허용) · `outputs`(어떤 단계의 `save` 변수여야 함) · `{{input.x}}` 치환. 로더가 검증: inputs 는 setup 에서만, 단계가 쓰는 `{{input.*}}` 는 전부 선언돼야 하고, outputs 는 save 에 있어야 한다. setup 은 covers 가 없어도 된다. nav "준비 작업" → `/setup`: 스크립트마다 카드(제목·설명·Normal 입력 폼 | Swagger 단계별 요청 원문 읽기 전용·담당자·꽉 찬 [실행]). `POST /setup/run` → `cases.bake_inputs` 가 입력을 스크립트에 박아(값 전체면 기본값의 타입을 지키고, 문자열 일부면 끼움) `create_run(trigger="setup", cases_override, notify=False)` + `execute_now`. 스냅샷 `input_values` 에 입력값이 남고 감사 로그 `setup.run`. 끝나면 `/setup?run=` 결과 카드: 판정 · 돌려준 값 표(복사 버튼) · 단계별 판정·오류 · [API 호출 카드로]. `App.setup_outputs` 가 스냅샷의 save 경로를 단계 응답에서 다시 읽는다(러너 변수는 저장하지 않으므로). 결과값은 JS 가 localStorage `qa_recent.<name>` 에 넣어 API 호출 카드의 최근 값으로 뜬다.
- **시드 `cases/setup.yaml` 3개**: `setup.room-open`(룸 생성, 입력: 제목·최소/최대 인원·며칠 뒤) · `setup.room-with-application`(생성 + qa-guest 신청, 출력 roomId·applicationId) · `setup.room-confirmed`(생성 → 신청 → 방장 수락 → 진행 확정). 요청 본문은 dev 에서 통과한 `room.yaml` sanity 와 같다. **셋째는 dev 에서 아직 안 돌렸다** — 최소 인원 2 를 방장 포함으로 세는지에 따라 확정이 E1421 로 막힐 수 있고, 그러면 SSOT 의 인원 계산을 확인한다(카드 설명에 적어 두었다).
- **로컬에서 못 본 것**: 테스트 계정(SSM `qa-actors`)이 로컬에 없어 실행은 `skipped` 로 끝난다. 결과 카드·값 표·복사·최근 값 기억은 가짜 dev 로 테스트했고, 실제 dev 는 배포된 플랫폼에서 버튼을 눌러 본다.
- **설계에서 달라진 것**: `/runs/new` 의 스위트 묶음(sanity·smoke·manual)에 setup 은 안 뜬다(설계대로). 실행 기록 목록에는 보인다(explorer 처럼 숨기지 않음). 대시보드 카운트는 setup 을 포함한다.
- **검증**: 테스트 6건 추가(로더 3·박기·실행·화면), 전체 75건. 브라우저: 카드 3장(단순한 것부터), Normal/Swagger 토글, 실행 → 결과 카드(로컬은 skipped), 콘솔 오류 없음.

### 11.4 P5d — 실행 결과 화면 (2026-09-22)

- **들어간 것**: 실행 상세(`/runs/{id}`)의 스크립트별 결과 위에 요약을 얹었다(`ui.run_summary`). 요약 카드 4개(전체 스크립트 · 실행 완료 · 통과(통과율 %) · 실패·오류(skip·취소 수)), 통과율 도넛(SVG 하나, JS 없음, 80% 이상 초록 · 50% 이상 노랑 · 그 아래 빨강), 상태별 건수 범례, **도메인별 진행 막대**(스냅샷의 `domains` 기준 — 그때 돌린 스크립트가 여러 도메인이면 각각 센다, 통과/실패·오류/skip/대기 색 구간), 판정 필터 탭(모두 · 통과 · 실패·오류 · skip → `?verdict=`).
- 통과율 분모는 전체 스크립트(skip 포함) — Tossion 캡처와 같다. "전주 대비" 는 넣지 않았다(설계대로).
- 도메인은 실행 기록의 스크립트 스냅샷(`case_yaml`)에서 읽는다 — 지금 파일이 아니라 그때 돌린 것 기준(런 불변). 로더 검증을 거치지 않고 YAML 의 `domains` 만 읽는다 — covers 가 필수이기 전(P2 이전)의 옛 스냅샷은 검증에 걸리지만 도메인은 있다.
- **검증**: 테스트 2건(요약 렌더·필터), 전체 77건. 브라우저: 릴리스 QA 실행 기록에서 카드·도넛·도메인 막대·필터 확인, 콘솔 오류 없음.
- **남은 것**: P5e 통계 배지(통과율·평균 소요·flaky, 스크립트·API 화면).

### 11.5 P5e — 통계 배지 (2026-09-22)

- **들어간 것**: `ui.stats_of(rows)` — 최신순 결과 목록에서 최근 N회 통과율(pass / (pass+fail+error), skip 제외) · 평균 소요 · 불안정(flaky) 을 낸다. `ui.stats_badge` 가 "최근 20회 통과율 80% · 평균 312 ms · 불안정 (flaky)" 한 줄로 그린다(툴팁에 통과·실패·skip 수와 불안정의 뜻). 스크립트 목록(마지막 결과 칸 아래)·스크립트 상세(실행 이력 제목 옆)·API 목록(마지막 호출 칸 아래)·API 상세(배지 옆)에 붙였다.
- **불안정(flaky) 기준**: 최근 10회 안에서 통과↔실패·오류가 2번 이상 뒤집힘. 스크립트는 **가장 최근 회차와 스크립트 해시가 같은 회차만** 본다(고친 뒤 결과가 달라진 것은 불안정이 아니다). API 는 여러 스크립트가 섞이므로 해시 조건 없이 본다.
- **조회**: `store.recent_case_results(20)` / `store.recent_op_results(20)` — SQLite 윈도 함수(`ROW_NUMBER() OVER (PARTITION BY …)`)로 한 번에. API 쪽은 `op_id` 가 박힌 단계만(옛 NULL 행 제외 — 배지 힌트에 "이 배포 이후 기록만" 을 적었다). 캐시 없음.
- **설계에서 달라진 것**: 없음. 숫자(20회·10회·2번)는 코드 상수 `FLAKY_WINDOW`·`FLAKY_FLIPS` — 설정값으로 두지 않았다(§9-4).
- **검증**: 테스트 4건(통과율·skip 제외·불안정 규칙(해시·창)·배지 문구·조회), 전체 81건. 브라우저: 스크립트 목록·상세, API 목록·상세에서 배지 확인.
- **P5 전체 정리**: P5a 호출 입력 폼(Normal/Swagger) → P5b API 별 모아 보기 → P5c 테스트 데이터 만들기 → P5d 실행 결과 요약 → P5e 통계 배지. 토스 두 글에서 가져오기로 한 것(§2.1·§2.2)은 전부 들어갔다. 배포 뒤 사람이 볼 것: 테스트 데이터 만들기 첫째 시드 실행(roomId 반환), 셋째 시드(확정)의 E1421 여부, API 상세 REST Docs 링크 앵커가 맞는지.

### 11.6 QA 데이터 정리 — 백엔드 dev 전용 API 연동 (2026-09-23)

- **백엔드**: [moimyeon-backend PR #135](https://github.com/100Thieves-team/moimyeon-backend/pull/135) (MOI-534, dev 머지) 가 `/v1/dev/…` 아래에 dev 전용 QA API 를 열었다 — `listQaData`(`GET /v1/dev/qa-data`: `[QA]` 룸 + QA 생성 회원 목록) · `deleteQaRoom`(`DELETE /v1/dev/rooms/{id}`, 딸린 20개 테이블까지 하드 삭제) · `deleteQaData`(일괄, `hostMemberId`·`includeMembers`) · `resetQaMember`(`POST /v1/dev/members/{id}/reset`) · `deleteQaMember` · `createQaMember`(테스트 회원 생성 + 토큰) · `rescheduleQaRoom`(시작 시각 변경) · `completeQaResumeSummary`(이력서 요약 강제). 지우기는 제목 `[QA]` 만(E2201), 프로파일 `local·local-dev·dev` 에서만 빈 등록, 인증 필요(dev-sessions 토큰).
- **플랫폼에 들어간 것**: `qa/qadata.py` — qa-host 토큰으로 dev API 를 부르는 클라이언트(`snapshot`·`delete_room`·`delete_all`·`reset_member`·`delete_member`). "테스트 데이터 만들기" 화면 아래 **"QA 데이터 정리"** 절: `[QA]` 룸 표(id·제목·상태·방장(테스트 계정 이름으로, 남은 UUID 는 앞 8자리)·딸린 행 수·시각·[삭제]), [`[QA]` 룸 전부 삭제], 테스트 계정별 [초기화], QA 테스트 회원 표([삭제]). 버튼마다 확인창. 결과는 지운 행 수로 플래시. `POST /setup/cleanup {action, target, operator}` → `App.qa_data_action` → 감사 로그 `qa_data.delete_room | delete_all | reset | delete_member`(ok·status·total·rooms·error). **실행 기록에는 안 남긴다** — 검증이 아니라 정리라서.
- **TC·API 화면에서 제외**: `/v1/dev/` op 는 계약 TC 를 만들지 않고(`catalog.build`) API 모아 보기에도 안 나온다(`api_overview`). API 호출 화면에는 도메인 `qa-dev` 로 남는다(손으로 부를 수 있게 — 시작 시각 변경·회원 생성·요약 강제는 여기서).
- **쓸 수 없을 때**: API 문서에 `listQaData` 가 없거나(배포 전) 테스트 계정이 없으면 절에 이유만 보인다. 로컬은 후자.
- **아직 안 한 것**: `rescheduleQaRoom`(확정 룸의 시작 시각을 과거로 → 진행 화면까지 공개 API 로 도달)과 `createQaMember`·`completeQaResumeSummary` 를 테스트 데이터 만들기 카드로 감싸기. setup 스크립트가 dev-sessions 대신 만든 회원 토큰을 쓰려면 `actor` 개념 확장이 필요하다 — 별도 설계. PR 에 적힌 미결(임의 회원 토큰이면 누구나 삭제 가능, 비QA 룸의 참여 행도 초기화 때 지워짐)은 백엔드 결정 사항.
- **검증**: 테스트 5건(제외·스냅샷과 이름 대응·삭제/초기화/일괄 호출과 감사 로그·거절 처리·불가 사유·화면·실제 스펙에 op 존재), 전체 90건. 실제 dev 삭제는 배포 뒤 사람이 첫 번째 [QA] 룸으로 확인한다.

### 11.7 시작 시각 변경 · QA 테스트 회원 만들기 (2026-09-23)

- **시작 시각 변경**은 테스트 데이터 만들기 카드 두 장으로 감쌌다(`cases/setup.yaml`). `setup.room-reschedule` — 있는 `[QA]` 룸의 시작 시각을 입력(며칠 뒤·시각)만큼 옮긴다(`POST /v1/dev/rooms/{id}/schedule`, 본문 `{{date:N}}T{{time}}`). `setup.room-ready-to-start` — 생성 → 신청 → 수락 → 확정 → 어제로 옮기기까지 한 번에. 진행 이후 화면(출석·클로징·후기)에 공개 API 실제 경로로 닿는 용도. 러너는 qa-host 토큰으로 dev 전용 API 를 부른다(인증 필요).
- **QA 테스트 회원 만들기**는 스크립트가 아니라 플랫폼 동작이다 — 만든 회원을 **테스트 계정 이름**으로 등록해야 해서. 카드에서 이름(예: qa-3)을 넣고 [회원 만들기] → `POST /v1/dev/members` → 응답의 memberId·닉네임·이메일을 `qa_members` 표에 이름과 함께 저장(accessToken 은 버린다) → 감사 로그 `qa_data.create_member`. 이후 `ActorPool.mapping()` 이 SSM 고정 계정에 이 표를 합쳐 주므로 스크립트 `actor: qa-3`, API 호출 화면 드롭다운, 테스트 데이터 카드에서 바로 쓴다. 토큰은 필요할 때 dev-sessions 로 받는다(PR 이 "실제 가입 경로"라 dev-sessions 가 통한다). 정리 표에서 회원을 지우면 `qa_members` 에서도 빠진다.
- **토큰 마스킹**: 러너가 응답 본문의 `accessToken`·`refreshToken`·`token` 값을 `***` 로 바꿔 기록한다 — API 호출 화면에서 회원 생성 API 를 직접 불러도 토큰이 실행 기록에 남지 않는다.
- **못 하는 것**: Hermes 초안 검증(`drafts.validate`)은 아직 SSM 고정 계정만 안다 — 초안에서 `actor: qa-3` 을 쓰면 경고가 난다. 필요해지면 검증에도 합친다.
- **검증**: 테스트 4건(회원 생성→테스트 계정→토큰, 중복·형식 거절, 삭제 시 목록 제거, 마스킹, 카드 로드·실행·결과값, 화면), 전체 94건. 실제 dev 는 배포 뒤 회원 하나 만들어 API 호출 화면 드롭다운에 뜨는지, 확정 룸에 시작 시각 카드를 돌려 `startAt` 이 어제로 오는지 본다.
