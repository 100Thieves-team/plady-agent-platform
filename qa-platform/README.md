# qa-platform

백엔드 dev 서버를 OpenAPI 계약·PRD 근거로 검증하고, **누가 언제 무엇을 검증했는지** 남기는 얇은 플랫폼.
설계·계약·워크플로우는 [`docs/qa-platform.md`](../docs/qa-platform.md) 가 정본이다.

- 실행의 시작은 언제나 사람이다 (UI 버튼). 자동 트리거·inbound webhook 은 없다.
- 케이스 정본은 [`cases/*.yaml`](cases/) (git). DB(sqlite)는 런·단계·감사 로그·초안만.
- 검증 기준(TC)은 llm-wiki 의 `상태-SSOT.yaml`·PRD 와 백엔드 OpenAPI 에서 **파생**한다 ([`catalog/`](catalog/) 에 바인딩·제외·서술 TC). 케이스는 `covers:` 로 덮는 TC 를 선언하고 플랫폼이 대조한다 — [`docs/qa-platform-tc.md`](../docs/qa-platform-tc.md).
- AI 는 Hermes(`hermes-gateway`) 경유로만, 사람이 누를 때만 — 실패 진단과 케이스 초안 생성. 런타임에는 AI 가 없다. 자세한 사용법은 UI 의 `/guide`.

## 로컬 실행

```bash
python3 qa-platform/app.py
```
기본 포트 8800, 데이터 `/data` (로컬은 `QA_DATA_DIR` 로 바꾼다). 기준 카탈로그를 보려면 `QA_WIKI_DIR=wiki-workspace`(레포 안의 team-wiki-v2 체크아웃). 테스트 계정이 필요한 케이스는 `QA_ACTORS='{"qa-host":"<uuid>"}'` 를 주면 실행되고, 없으면 skipped 로 기록된다.

```bash
python3 -m unittest discover -s qa-platform/tests
```

컨테이너: `docker compose --profile qa up -d qa-platform` (compose.yaml).

## 케이스 쓰기

형식은 설계 §8. 최소 예:

```yaml
id: catalog.terms
title: 현재 유효 약관 목록을 비로그인으로 조회한다
suite: smoke            # smoke | sanity | manual
domains: [terms]        # PR 변경 도메인 → 권장 선택 키
operations: [termsList] # OpenAPI operationId
covers: [op.termsList:200]   # 덮는 TC (기준 화면에서 id 확인)
source: ["PRD/회원 및 프로필 §약관"]
steps:
  - name: 약관 목록
    request: { method: GET, path: /v1/terms }
    expect: { status: 200, result: SUCCESS, exists: [data] }
```

- `covers` 는 덮는 TC id (smoke·sanity 필수). 단계에도 달 수 있다. id 는 기준 화면(`/catalog`)에서 찾는다.
- `expect` 는 `status` · `result` · `error_code` · `json`(경로→값) · `exists`(경로 목록) 5종뿐이다.
- 치환은 `{{var}}`(save) · `{{actor.X.memberId}}` · `{{fixture.key}}` · `{{date:+N}}` · `{{uuid}}` · `{{rand}}`.
- 쓰기 케이스는 자기가 만든 데이터를 자기가 닫는다. 제목 접두 `[QA]`.
- 파일을 고친 뒤 UI 의 케이스 화면에서 [파일에서 다시 읽기].
