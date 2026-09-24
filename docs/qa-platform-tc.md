# QA 플랫폼 P2 설계 — 검증 기준(테스트 조건) 관리: 기획 문서가 기준이다

- 이슈: [MOI-483](https://linear.app/100-thieves/issue/MOI-483/qa-자동화-플랫폼-구축) 후속 (P2)
- 선행 문서: [`qa-platform.md`](qa-platform.md) (P0·P1 설계와 런북). 이 문서는 그 §7.3·§12·§13 을 구체화한다.
- 상태: **결정 확정, 구현 진행** (2026-09-21). 사용자가 결정을 위임해 §13 은 전부 권장안으로 확정했다.
- 용어: 스크립트가 로그인에 쓰는 dev 전용 QA 회원은 **테스트 계정**이라 부른다(YAML·코드 키는 `actor` 그대로).
- 작성: 2026-09-21

## 0. 한 줄 요약

smoke·sanity 스크립트가 "무엇을 검증하는지"의 정본을 스크립트 자신이 아니라 **llm-wiki 의 기획 문서**(PRD `raw/product/*.md`, `상태-SSOT.yaml`)와 **백엔드 API 계약**(OpenAPI)에 두고, 플랫폼은 거기서 **테스트 조건 카탈로그를 결정론적으로 파생**한다. 스크립트는 `covers:` 로 어떤 테스트 조건을 덮는지 선언하고 플랫폼이 그 선언을 검증한다. 그 위에 커버리지 화면, 기준 변경(드리프트) 표시, 근거를 강제한 Hermes 초안 생성, 탐색기, 위키 보고서 발행을 얹는다.

## 1. 전제 — 조사로 확인한 사실

| # | 사실 | 설계에 미치는 영향 |
| --- | --- | --- |
| 1 | `wiki/policy/_src/상태-SSOT.yaml`(v0.4): gates 66 / checks 190 / commands 46 / transitions 43 / cascades 5. `render_tests.py --json` 이 이미 **거절 테스트 조건 190 + 성공 테스트 조건 40 = 230건**을 뽑는다(gate 나 transition 이 없는 command 6건 — `C.member.logout`·`C.room.change_block` 등 — 은 성공 테스트 조건이 안 나온다) | 정책 테스트 조건 파생 로직을 새로 쓰지 않는다. 있는 것을 쓴다 |
| 2 | SSOT gate check 의 `error` 필드는 **전부 비어 있다**(렌더 결과 `TBD`). SSOT 는 사용자 문구(`message`)만 안다 | 거절 테스트 조건의 기대 에러 코드는 SSOT 에서 못 얻는다 → 다른 층(OpenAPI)이 필요 |
| 3 | SSOT `command`(예 `C.room.create`)와 OpenAPI `operationId`(예 `createRoom`)를 **잇는 정보가 어디에도 없다** | 바인딩(§4.4)이 필요하고, 그것은 사람이 유지하는 작은 파일이다 |
| 4 | OpenAPI(dev 브랜치, 83 ops) 중 63 ops 에 에러 예시가 문서화돼 있고 distinct 코드 55개. 예시 이름이 `createRoom-e1402-min-participants` 처럼 코드까지 담는다 | 계약 테스트 조건(`op.createRoom:E1402`)을 결정론적으로 파생할 수 있다 |
| 5 | 같은 정책이 두 문서에서 **다르게** 적혀 있는 경우가 있다. `createRoom` 의 E1402 예시는 인원 `min 1 / max 6`, SSOT `D.room.headcount_range_valid` 는 `2 이상 / 8 이하` | 두 층을 한 층으로 합치면 안 된다. 불일치는 **표시 대상**이다(§6.4) |
| 6 | 현재 스크립트 13건의 `source:` 는 자유 텍스트다. 그중 `G.room.cancel` 은 **SSOT 에 없는 id** 다(룸 취소 게이트는 `G.participation.cancel` 계열) | 근거 참조는 검증돼야 한다 → `covers` 는 카탈로그와 대조한다(§5) |
| 7 | PRD 는 `## 4. 기능 명세` / `### 4.x` 절 구조. SSOT `source` 는 `PRD/{문서} §{절}` 또는 `DEC-nnn`. 문서 링크는 `https://wiki.agent.plady.io/raw/product/<slug>/`(팀 세션 뒤) | PRD 절 본문은 절 번호로 기계 추출이 된다 |
| 8 | `policy-renderer` 는 `render_wiki.py` 만 60초 주기로 돌린다. `wiki/policy/*.md` 는 `managed_by: harness`, `source: "상태-SSOT.yaml@<hash>"`, `sync-manifest.json` 에 `source_hash` | 기준 버전 식별자로 SSOT 내용 해시(12자리)를 그대로 쓴다 |
| 9 | `qa-platform` 컨테이너는 `qa-data` 볼륨만 갖는다. `wiki-data`(team-wiki-v2 체크아웃, `/workspace`)는 llm-wiki·wiki-ui·wiki-data-sync·policy-renderer 가 마운트한다 | 플랫폼이 기획 문서를 읽으려면 볼륨 마운트 또는 MCP 가 필요(§4.5 결정) |
| 10 | Hermes 는 llm-wiki read 도구 16개 + `wiki_apply`(운영자 opt-in) 를 갖는다. 플랫폼은 Hermes 를 chat completions 로만 부른다(P1 진단) | 초안 생성에서 근거를 Hermes 가 도구로 찾게 할지, 플랫폼이 넣어 줄지 결정(§7, 권장은 후자) |
| 11 | `drafts` 테이블은 P0 에서 만들어 두었고 비어 있다. `runs.meta` 는 JSON 이라 열 추가 없이 확장된다 | 스키마 변경은 최소(§10) |

## 2. 문제 — 지금 무엇이 없는가

1. **기준이 스크립트 안에 있다.** 스크립트가 스스로 "이게 맞다"고 말한다. 스크립트가 통과해도 기획이 바뀌었으면 틀린 것을 통과시키는 것이다.
2. **얼마나 덮는지 모른다.** 룸 도메인 gate 14개 중 스크립트가 건드리는 것이 몇 개인지 아무도 답할 수 없다.
3. **기준이 바뀌어도 모른다.** SSOT 가 9/20 에 바뀌었지만 어떤 스크립트가 영향을 받는지 알 길이 없다.
4. **AI 초안에 근거가 없다.** §7.3 은 "PRD + SSOT + OpenAPI 를 모아 Hermes 에 넘긴다"고 했지만 무엇을 어떻게 모으고 무엇으로 검증하는지가 없다.

## 3. 원칙 (P0·P1 원칙에 더한다)

| 원칙 | 뜻 |
| --- | --- |
| **정본은 위키, 플랫폼은 파생** | 테스트 조건을 플랫폼 DB 에 만들지 않는다. SSOT·PRD·OpenAPI 에서 **같은 입력이면 같은 출력**이 나오는 함수로 뽑는다. 기준을 고치려면 위키(또는 백엔드 스펙)를 고친다 |
| **선언은 검증된다** | 스크립트의 `covers:` 는 카탈로그에 실재하는 id 여야 하고, 계약 테스트 조건을 덮는다고 하면 단계의 method·path·기대 코드가 실제로 그 계약과 맞아야 로드된다 |
| **기준 변경은 알리기만** | 위키가 바뀌면 배지를 띄운다. 스크립트를 자동으로 고치거나 런을 자동으로 돌리지 않는다(사용자 결정 ①) |
| **카탈로그 계산은 읽기다** | 파생은 요청 시 계산해 소스 해시로 캐시한다. 런이 아니므로 사람 트리거 원칙에 걸리지 않는다. 실행(런·탐색기 전송·초안 생성·발행)은 여전히 버튼이다 |
| **AI 산출물은 근거를 달고 검증 겹을 지난다** | 초안의 모든 스크립트는 `covers` 가 있어야 하고, 플랫폼의 결정론 검증을 통과한 것만 스크립트 초안에 들어간다. 승인 없이 스위트에 들어가는 스크립트는 없다(§7.3 유지) |
| **분모를 속이지 않는다** | 커버리지 분모는 전체 테스트 조건이다. 자동화 못 하는 테스트 조건은 사유를 적은 제외 목록으로 뺀다. 제외도 화면에 보인다 |

## 4. 테스트 조건 카탈로그

### 4.1 세 층

| 층 | 원천 | 파생 | 건수(현재) | 답하는 질문 |
| --- | --- | --- | --- | --- |
| **정책 테스트 조건** | `상태-SSOT.yaml` | `render_tests.py::cases()` 그대로 | 거절 190 + 성공 40 | 기획이 정한 규칙이 지켜지는가 |
| **계약 테스트 조건** | OpenAPI `openapi3.yaml`(dev) | 플랫폼 파생: op 별 성공 응답 1건 + 문서화된 에러 코드마다 1건 | 성공 81 + 에러 199(op·코드 쌍) | API 가 문서대로 응답하는가 |
| **서술 테스트 조건** | PRD 절 중 SSOT 로 형식화되지 않은 요구(탐색 정렬·필터, 문구, 화면 흐름 등) | 사람이 `qa-platform/catalog/prd-tc.yaml` 에 적는다 | 0 에서 시작 | SSOT 밖의 기획 요구가 지켜지는가 |

정책 테스트 조건과 계약 테스트 조건은 **합치지 않는다**(전제 5). 하나의 스크립트 단계가 둘 다를 덮을 수 있고, 그것이 "기획대로 API 가 거절한다"의 정확한 표현이다.

### 4.2 id 체계

| 층 | 형식 | 예 | 뜻 |
| --- | --- | --- | --- |
| 정책·거절 | `{gate}#{key}` | `G.room.create#duplicate-slot-left` | 게이트의 그 검사가 걸려 거절된다. key 는 SSOT 검사의 `key`(2026-09-23~). 예전에는 순서 번호(`G.room.create#8`)였고, 옛 번호는 `catalog/tc-aliases.yaml` 로 새 id 로 읽힌다 — [policy-ssot-split.md](policy-ssot-split.md) §4.5. 이 문서의 아래 예시들은 옛 번호 형식 그대로 둔다 |
| 정책·성공 | `{command}` | `C.room.create` | 게이트를 다 통과해 전이가 일어나고 `writes` 가 반영된다 |
| 계약·성공 | `op.{operationId}:{status}` | `op.createRoom:200` | 문서화된 성공 응답 |
| 계약·오류 | `op.{operationId}:{code}` | `op.createRoom:E1402` | 문서화된 에러 코드 |
| 서술 | `PRD.{slug}.{절}#{n}` | `PRD.룸-탐색.4.2#1` | PRD 절 안의 n 번째 수동 테스트 조건 |

id 는 원천의 id 를 그대로 잇는다. 플랫폼이 번호를 새로 매기지 않으므로 SSOT 에 검사가 **끼어들면** 뒤 번호가 밀린다. 이것은 결함이 아니라 드리프트 신호다(§6.3) — 그 게이트를 덮는 스크립트는 다시 봐야 한다.

### 4.3 테스트 조건 레코드

```yaml
id: G.room.create#8
layer: policy            # policy | contract | prd
kind: reject             # reject | success | response
domain: room             # SSOT owner → 도메인 슬러그(render_tests OWNER_PKG 재사용)
title: 룸 생성 거절 — 같은 회사·공고·직무의 활성 룸은 3개까지 만들 수 있어요
expect_hint:             # 층마다 다르다. 스크립트 검증에 쓴다
  cond: D.member.duplicate_slot_left >= 1
  message: 같은 회사·공고·직무의 활성 룸은 3개까지 만들 수 있어요
  must_pass_first: [subject 가 로그인한 회원인가, …]   # 앞 7개 검사
binding:                 # §4.4 에서 붙는다. 없으면 null
  operation: createRoom
  error_code: E1427
source: [PRD/룸 생성 §4.7]           # SSOT 가 말한 근거
prd: [{doc: 룸 생성, section: "4.7", url: https://wiki.agent.plady.io/raw/product/룸-생성/}]
hash: 3f9a…              # 레코드 내용 해시(제목·expect_hint·binding). 드리프트 판정 단위
catalog: {ssot: 4bc51d05edce, openapi: 9e1c…, bindings: a7…}   # 이 레코드가 나온 원천 버전
```

계약 테스트 조건의 `expect_hint` 는 `{method, path, status, error_code, example}`. 서술 테스트 조건은 사람이 쓴 `given/when/then` 문장이다.

### 4.4 바인딩 — SSOT 와 API 를 잇는 유일한 사람 손

기획 명세와 API 는 1:1 이 아니다(사용자 확인). command 하나가 op 여러 개에 걸치거나(일괄 생성), op 하나가 command 여러 개를 실현하거나(취소 = 참여 취소의 특수형), API 가 아예 없는 command(시스템 전이·미구현)도 있다. 바인딩은 이 관계를 **있는 그대로** 적는 표이고, 못 잇는 것은 못 잇는 대로 카탈로그에 "API 없음" 으로 남는다.

`qa-platform/catalog/bindings.yaml`:

```yaml
# SSOT command → OpenAPI operationId. 없는 command 는 "API 없음(시스템 전이·미구현)"으로 카탈로그에 표시된다.
commands:
  C.room.create: createRoom
  C.room.create_batch: createRoom          # 여러 command 가 같은 op 를 가리켜도 된다
  C.application.submit: submitRoomApplication
  C.application.withdraw: withdrawRoomApplication
  C.participation.cancel: cancelRoom          # 방장의 룸 취소는 SSOT 에서 참여 취소의 특수형
# 게이트 검사 → 에러 코드. SSOT `error` 가 비어 있는 동안만 여기 둔다.
checks:
  G.room.create#1: E1102        # 비로그인
  G.room.create#8: E1427        # 활성 룸 3개
  G.room.create#9: E1425        # 참여 슬롯
```

- 왜 SSOT 에 안 넣나: 에러 코드는 백엔드 구현 사실이고 SSOT 는 기획 정본이다. SSOT `error` 필드가 이미 예약돼 있으니 **팀이 그 필드를 채우기로 하면** 플랫폼은 SSOT 값을 우선하고 이 파일의 `checks` 는 비워 간다. 그때까지는 이 파일이 임시 정본이다(결정 §13-2). 구현됨: SSOT `error` 가 있으면 그것을 쓰고(`binding.error_source: ssot`), bindings 와 다르면 경고로 알린다.
- 바인딩이 틀리면: 로더가 (a) operationId 실재, (b) 에러 코드가 그 op 의 OpenAPI 예시에 존재하는지 검사해 화면에 경고로 띄운다. 예시에 없으면 스펙 누락일 수 있으므로 오류가 아니라 경고다.
- 바인딩은 스크립트와 같은 PR 흐름으로 리뷰된다.

### 4.5 파생을 어디서 하나 — 결정 필요 (§13-1)

| 안 | 내용 | 장점 | 단점 |
| --- | --- | --- | --- |
| **A. team-wiki-v2 렌더러** | `policy-renderer` 가 `render_tests.py --json` 도 돌려 `wiki/policy/tc-catalog.json` 을 위키에 커밋. 플랫폼은 그 파일을 읽는다 | 파생이 위키 쪽 한 곳. 위키에서도 테스트 조건 표를 볼 수 있다 | (1) 플랫폼이 어차피 볼륨 또는 HTTP 로 위키 파일을 읽어야 한다 (2) team-wiki-v2 와 이 레포 두 곳을 고쳐야 하고 배포 순서가 생긴다 (3) JSON 은 위키 "페이지"가 아니라 MCP `wiki_content_read` 로 못 읽고, wiki-ui(Hugo)가 JSON 을 그대로 서빙하는지도 보장이 없다 (4) 계약 테스트 조건·바인딩·PRD 절 추출은 어차피 플랫폼 몫 |
| **B. 플랫폼이 위키 볼륨을 읽기 전용 마운트** (`wiki-data:/wiki:ro`) | 플랫폼이 `/wiki/wiki/policy/_src/상태-SSOT.yaml` 과 `/wiki/raw/product/*.md` 를 직접 읽고, `/wiki/tools/policy-renderer/render_tests.py` 의 `cases()` 를 **import 해서** 정책 테스트 조건을 뽑는다 | 파생 코드는 여전히 team-wiki-v2 한 곳(복제 없음). team-wiki-v2 무변경, 배포 순서 없음. PRD 절 본문·git HEAD 도 같은 볼륨에서 얻는다. 실패 시 마지막 성공 캐시 유지 | 위키 레포의 파이썬을 플랫폼 프로세스가 실행한다 — 그러나 `policy-renderer` 가 이미 같은 볼륨의 같은 코드를 60초마다 실행하므로 신뢰 경계가 새로 생기지 않는다. `cases()` 시그니처가 바뀌면 카탈로그 파생이 실패한다 → UI 에 오류로 보이고 캐시로 버틴다 |
| C. MCP 로 읽기 | `wiki_content_read` 로 SSOT 를 읽는다 | 볼륨 불필요 | SSOT 는 `_src/` 의 yaml 이라 페이지가 아니다. PRD 는 읽히지만 절 추출은 결국 플랫폼 몫. 기각 |

**권장: B.** compact 전에는 A 쪽으로 기울었으나, 플랫폼이 위키 볼륨을 마운트하지 않는다는 사실(전제 9)과 A 의 단점 (3)(4) 를 확인하고 바꿨다. "파생 로직 단일화"는 B 에서도 지켜진다(같은 `cases()` 를 import). 위키에도 테스트 조건 표를 보이고 싶으면 후속으로 `policy-renderer` 가 `render_tests.py --list` 를 `wiki/policy/테스트-케이스.md` 로 렌더하면 되고, 그것은 이 설계와 독립이다.

볼륨 읽기 시 주의: `wiki-data-sync` 가 `git pull` 로 파일을 바꾸는 순간 읽으면 반쪽 파일이 올 수 있다. 파싱 실패 시 1초 후 1회 재시도, 그래도 실패면 마지막 성공 캐시를 쓰고 화면에 "기준 읽기 실패(시각)" 를 표시한다. 락 디렉터리(`/wiki/.git/llm-wiki.lock`)는 **잡지 않는다**(읽기 전용이고, 잡으면 렌더러·싱크를 막는다).

### 4.6 카탈로그 계산과 캐시

- 입력 버전: `ssot_hash`(SSOT 내용 sha256[:12], 렌더러와 같은 규칙), `openapi_hash`(스펙 본문 해시, `QA_SPEC_URL` 1시간 캐시는 P1 그대로), `bindings_hash`, `prd_tc_hash`, `wiki_head`(`/wiki/.git/refs/heads/<branch>`, 표시용).
- 캐시: `/data/catalog/<ssot>-<openapi>-<bindings>-<prdtc>.json`. 입력 버전이 같으면 재계산하지 않는다. 마지막 성공본 포인터 `latest.json`.
- 트리거: 화면 요청 시 입력 버전만 확인(파일 stat + 해시)하고 바뀌었을 때만 계산. 계산은 수 초 이내(230 + 280 레코드)라 동기로 한다.

## 5. 스크립트 ↔ 테스트 조건 연결

### 5.1 `covers` 필드

```yaml
- id: room.creation-limit
  suite: sanity
  covers: [C.room.create, op.createRoom:200, G.room.create#8, op.createRoom:E1427]   # 스크립트 수준: 합집합
  source: ["PRD/룸 생성 §4.7"]        # 유지 — 사람이 읽는 근거 메모. 검증하지 않는다
  steps:
    - name: 활성 룸 3개 생성
      covers: [C.room.create, op.createRoom:200]
      …
    - name: 4번째는 E1427
      covers: [G.room.create#8, op.createRoom:E1427]
      request: { method: POST, path: /v1/rooms, … }
      expect: { status: 409, error_code: E1427 }
```

- 스크립트 `covers` 는 단계 `covers` 의 합집합이어야 한다(로더가 채우거나 검증). 단계 단위가 정확하고, 스크립트 단위는 목록 화면용이다.
- **필수 여부**: `smoke`·`sanity` 는 `covers` 1개 이상 필수, `manual` 은 선택(결정 §13-3). 기존 13건은 이번 단계에서 마이그레이션하고, 그 과정에서 유령 참조(`G.room.cancel`)를 바로잡는다.

### 5.2 로더 검증(결정론)

| 검사 | 실패 시 |
| --- | --- |
| `covers` 의 모든 id 가 카탈로그에 실재 | 로드 오류(스크립트 목록에 빨간 줄, 스위트에서 제외). 카탈로그를 못 읽은 상태에서는 "미검증" 으로 표시하고 실행은 허용(기준 읽기 실패가 QA 를 막으면 안 된다) |
| 계약·오류 테스트 조건(`op.X:E####`)을 덮는 단계: method·path 가 그 op 와 일치하고 `expect.error_code` 가 같다 | 로드 오류 — "덮는다"는 선언이 거짓이다 |
| 계약·성공 테스트 조건(`op.X:2xx`)을 덮는 단계: method·path 일치, `expect.status` 가 2xx | 로드 오류 |
| 정책·거절 테스트 조건(`G.x#n`)을 덮는 단계: 바인딩에 에러 코드가 있으면 `expect.error_code` 와 같아야 한다 | 경고(바인딩이 틀렸을 수도 있다) |
| 정책·성공 테스트 조건(`C.x`)을 덮는 스크립트: 바인딩된 op 를 호출하는 단계가 있다 | 경고 |

path 비교는 OpenAPI 템플릿(`/v1/rooms/{roomId}`)과 스크립트 path(`/v1/rooms/{{roomId}}`)를 세그먼트 단위로 맞춘다(치환 표현은 와일드카드).

## 6. 화면

### 6.1 기준 화면 `/catalog`

- 도메인 탭(room · application · participation · member · resume · question · guestbook · review · attendance · platform) × 층 필터 × "미커버만".
- 행: 테스트 조건 id · 제목 · 근거(PRD 링크, 절) · 바인딩(op, 코드) · 덮는 스크립트 · **마지막 판정**(`store.last_verdicts` 를 스크립트→테스트 조건으로 펼침) · 상태 배지(커버 / 미커버 / 제외 / API 없음).
- `/catalog/{id}`: 레코드 전문, 원천 발췌(SSOT 검사 블록 그대로, OpenAPI 응답 예시 그대로, PRD 절 본문 앞 40줄), 덮는 스크립트와 단계 링크, 이 테스트 조건이 걸린 최근 런 5개.
- 버튼: [초안 생성](§7) — 미커버 테스트 조건을 골라 누른다.

### 6.2 커버리지

대시보드 카드 하나: 도메인 × 층 매트릭스 `덮음 / 전체 (제외 n)`. 클릭하면 `/catalog` 필터.

제외 목록 `qa-platform/catalog/exclusions.yaml` — 사유 필수:

```yaml
- id: G.room.autocancel_not_started#3     # D.room.start_deadline_passed
  reason: 시간 경과 조건. dev 에서 시계를 돌릴 수 없다. 단위 테스트(백엔드 레포) 영역
- pattern: "C.*"                          # actor: system 인 command
  when: actor == system
  reason: 시스템 전이는 API 로 트리거되지 않는다
```

제외는 화면에 회색으로 보이고 분모 옆에 `(제외 n)` 으로 남는다. 숨기지 않는다.

### 6.3 드리프트

- 카탈로그를 계산할 때마다 직전 캐시와 레코드 해시를 비교해 `changed / added / removed` 를 낸다. 스크립트 화면과 런 확인 화면(`/runs/new`)에서, 덮는 테스트 조건이 `changed` 또는 `removed` 인 스크립트에 배지 **"근거 변경됨 · SSOT 4bc51d05 (2026-09-20)"** 를 붙인다.
- 런 생성 시 `runs.meta.catalog = {ssot, openapi, bindings, wiki_head}` 를 기록한다. 런 상세 상단에 "이 런의 기준: SSOT@…, OpenAPI@…" 가 보인다. 과거 런의 판정을 지금 기준으로 다시 해석하지 않는다(런 불변 원칙).
- 배지를 지우는 방법은 하나다: 스크립트를 고쳐(또는 그대로 두기로 하고) `covers` 옆에 `reviewed: {ssot: 4bc51d05, by: bebe, at: 2026-09-22}` 를 적어 PR. 플랫폼은 그 해시 이후의 변경만 다시 배지로 띄운다.

### 6.4 불일치 표시

바인딩된 테스트 조건에서 두 층이 어긋나면 `/catalog` 에 노란 줄: (a) 바인딩 코드가 그 op 의 OpenAPI 예시에 없다, (b) 게이트가 있는데 op 에 4xx 예시가 하나도 없다. 전제 5 의 인원 범위(1~6 vs 2~8)처럼 **값** 이 다른 경우는 자동으로 못 잡는다 — 그건 스크립트가 잡는 것이고(실패 → 진단), 이 화면은 구조 불일치만 잡는다. 범위를 넓히지 않는다.

## 7. Hermes 초안 생성

### 7.1 입력 — 플랫폼이 근거를 조립한다

사람이 `/catalog` 에서 같은 도메인의 미커버 테스트 조건 1~10건을 고르고 [초안 생성]. 플랫폼이 다음을 **한 프롬프트로** 조립한다.

1. 고른 테스트 조건 레코드 전문(§4.3). 거절 테스트 조건은 `must_pass_first` 포함 — "앞 검사를 통과시켜 두어야 이 검사가 걸린다"가 스크립트 단계 설계의 핵심이다.
2. 바인딩된 op 의 OpenAPI 발췌: path·method·요청 예시·응답 예시(성공 1 + 에러 전부).
3. PRD 절 본문: 테스트 조건 `source` 의 `PRD/{문서} §{절}` 을 `/wiki/raw/product/{slug}.md` 에서 `### {절}` 헤딩부터 다음 헤딩 전까지 추출. 절당 최대 80줄.
4. 사용 가능한 테스트 계정 이름과 픽스처 **키** 목록(값 없음), 치환 문법, 스크립트 형식(§8 of 선행 문서), 잘 만든 예시 스크립트 1개(`room.creation-limit`).
5. 규칙: 출력은 YAML 스크립트 목록만. 각 스크립트·단계에 `covers` 필수이며 요청한 테스트 조건 id 의 부분집합. 쓰기 스크립트는 자기가 만든 것을 닫는 단계로 끝난다. 제목 접두 `[QA]`. 모르는 값은 지어내지 말고 `TODO:` 로 남긴다.

Hermes 의 위키 도구를 쓰지 않는 이유: 도구 호출은 어떤 문서를 읽을지가 매번 달라 재현이 안 되고, 근거 없는 초안을 걸러낼 기준이 사라진다. 플랫폼이 넣어 준 근거만으로 쓰게 하면 "근거 = 프롬프트에 있던 것" 이 성립하고, 검증 겹(§7.2)이 그 근거와 대조할 수 있다(결정 §13-8).

세션 키 `qa-draft-<hex>`, `stream: false`, 타임아웃은 진단보다 길게(120초). 모델은 `HERMES_MODEL`.

### 7.2 결정론 검증 — 통과한 것만 스크립트 초안에

| # | 검사 | 결과 |
| --- | --- | --- |
| 1 | YAML 파싱, `cases._validate` 스키마 | 실패 → 스크립트 버림, 사유 기록 |
| 2 | `covers` ⊆ 요청 테스트 조건, 비어 있지 않음 | 실패 → 버림 |
| 3 | §5.2 로더 검증 전부(op 실재, path·method·코드 일치) | 로드 오류급 → 버림, 경고급 → 초안에 경고 첨부 |
| 4 | `actor`·`fixture` 키 실재 | 실패 → 버림 |
| 5 | 쓰기 op(POST/PUT/PATCH/DELETE)를 부르는 스크립트에 정리 단계(취소·철회 계열 op) 존재 | 실패 → 경고(정리 불가한 흐름도 있다) |
| 6 | 스크립트 id 가 기존과 충돌하지 않음, 제목 `[QA]` 접두 | 실패 → 자동 수정 후 경고 |

결과: 초안 1건 = 스크립트 1건. `drafts` 행에 `yaml`, `tc_ids`, `validation`(경고 목록 JSON), `prompt_hash`(조립 근거의 해시 — 같은 근거로 다시 만들면 비교 가능), `status=draft`. 버린 것은 `events` 에 `draft.rejected_by_validation` 으로 사유와 함께 남긴다(AI 가 무엇을 틀리는지가 나중에 프롬프트를 고치는 근거다).

### 7.3 스크립트 초안 `/drafts`

- 목록: 상태(draft / checked / approved / rejected), 덮는 테스트 조건, 경고 수, 만든 사람·시각.
- 상세: YAML(편집 가능한 textarea), 검증 결과, 근거 테스트 조건 링크, 버튼 [한 번 실행해 보기] / [승인] / [반려].
- **[한 번 실행해 보기]** = 이 초안 하나를 `trigger=draft-check`, `suite=manual` 런으로 실행(런 기록·마스킹·스냅샷 전부 P0 그대로). 초안 상태 → `checked`, 런 링크 첨부.
- **[승인]** = 상태 `approved`, 화면에 "이 YAML 을 `qa-platform/cases/<domain>.yaml` 에 붙여 PR" 안내 + 복사 버튼. **플랫폼은 git 에 쓰지 않는다**(스크립트 정본은 리뷰를 거친 PR, 선행 문서 §7.3-4). 승인이 곧 스위트 편입이 아니다.
- 모든 버튼은 `events`: `draft.generate`(tc_ids, 모델, prompt_hash), `draft.check`, `draft.approve`, `draft.reject`(사유).

## 8. 탐색기 `/explorer` (Swagger 모드)

- 왼쪽: OpenAPI op 목록(태그·검색). 오른쪽: 선택한 op 의 폼 — path 파라미터, query, body(요청 예시로 미리 채움, 편집 가능), 테스트 계정 드롭다운(없음 / qa-host / qa-guest).
- [보내기] → 응답 status·본문·소요 시간 표시. **모든 전송은 런이다**: `trigger=explorer`, 스크립트 id `explorer.<operationId>`, 단계 1개, `expect` 없음(판정 `pass` 가 아니라 `n/a`). 새 테이블 없이 마스킹·절단·감사 로그·이력 화면을 그대로 얻는다. 목록 화면에서는 기본 숨김(필터로 보기).
- [스크립트 단계로 담기] → 방금 요청·응답을 단계 YAML 로 변환해 `drafts` 에 `source=explorer` 로 추가(기대는 방금 받은 status·error_code 로 채움, `covers` 는 비워 두고 사람이 채움 — 검증 §7.2 는 승인 전에 돈다).
- 쓰기 op 허용 범위: dev 대상이고 테스트 계정이 QA 회원 2명뿐이므로 허용한다. 단 목데이터 회원은 테스트 계정 목록에 없다(결정 §13-7).

## 9. 위키 보고서 발행

- 런 상세의 [위키에 발행] 버튼(사람만, 기본 안 씀 — 선행 문서 §13-3 유지). 대상: `sprint-smoke`·`release` 런.
- 페이지: `wiki/qa/<YYYY-Www>-<trigger>.md`, front matter `type: doc, managed_by: harness, source: "qa-platform run <id>"`, 본문 = 런 요약(대상·sha·운영자·판정·카운트) + 도메인 × 층 커버리지 표 + 실패 스크립트와 Hermes 진단 + 기준 버전(SSOT·OpenAPI 해시). 개인 식별값(회원 UUID)은 마스킹.
- 경로: llm-wiki MCP `wiki_apply` 를 내부(`mcp-proxy:18765`, 기존 `MCP_BEARER_TOKEN`)로 호출. 플랫폼에 최소 MCP 클라이언트(JSON-RPC over HTTP, stdlib)가 필요하다. `wiki_apply` 의 정확한 인자(변경 집합 형식, `expected_head`, raw create-only 규칙)는 **구현 전에 llm-wiki 코드로 확인**한다 — 이 문서는 형식을 단정하지 않는다.
- 볼륨에 직접 쓰고 `wiki-data-sync` 가 커밋하게 하는 방법은 쓰지 않는다: 락 규약과 `wiki_apply` 의 검증(링크·frontmatter)을 우회한다.
- `events`: `run.publish`(페이지 경로, 커밋 해시).

## 10. 데이터 모델 변경

| 대상 | 변경 |
| --- | --- |
| 카탈로그 | DB 아님. `/data/catalog/*.json` 캐시 + `latest.json` |
| `drafts` | 열 추가: `tc_ids`(json), `validation`(json), `prompt_hash`, `run_id`(check 런). `status` 값에 `checked` 추가 |
| `runs.meta` | `catalog`(입력 버전), `explorer`(op, 테스트 계정) 키 추가. 열 추가 없음 |
| `events.action` | `catalog.refresh`(계산이 일어난 시각·버전, 사람 행위는 아니지만 기준 변경 추적용), `draft.*`, `explorer.send`, `run.publish` |
| 스크립트 YAML | `covers`(스크립트·단계), `reviewed`(선택) |
| 레포 파일 | `qa-platform/catalog/bindings.yaml`, `exclusions.yaml`, `prd-tc.yaml` |

## 11. 계약 변경

| 항목 | 변경 |
| --- | --- |
| `compose.ec2.yaml` / `compose.yaml` qa-platform | `wiki-data:/wiki:ro` 마운트, `QA_WIKI_DIR=/wiki`, `QA_WIKI_BRANCH`(기본 `main`, `wiki-data-sync` 의 `WIKI_SYNC_BRANCH` 와 같은 값), `LLM_WIKI_MCP_URL=http://mcp-proxy:18765/mcp`, `LLM_WIKI_MCP_BEARER_TOKEN=${MCP_BEARER_TOKEN:-}`(발행에만) |
| 라우트 | `/catalog`, `/catalog/{id}`, `/drafts`, `/drafts/{id}`, `POST /drafts/generate`, `POST /drafts/{id}/(check\|approve\|reject)`, `/explorer`, `POST /explorer/send`, `POST /runs/{id}/publish`. 전부 팀 세션 뒤, 운영자 필수. `/health` 에 `catalog: {ssot, openapi, records, age_s}` 추가 |
| SSM | **추가 없음** |
| 백엔드 레포 | **변경 없음** |
| team-wiki-v2 | **변경 없음**(안 B). 팀이 SSOT `error` 를 채우기로 하면 그때 그쪽 작업 |
| 로컬 | `.claude/launch.json` qa-platform 에 `QA_WIKI_DIR=./wiki-workspace` — 로컬 체크아웃으로 그대로 돈다 |

## 12. 단계

| 단계 | 내용 | 산출 |
| --- | --- | --- |
| **P2a 기준** | 볼륨 마운트, 카탈로그 파생(정책·계약·서술) + 캐시, 바인딩·제외 파일, `covers` 로더 검증, 기존 13건 마이그레이션, `/catalog`, 커버리지 카드, 드리프트 배지, 런 meta 에 기준 버전 | 여기까지가 "테스트 조건 관리"의 본체. 이것만으로 사용자 요청의 핵심이 닫힌다 |
| **P2b 초안** | 근거 조립, Hermes 호출, 결정론 검증, 스크립트 초안, draft-check 런 | P2a 에 의존 |
| **P2c 탐색기** | op 폼, 전송=런, 단계로 담기 | P2a 의 스펙 파서에 의존. 스크립트 초안 재사용 |
| **P2d 발행** | MCP 클라이언트, `wiki_apply` 호출, 보고서 렌더 | 독립. `wiki_apply` 계약 확인이 선행 |

P2a 를 먼저 배포해 팀이 `/catalog` 를 보고 바인딩·제외를 채우는 동안 P2b 를 만든다. 커밋은 단계·파일 단위로 응집한다.

## 13. 결정 (확정 — 권장안 채택)

| # | 질문 | 확정 | 버린 대안 |
| --- | --- | --- | --- |
| 1 | 정책 테스트 조건 파생 위치 | **B** 플랫폼이 위키 볼륨을 읽기 전용 마운트하고 `render_tests.cases()` 를 import | A team-wiki-v2 렌더러가 JSON 커밋(§4.5) |
| 2 | SSOT command↔op 바인딩과 에러 코드 위치 | 지금은 `qa-platform/catalog/bindings.yaml`. SSOT `error` 가 채워지면 SSOT 우선 | 처음부터 SSOT 에 `api:`/`error:` 추가(기획 문서에 구현 사실이 들어간다) |
| 3 | `covers` 필수 범위 | smoke·sanity 필수, manual 선택. 기존 13건 지금 마이그레이션 | 전부 선택(커버리지가 거짓이 된다) |
| 4 | 커버리지 분모 | 전체 테스트 조건, 제외는 사유 필수 파일, 화면에 표시 | 자동화 가능한 것만 분모(분모를 플랫폼이 정하게 된다) |
| 5 | 승인된 초안의 행선지 | YAML 복사 → 사람이 PR. 플랫폼은 git 에 안 쓴다 | 플랫폼이 GitHub PR 생성(쓰기 토큰·브랜치 관리가 생긴다) |
| 6 | 위키 보고서 | `wiki/qa/` 스프린트·릴리스 런만, 버튼만(기존 결정 유지) | 매 런 발행(위키 소음) |
| 7 | 탐색기에서 쓰기 op | 허용, 테스트 계정은 QA 회원 2명만 | GET 만 |
| 8 | 초안 생성 시 Hermes 위키 도구 | 안 씀. 플랫폼이 근거를 조립해 넣는다 | Hermes 가 `wiki_content_read` 로 직접 찾는다 |
| 9 | 서술 테스트 조건(`prd-tc.yaml`) | P2a 에 파일과 로더만, 내용은 팀이 채운다. Hermes 로 PRD 절에서 뽑는 것은 P3 | P2 에서 Hermes 추출까지 |

## 14. 리스크와 대응

- **테스트 조건이 많다**(정책 230 + 계약 280). 기본 뷰는 도메인 하나 + 미커버만. 전체는 필터를 풀어야 보인다.
- **`render_tests.cases()` 시그니처 변경.** import 실패·예외 → `/health.catalog.error`, 화면 상단 오류, 마지막 캐시로 동작. 이 레포 테스트에 "현재 team-wiki-v2 체크아웃으로 카탈로그가 파생된다" 를 넣어 CI 에서 먼저 잡는다(`wiki-workspace` 가 레포 안에 있다).
- **볼륨 교체 순간 읽기.** 재시도 1회 + 캐시(§4.5).
- **바인딩 노후.** OpenAPI 에서 op 가 사라지면 그 바인딩은 `/catalog` 경고. 스크립트는 어차피 로더 검증에서 걸린다.
- **초안 품질.** 검증에서 버려진 비율을 `events` 로 남기고, 높으면 프롬프트(§7.1 5번)를 고친다. 자동으로 재시도하지 않는다.
- **원칙 ① 오해.** 카탈로그 재계산은 읽기라 자동이다. 런·전송·초안·발행은 전부 버튼이다. 이 구분을 §3 에 못 박았다.

## 15. 구현 결과 (2026-09-21)

P2a~P2d 전부 구현·로컬 검증했다. 테스트 27건(`python3 -m unittest discover -s qa-platform/tests`). 실제 `wiki-workspace` 체크아웃과 스펙 발췌 픽스처로 카탈로그 파생·대조 회귀를 CI 에서 잡는다.

### 15.1 무엇이 들어갔나

| 단계 | 파일 | 요지 |
| --- | --- | --- |
| P2a 기준 | `qa/wiki.py` `qa/spec.py` `qa/catalog.py` `catalog/{bindings,exclusions,manual-tc}.yaml` | 정책 230 + 계약 278 + 서술 4 = 512 테스트 조건. 위키 볼륨 읽기 전용 마운트(안 B), `render_tests.cases()` import. 캐시·변경 이력 `/data/catalog/` |
| P2a 대조 | `qa/cases.py` `cases/*.yaml` | `covers`(스크립트·단계), `reviewed`, `audit()`. 시드 13건 마이그레이션 — 유령 참조 `G.room.cancel` 은 `G.participation.cancel#2` 로 |
| P2a 화면 | `app.py` `qa/ui.py` | `/catalog` `/catalog/tc?id=` 대시보드 커버리지 카드, 스크립트 대조·근거 변경 배지, 런 meta.catalog |
| P2b 초안 | `qa/drafts.py` `qa/hermes.py` `qa/store.py` | 근거 조립 → Hermes → 결정론 검증 → `/drafts`. `draft-check` 런. 승인 = YAML 복사 → PR |
| P2c 탐색기 | `app.py` `qa/ui.py` `qa/runner.py` | `/explorer` 전송 = 런(trigger explorer, 동기·직렬), 런 목록 기본 숨김, [스크립트 단계로 담기] |
| P2d 발행 | `qa/mcp.py` `qa/report.py` | 런 상세 [위키에 발행]/[dry-run] → `wiki_apply` mode generated, 슬러그 `qa/<YYYY-Www>-<trigger>` |
| 가이드 | `qa/ui.py` | `/guide` — 트리거 원리, 테스트 조건 출처, AI 개입 시점, 화면별 용도, 개발·QA 워크플로우 (사용자 요청) |

### 15.2 설계에서 달라진 것

- **서술 테스트 조건 파일은 `manual-tc.yaml`** (설계 `prd-tc.yaml`). PRD 밖 운영 기준(헬스 체크)도 담아야 해서 `OPS.` 접두를 더했다. 층 이름은 `manual`.
- **`reviewed` 는 `{at, by}`** (설계 `{ssot: hash, …}`). 변경 이력을 테스트 조건 별 시각으로 쌓으므로 "검토 시각 이후 변경" 이 더 단순하고 SSOT·OpenAPI 두 원천에 같이 통한다.
- **OpenAPI 미디어 타입** `application/json;charset=UTF-8` 을 REST Docs 가 섞어 낸다. 이걸 놓치면 401 예시(E1102)가 통째로 빠진다 — 파서가 둘 다 읽는다.
- **탐색기 전송은 동기** (큐 대신 워커와 같은 락). 사람이 응답을 바로 봐야 해서다. 직렬성은 유지된다.
- **발행 대상에 배포 검증 런도 포함** (설계는 스프린트·릴리스만). 버튼은 같고 기본은 안 누른다.
- **`wiki_apply` 계약 확인**: 인자 `{mode, changes:[{path, content}], message, expected_head?, dry_run?}`. `generated` 모드는 `policy` 경로이거나 frontmatter `managed_by: harness` 여야 통과 — 보고서는 후자. `qa/` 컬렉션은 `wiki.toml` `type_by_prefix` 에 없어 kind 가 없는 페이지로 들어간다. **live 에서 첫 발행은 [dry-run] 으로 먼저 확인한다** (§15.3-3).

### 15.3 사람이 해야 하는 일

1. **push → 배포** (paths 트리거 `qa-platform/**`, compose). 배포 후 `https://qa.agent.plady.io/health` 에서 `catalog.records` 가 500 근처, `wiki.available: true` 인지 본다. `false` 면 `wiki-data` 볼륨 마운트 문제다.
2. **기준 화면 한 바퀴.** `/catalog?domain=room` 에서 카탈로그 경고 7건(스펙 예시 누락)을 확인한다. 이건 백엔드 REST Docs 에 E1102·E1410·E1425·E1427 예시를 추가하면 사라진다 — 백엔드 이슈로 뺄지 결정.
3. **첫 발행은 dry-run.** 스프린트 smoke 를 한 번 돌린 뒤 런 상세 [dry-run]. llm-wiki 가 `qa/` 슬러그를 받는지(`type_by_prefix` 밖) 여기서 확인된다. 거부하면 `report.slug_for` 를 `topics/qa-…` 로 바꾸는 한 줄 수정.
4. **초안 생성 1회.** `/catalog` 에서 미커버 테스트 조건 2~3건(같은 도메인) 고르고 [초안 생성]. 검증 탈락률은 활동 화면 `draft.rejected_by_validation` 으로 본다.
5. **Linear MOI-483** 코멘트 갱신(이 세션에서 Linear 연결이 인증 대기라 못 남겼다).
