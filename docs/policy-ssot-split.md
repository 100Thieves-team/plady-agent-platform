# PRD 요구 id 와 SSOT 나누기 — 바뀐 곳을 문장 단위로 추적하기 (설계)

> 상태: **구현됨 (2026-09-23)**. 사용자 결정: PRD 는 전체를 구조화하지 않고 중간안으로 간다("중간안으로 설계 문서 써줘"). 검토 답은 §9, 구현 결과는 §10, 후속 작업은 §11.
> 대상 레포: 대부분 **team-wiki-v2**(PRD·SSOT·렌더러·CI·AGENTS.md). 이 레포에서는 compose 의 `policy-renderer` 사이드카와 `qa-platform` 이 바뀐다.
> 다음 작업: 이 설계가 끝나면 시나리오 관리(Hermes 가 만들고 사람이 고친다)를 이 위에 올린다.

## 1. 왜

지금 정본은 두 층이다. 사람이 읽는 **PRD**(`raw/product/*.md`, 11개)와, 그 규칙을 구조화한 **상태 SSOT**(`wiki/policy/_src/상태-SSOT.yaml`, 7,109줄)다. 둘을 잇는 끈이 약해서 네 가지 문제가 있다.

1. **참조가 절 번호에 묶여 있다.**
   - SSOT 는 PRD 를 `"PRD/룸 생성 §4.3"` 처럼 절 단위로 인용한다. 인용이 약 960건이다.
   - 수동 작성 TC id 도 `PRD.룸-탐색.4.1#1` 처럼 절 번호로 만든다.
   - 기획자가 절 순서를 바꾸면 이 참조가 한꺼번에 깨진다.
2. **절 안에서 문장이 바뀌면 아무도 모른다.**
   - `policy-drift-check` 는 인용한 절 제목이 아직 있는지만 본다.
   - AGENTS.md 도 이렇게 적는다: *"a section whose text was rewritten in place passes the check while the SSOT silently goes stale."*
   - 예를 들어 §4.3 에는 인원 규칙이 세 개 있다. 그중 "최대 8명" 이 "최대 6명" 으로 바뀌어도 검사는 통과한다.
3. **SSOT 가 한 파일이다.**
   - 7천 줄에 정책·사실·파생값·게이트·명령·전이·연쇄·결정이 다 들어 있다.
   - 에이전트는 위키 MCP 로 고칠 때마다 이 파일 전체를 읽고 쓴다. 둘이 동시에 고치면 충돌한다.
   - git 기록으로는 "룸 생성 규칙이 언제 바뀌었나" 를 가려 보기 어렵다.
4. **정책 TC id 가 순서 번호다.**
   - `G.room.create#8` 은 룸 생성 게이트의 여덟 번째 검사다(`render_tests.cases()` 의 `enumerate`).
   - 검사 하나를 중간에 넣으면 뒤 번호가 다 밀린다.
   - QA 플랫폼에는 이게 "TC 삭제 + 추가" 로 보인다.

## 2. 방향 — 중간안

| 한다 | 하지 않는다 |
|---|---|
| PRD 요구 문장마다 **고정 id** 를 단다(문장은 그대로) | PRD 를 YAML·표로 바꾸기 |
| PRD 2장 **사용자 시나리오만 약한 틀**에 맞춘다 | 규칙을 PRD 에도 구조로 적기(정본이 둘이 된다) |
| PRD 머리말에 **메타데이터** 몇 개 | 변경 기록 콜아웃(🔄 Before/After) 없애기 |
| SSOT 를 **기능별·대상별 파일**로 나누고 조립한다 | SSOT 형식(키·id·참조 문법) 바꾸기 |
| SSOT 가 PRD 를 **요구 id 로 인용**하고, 요구 문장의 해시로 변경을 잡는다 | 자동으로 SSOT 를 고치기(지금처럼 사람·에이전트가 고친다) |

규칙의 구조화된 정본은 SSOT 하나로 남는다. PRD 는 "근거 문장과 그 id" 까지만 책임진다.

## 3. PRD

### 3.1 요구 id

요구 한 줄 끝에 짧은 표식을 단다.

```markdown
### 4.3 모집 인원

- 최소 진행 인원은 2명 이상이다. `R21`
- 최대 모집 인원은 8명 이하이다. `R22`
- 최대 모집 인원은 최소 진행 인원보다 작을 수 없다. `R23`
- 방장은 현재 참여 인원에 포함된다. `R24`
```

- **모양**: 줄 끝의 인라인 코드 `` `R숫자` ``. 렌더링된 위키에서도 작게 보여서 사람이 "R22 바꿨어요" 처럼 말할 수 있다. 숨은 주석(`<!-- R22 -->`)은 편집하다 지워도 모르기 쉬워서 권하지 않는다(§9 질문 1).
- **번호**: 문서마다 1부터 올라가고, **지운 번호는 다시 쓰지 않는다.** 다음 번호는 머리말 `next_req` 에 적는다. 절을 옮겨도 번호는 따라간다.
- **전역 이름**: `PRD/룸 생성 R22`. 문서 이름 + 번호다.
- **범위**: 규칙을 말하는 줄에만 단다.
  - 3장(권한), 4장(기능 명세), 6장(데이터와 개인정보)의 목록 항목과 규칙을 말하는 문단이다. 지금 3·4장 목록 항목은 637개다.
  - 예시·용어 풀이·배경 설명 줄에는 달지 않는다.
  - 변경 기록 콜아웃 안에는 달지 않는다. 콜아웃은 기록이고, 규칙은 본문에 있다.
- **한 줄에 규칙 둘**이면 줄을 나누거나 하나의 id 로 둔다. 나누기를 권한다.

### 3.2 시나리오 약한 틀 (2장)

지금도 11개 PRD 모두 "2. 사용자 시나리오" 에 번호 단계가 있다. 이름과 분기 표시만 맞춘다.

```markdown
## 2. 사용자 시나리오

### 시나리오 S1: 룸을 만든다

1. 사용자가 룸 생성을 시작한다. `R1`
2. 채용 공고를 선택하고 직무·면접 단계를 선택한다. `R2`
   - 분기: 목록에 공고가 없으면 공고 링크를 붙여넣어 그 자리에서 공고를 만든다. `R3`
3. …
```

- `### 시나리오 S{n}: {이름}` 이 시나리오 하나다. 주요 시나리오가 하나뿐이면 S1 하나면 된다.
- 단계는 번호 목록이고, 들여쓴 `- 분기:` 가 분기다.
- 단계와 분기도 요구 id 를 받는다. 다음 작업인 시나리오 관리가 "이 변형은 S1 의 R3 분기" 처럼 가리킨다.
- "대표 사용자" 같은 설명 절은 그대로 둔다.

### 3.3 머리말

```yaml
---
legacy_source: "notion"              # 있는 것은 그대로
legacy_source_url: "…"
archived_at: "2026-08-22"
owner: "기획 담당 이름"               # 새로
status: "확정"                        # 초안 | 확정
updated: "2026-09-03"                 # 마지막 내용 변경일 (SSOT meta.기준_문서 와 같은 뜻)
next_req: 83                          # 다음에 쓸 요구 번호
---
```

## 4. SSOT 나누기

### 4.1 파일 구성

```
wiki/policy/_src/
  index.yaml                  meta(version·성격·출처_규칙·결정_주체·기준_문서·상태) + 조립 순서
  공통.yaml                   policies · cascades
  결정.yaml                   decisions · decisions_pending
  상태/룸.yaml                facts · derived  (소유 대상별: 룸·회원·질문·후기·이력서·참여·참가 신청·방명록·출석)
  상태/회원.yaml …
  기능/룸-생성.yaml           commands · gates · transitions  (PRD 하나당 하나)
  기능/룸-참여-및-참여자-관리.yaml …
  상태-SSOT.yaml              조립본 — 생성물. 손으로 고치지 않는다 (§4.4)
```

### 4.2 항목을 어느 파일에 두나

2026-09-23 origin/main 기준으로 항목이 몇 개의 PRD 를 인용하는지 셌다.

| 종류 | PRD 하나 | 여러 PRD | 놓는 곳 |
|---|---|---|---|
| gates | 59 | 7 | 기능 파일 |
| commands | 39 | 7 | 기능 파일 |
| transitions | 37 | 6 | 기능 파일 (자기 command 와 같은 파일) |
| facts | 72 | 26 | 상태 파일 (`owner` 필드 = 파일) |
| derived | 41 | 25 | 상태 파일 (`owner` 필드 = 파일) |
| policies | 7 | 17 | 공통 |
| cascades | 3 | 2 | 공통 |

- 행동 규칙(게이트·명령·전이)의 약 90% 는 PRD 하나에만 속한다. 여러 PRD 를 인용하는 것은 **명령을 트리거하는 화면이 있는 PRD** 에 둔다. 게이트와 전이는 자기 명령을 따라간다.
- 사실·파생값은 이미 `owner` 필드가 있다(룸 21, 질문 17, 회원 16 …). 그 값이 파일이다.
- id 는 지금처럼 전역이다. 파일이 달라도 `F.member.account_status` 같은 참조는 그대로 된다.

### 4.3 조립

`tools/policy-renderer/ssot_load.py` 를 새로 둔다. 렌더러·테스트 추출·QA 플랫폼이 모두 이 함수 하나로 읽는다.

1. `index.yaml` 의 `files:` 순서대로 읽는다.
2. 종류별 목록을 이어 붙여 지금 파일과 같은 모양의 dict 를 만든다.
3. 검사한다. 하나라도 걸리면 실패한다.
   - id 중복(파일을 건너서도)
   - 끊긴 참조(`gate`·`transition`·`reads`·`checks[].ref` 의 id 가 없음)
   - 파일에 놓으면 안 되는 종류(기능 파일에 facts 가 있음 등)
   - `source` 인용 형식(§5.1)

### 4.4 조립본

`상태-SSOT.yaml` 은 **조립 결과를 커밋해 두는 생성물**로 바꾼다.

- 그러면 지금 이 파일을 읽는 곳(렌더러 3개, QA 플랫폼, MCP 로 읽는 에이전트)이 당장 바뀌지 않아도 된다.
- 파일 맨 위에 "생성물 — `_src/기능/`·`_src/상태/` 를 고친다" 주석을 넣는다.
- CI 가 `조립(나눈 파일) == 조립본` 을 검사한다. 조립본을 손으로 고치면 실패한다.
- 소비자가 모두 `ssot_load` 로 옮기면 조립본을 없앨지 다시 판단한다(§9 질문 3).

### 4.5 게이트 검사의 고정 key (선택)

§1-4 문제를 풀려면 게이트 `checks` 항목마다 `key` 를 단다.

```yaml
- ref: F.room.mode == OFFLINE 이면 F.room.region 이 입력되었는가
  key: offline-region
  message: 오프라인 룸은 탐색에 쓸 지역을 입력해 주세요
```

- TC id 가 `G.room.create#offline-region` 이 된다. 검사를 끼워 넣어도 다른 TC id 가 안 바뀐다.
- 비용: QA 스크립트의 `covers` 가 `G.room.create#5` 같은 옛 id 를 쓴다. 한 번 옮겨야 한다. QA 플랫폼이 옛 번호 → key 대응표로 스크립트를 고쳐 main 에 커밋할 수 있다(폼 편집의 커밋 경로 재사용).
- 이 단계는 따로 결정한다(§9 질문 4).

## 5. 변경 추적

### 5.1 인용 형식

SSOT 의 `source` 는 요구 id 를 인용한다.

```yaml
source: ["PRD/룸 생성 R21", "PRD/룸 생성 R22", "PRD/룸 생성 R23"]
```

- 절 번호는 적지 않는다. 렌더러가 PRD 를 읽어 R22 가 어느 절에 있는지 찾아 화면에 "§4.3" 을 같이 보여 준다. 적어 두면 절을 옮길 때마다 또 고쳐야 한다.
- 옮기는 동안에는 `"PRD/룸 생성 §4.3"` 절 인용도 받는다. 검사는 경고만 한다.
- `"DEC-nnn"` 은 그대로다.

### 5.2 무엇이 바뀌었나

렌더링 때 `sync-manifest.json` 에 두 가지를 더 적는다.

```json
{
  "req_hashes": { "룸 생성": { "R21": "3f2a9c", "R22": "b71e04" } },
  "part_hashes": { "기능/룸-생성.yaml": "a1b2c3", "상태/룸.yaml": "9d8e7f" }
}
```

`policy-drift-check` 가 지금 PRD 와 비교해 세 가지를 잡는다.

| 무엇 | 지금 | 나눈 뒤 |
|---|---|---|
| 인용한 요구가 사라짐 | 절 제목이 사라질 때만 | R 번호가 사라지면 |
| 요구 문장이 바뀜 | 못 잡음 | 문장 해시가 다르면 |
| 영향받는 SSOT 항목 | 없음 | 그 R 을 인용하는 항목 id 와 파일 |

알림은 지금처럼 Slack 과 이슈다. 예를 들면 이렇게 뜬다.

```
PRD/룸 생성 R22 문장이 바뀌었다 (b71e04 → 55c0d1)
  "최대 모집 인원은 8명 이하이다" → "최대 모집 인원은 6명 이하이다"
  이 요구를 인용하는 SSOT 항목: D.room.headcount_range_valid (상태/룸.yaml), G.room.create (기능/룸-생성.yaml)
```

### 5.3 QA 플랫폼까지

- TC 레코드에 근거 요구 id 를 싣는다. TC 상세 화면이 "근거: R22 (§4.3) — 최대 모집 인원은 8명 이하이다" 를 보인다.
- 지금의 "TC 변경" 표시(TC 해시 비교)에 **사유**가 붙는다. 예: "R22 문장이 바뀌어 G.room.create 가 바뀜".
- "바뀐 TC 에 맞게 Hermes 가 고치기" 에 바뀐 요구 문장의 전후를 근거로 넣는다.

## 6. 바꿀 곳

| 레포 | 무엇 | 내용 |
|---|---|---|
| team-wiki-v2 | `raw/product/*.md` 11개 | 요구 id, 시나리오 틀, 머리말 |
| team-wiki-v2 | `wiki/policy/_src/` | 나눈 파일 + `index.yaml` + 조립본 |
| team-wiki-v2 | `tools/policy-renderer/` | `ssot_load.py` 새로, `render_wiki.py`·`render_ssot.py`·`render_tests.py` 가 폴더를 입력으로 받게(`-i` 가 파일이면 지금처럼) |
| team-wiki-v2 | `.github/scripts/check_policy_refs.py`, 워크플로 | R 번호·문장 해시·영향 항목, 조립본 일치 검사 |
| team-wiki-v2 | `AGENTS.md` | "PRD → SSOT sync" 절차를 요구 id 기준으로. 새 요구엔 `next_req` 로 번호, 고칠 파일은 기능·상태 파일 |
| team-wiki-v2 | `render_wiki.py` 안내 문구 | "유일한 진실은 `interview-ddd/docs/design/상태-SSOT.yaml`" 라는 옛 문구를 `_src/` 로 |
| 이 레포 | `compose.ec2.yaml` `policy-renderer` | 파일 하나(`SRC=…상태-SSOT.yaml`)가 아니라 `_src/` 폴더 전체의 해시를 지켜본다 |
| 이 레포 | `qa-platform/qa/wiki.py`·`catalog.py` | SSOT 해시를 폴더 기준으로, 읽기는 `ssot_load`, TC 에 근거 요구 id |
| llm-wiki | 없음 | MCP 는 어느 파일이든 읽고 쓴다. 안내문은 AGENTS.md 에서 온다 |

## 7. 옮기는 순서

| 단계 | 내용 | 확인 |
|---|---|---|
| M1 | `ssot_load` + 파일 나누기. **내용은 한 글자도 안 바꾼다** | 조립본을 파싱한 결과가 지금 파일과 같다. 렌더링된 정책 페이지 diff 가 0 이다. 사이드카가 폴더를 지켜본다 |
| M2 | PRD 요구 id·머리말. 문서 하나씩, 에이전트가 달고 사람이 본다 | 문서마다 `next_req` 와 실제 최대 번호가 맞다. 렌더링된 PRD 에 표식이 보인다 |
| M3 | SSOT `source` 를 요구 id 로. 절 인용 하나를 그 절의 요구 여러 개로 좁힌다. 어느 요구인지 모호하면 절 인용을 남기고 표시해 둔다 | 절 인용 경고 수가 줄어든다. 드리프트 검사가 문장 해시를 본다 |
| M4 | PRD 2장 시나리오 틀 | 11개 모두 `### 시나리오 S{n}:` 이 있다 |
| M5 (선택) | 게이트 검사 key + TC id 이전 | QA 스크립트 covers 가 새 id 로 바뀌고 테스트가 통과한다 |

- QA 플랫폼은 M1 뒤에 폴더 읽기로, M3 뒤에 근거 요구 표시로 바꾼다.
- 각 단계는 PR 하나다. M2·M3 는 문서 11개라 문서별 커밋으로 나눈다.
- M1 은 사람 작업이 없다. M2~M4 는 PRD 를 바꾸니 기획 담당이 결과를 본다.

## 8. 위험

- **옮기는 동안의 편집**: M1~M3 사이에 누가 PRD 나 SSOT 를 고치면 충돌한다. 단계마다 짧게 편집을 멈추는 시간을 정한다.
- **요구 id 를 안 다는 편집**: 새 규칙 줄에 id 를 안 달면 SSOT 가 인용할 수 없다. CI 가 3·4·6장 목록 항목 중 id 없는 줄을 경고한다.
- **렌더링**: 인라인 코드 `` `R22` `` 는 Hugo 에서 그대로 코드로 보인다. 확인이 필요하면 CSS 로 흐리게 한다.
- **`raw/` 규칙**: AGENTS.md 는 `raw/` 를 create-only 라고 하지만 `raw/product` 는 `wiki.toml` 에서 `revisable` 로 선언돼 있다. PRD 수정은 지금도 되는 일이다.

## 9. 검토 질문과 답 (2026-09-23)

1. 요구 id 모양 → **보이는 쪽** (`` `R22` ``).
2. SSOT 나누기 기준(행동 규칙은 기능별, 사실·파생값은 대상별, 정책·연쇄·결정은 공통) → **괜찮다**.
3. 조립본을 생성물로 커밋 → **동의**.
4. 게이트 검사 key(M5) → **같이 한다**.
5. PRD 를 쓰는 사람 → **에이전트**. 그래서 요구 id 규칙(`next_req`, 번호 재사용 금지)을 AGENTS.md 절차로 강제한다.

## 10. 구현 결과 (2026-09-23)

team-wiki-v2 브랜치 `ssot-split`(worktree `team-wiki-v2-ssot`)와 이 레포에서 했다.

| 단계 | 결과 |
|---|---|
| M1 나누기 | 조각 21개: 공통 · 결정 · 상태 9(룸·참여·참가 신청·출석·회원·이력서·질문·방명록·후기) · 기능 10(PRD 별). 항목 417개가 원본과 **데이터가 같다**(종류별 id 정렬 비교). 렌더된 정책 페이지 6개 중 5개와 manifest 가 원본과 글자까지 같고, 결정 로그 페이지만 미결 질문 목록의 **순서**가 바뀐다(게이트가 기능별로 묶여서). 여러 PRD 에 걸친 명령 7개는 일어나는 화면의 PRD 로 직접 정했다(`C.room.start` → 룸 진행 등). 명령 없는 조회 게이트 27개는 첫 인용 PRD 로 갔다 |
| M2 요구 id | PRD 11개에 1,042개. 2·3·4·6장의 목록 항목·규칙 문단과 표 행(회원 §4.8 삭제 기한 표 R126~R128). 콜아웃·제목에는 없다. **설계와 다른 점**: "규칙 줄에만" 대신 해당 장의 본문 줄에 모두 달았다 — 규칙인지 판단은 인용하는 쪽이 하고, 빠뜨리는 것보다 낫다 |
| M3 인용 | 절 인용 976건 중 936건(요구 id 가 있는 장)을 서브 에이전트 5개가 문장을 읽고 요구 id 로 좁혔다. 결과 인용: 요구 1,889 · 절 51 · 결정 19. 절 51 = 1·5·7·8장 인용 40 + 근거 문장이 지금 PRD 에 없는 11(§11-1) |
| M4 시나리오 | 11개 PRD 모두 `### 시나리오 S1: …`. 분기 표시는 룸 생성 하나(`- 분기: 목록에 공고가 없으면…`). 룸 참여 PRD 의 콜아웃 뒤 번호를 4부터 이어 붙였다 |
| M5 검사 key | 게이트 68개(검사 194개)에 key. TC id `G.x#key`. 이 레포는 스크립트·바인딩·자동화 제외·테스트를 새 id 로 옮기고, `catalog/tc-aliases.yaml`(새 key → 옛 번호) + 카탈로그 동적 별칭(옛 번호 → key)으로 **어느 쪽이 먼저 배포돼도** covers 가 풀린다. 이름만 바뀐 TC 는 변경 이력에서 삭제+추가로 보지 않는다 |

**추적이 실제로 되는지**: 룸 생성 R54 "최대 모집 인원은 8명 이하" 를 6명으로 바꾸면 드리프트 검사가 "R54 문장이 바뀜 — 전/후 — 인용한 레코드: P.room.capacity" 를 낸다. 절 번호는 그대로라 예전 검사는 통과했을 변경이다. 상관없는 조각을 고쳐 다시 렌더돼도 기준 문장은 그대로 남고(`meta.기준_문서` 날짜가 바뀔 때만 새 문장으로 옮긴다), 날짜를 올리면 드리프트가 풀린다.

**QA 플랫폼**: TC 레코드의 `prd` 에 요구 id·절·문장이 실리고 TC 상세의 "근거 PRD" 에 보인다. TC 변경 해시는 출처를 문서·장 단위로 줄여 계산해, 절 인용을 요구 인용으로 좁힌 것 같은 형식 변화는 변경으로 보지 않는다(이전 캐시 해시도 새 공식으로 다시 계산).

**바꾼 파일**

| 레포 | 파일 |
|---|---|
| team-wiki-v2 | `wiki/policy/_src/`(조각·index·조립본), `raw/product/*.md` 11개, `tools/policy-renderer/ssot_load.py`·`prd_reqs.py`(새로), `render_wiki.py`·`render_ssot.py`·`render_tests.py`, `.github/scripts/check_policy_refs.py`·`slack_drift_payload.py`, `.github/workflows/policy-drift-check.yml`, `AGENTS.md`, `wiki/policy/*`(다시 렌더) |
| 이 레포 | `compose.ec2.yaml` policy-renderer(조각 폴더 감시, 예전 한 파일도 지원), `scripts/sync-policy.sh`, `qa-platform/qa/{wiki,catalog,cases,ui,help}.py`, `qa-platform/catalog/{bindings,exclusions,tc-aliases}.yaml`, `qa-platform/cases/room.yaml`, 테스트(`QA_TEST_WIKI_DIR` 로 위키 체크아웃을 고를 수 있다) |

**배포 순서**: 둘 다 서로 없이도 동작한다. 사이드카는 조각 폴더가 없으면 예전처럼 파일 하나를 보고, QA 플랫폼은 별칭으로 두 id 체계를 다 읽는다. 권하는 순서는 team-wiki-v2 `ssot-split` 을 main 에 합친 뒤 이 레포를 push 하는 것이다. 합치기 전에 서버 쪽에서 SSOT 를 MCP 로 고치는 작업은 멈춘다(조각으로 옮긴 파일과 충돌).

## 11. 후속 작업 — 옮기면서 드러난 SSOT·PRD 불일치

서브 에이전트들이 인용을 좁히며 남긴 메모 48건을 묶었다. SSOT 내용 수정은 이번 범위 밖이라 그대로 두었다.

1. **근거 문장이 지금 PRD 에 없어 절 인용으로 남은 것(11건)**: `G.room.start`(룸 진행 §4.1 은 블록 목록만), `F.member.mode_preference`·`F.member.offline_region`(현행 프로필 선택 항목에 없다), `F.question.answer_summary`·`answer_summary_author`·`answer_summary_round`(룸 진행 R40 이 답변 요약을 없앴다).
2. **SSOT 가 PRD 보다 뒤처진 레코드**: 답변 요약 → 질문 메모(`G/C.question.record_answer_summary`, `F.question.comment_*` 값 이름 NOTE/GOOD/IMPROVE ↔ PRD MEMO/GOOD_POINT/IMPROVEMENT_POINT), 회당 평균 → 활동률 상위 %(`D.member.questions_per_room`·`feedbacks_per_room`), `D.member.attendance_tendency`(최근 3회로 확정), `D.member.absence_count` 표현, `F.member.job`(관심 직무 복수), `D.participation.round_record_listing`, `G.question.rate_closing`(공통 질문 개념 없어짐, R70), `G.question.write_comment`(최초 등록은 MEMO, R46), `D.review.already_written`(삭제되지 않은 후기만 막는다 — expr 에 조건 누락).
3. **PRD 끼리 또는 SSOT 와 충돌 — decisions_pending 후보**: 진행 시작 권한(룸 진행 R26 "시각·방장 무관" ↔ `P.room.session_start` "+5분 전 방장만"), 진행 모드를 연 사람이 방장이 되는가(룸 진행 준비 R7 ↔ 마무리 R13·R24), 방장 이탈·자동 승계(룸 참여 R31~R35 ↔ `P.participation.exit`), 모집 중 일정 수정(룸 생성 R108 ↔ `P.room.schedule_deadline` open_question), 확정 후 취소(룸 참여 R58 만 "불가").
4. **PRD 가 이미 답한 open_question**: `F.question.asked`(R36 해제 가능), `F.question.body`(준비 R38), `F.review.deleted_at`(R32 재작성 가능), `P.member.withdrawal`(승계 규칙 R31~R35 존재), `P.room.confirmation_freeze`.
5. **근거가 약한 검사**: `G.question.create#not-own-cardset`, `G.question.create_followup#parent-question-active`.
6. **QA 스크립트**: `room.create-and-cancel` 4단계가 `G.participation.cancel#participation-joined`(SSOT error E1419)를 covers 로 두고 E1410 을 기대한다 — 룸 재취소는 참여 취소 게이트가 아닐 수 있다. 최신 SSOT 로 카탈로그를 만들면 정합성 경고가 뜬다.
7. **API 매핑**: `catalog/bindings.yaml` 의 `G.room.start#5` 는 그 게이트에 검사가 5개가 안 돼 가리키는 TC 가 없다(예전부터).
