# LLM Wiki agent ingest workflow

이 문서는 MCP client로 붙은 agent(Codex, Claude, Cursor 등)가 `100Thieves-team/team-wiki-v2`를 SSOT LLM Wiki로 업데이트할 때 따라야 하는 표준 workflow입니다.

## 핵심 원칙

`llm-wiki` binary에는 LLM이 없습니다. 엔진은 git, markdown, schema validation, search index, graph, MCP tool만 제공합니다.

따라서 ingest는 두 단계로 나눕니다.

| 단계 | 주체 | 의미 |
| --- | --- | --- |
| AI compile | MCP client agent | raw 문서를 읽고 기존 wiki와 연결해 source/topic/person page를 생성 또는 갱신 |
| `wiki_ingest` | llm-wiki engine | 작성된 markdown을 검증, index 갱신, git commit |

즉 `wiki_ingest`는 compile 자체가 아니라 compile 결과를 finalize하는 primitive입니다.

## 저장소/경로 규칙

운영 data repo는 [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)입니다. 로컬과 EC2에서는 app repo 내부의 `wiki-workspace/`로 mount됩니다.

권장 구조:

```text
wiki-workspace/
  raw/                 # 원문/입력 문서 archive, UI에서는 /raw/로 노출
    meetings/
    adr/
    mentoring/
    legacy-team-wiki/
  wiki/                # agent가 compile한 durable knowledge pages
    people/
    sources/
    topics/
  schemas/
  wiki.toml
```

- raw 문서는 가능한 한 원문성을 보존합니다.
- active wiki page는 `wiki/` 아래에 둡니다.
- 기존 legacy 규칙은 active rule로 가져오지 않습니다.
- 새/수정 wiki page는 현재 `doc` schema를 우선 사용합니다.

## Agent ingest 절차

새 raw 문서가 들어오면 agent는 아래 순서로 작업합니다.

1. **Raw 저장**
   - 원문을 `raw/<category>/...` 아래에 저장합니다.
   - 이미 외부 repo/첨부에 있던 문서라면 source 위치를 body나 frontmatter에 남깁니다.

2. **기존 지식 탐색**
   - `wiki_search`로 문서의 핵심 키워드, 사람 이름, 프로젝트명, 결정 사항을 검색합니다.
   - 필요하면 `wiki_content_read`로 관련 `people/`, `topics/`, `sources/` page를 읽습니다.

3. **Source page 작성/갱신**
   - raw 문서 1개 또는 관련 raw 묶음마다 `wiki/sources/...`에 요약 page를 작성합니다.
   - 포함할 내용:
     - 문서의 목적/맥락
     - 핵심 주장/결정
     - caveat/불확실성
     - 관련 raw path
     - 관련 topic/person 링크

4. **Topic/Person page 갱신**
   - 새 정보가 기존 topic/person 지식에 영향을 주면 해당 page를 갱신합니다.
   - 같은 사실을 여러 곳에 중복 서술하지 말고, index page는 요약과 링크 중심으로 유지합니다.

5. **검증 dry-run**
   - 큰 변경이면 먼저 `wiki_ingest(path: "wiki/...", dry_run: true)`로 schema 문제를 확인합니다.

6. **Finalize**
   - `wiki_ingest(path: "wiki/...", dry_run: false)`를 호출합니다.
   - raw 문서도 index에 포함해야 하는 경우 `wiki_ingest(path: "raw/...", dry_run: false)`를 별도로 호출합니다.

7. **품질 점검**
   - 여러 page를 만든 경우 `wiki_lint`를 실행합니다.
   - 필요하면 `wiki_index_rebuild`로 index를 재생성합니다.

## MCP tool 선택 기준

| 목표 | 권장 tool/방법 |
| --- | --- |
| 관련 문서 찾기 | `wiki_search` |
| 기존 page 읽기 | `wiki_content_read` |
| 새 page scaffold | `wiki_content_new` |
| 기존 page path 확인 | `wiki_resolve` |
| 전체 내용 overwrite | `wiki_content_write` |
| 파일 검증/index/commit | `wiki_ingest` |
| 링크/고립 문서 점검 | `wiki_lint` |
| 검색 index 재생성 | `wiki_index_rebuild` |

`wiki_content_write`나 직접 파일 쓰기만으로는 index와 git commit이 완료되지 않습니다. 작성 후 반드시 `wiki_ingest`를 호출합니다.

## Compile 품질 기준

- raw 원문을 지우거나 요약본으로 대체하지 않습니다.
- wiki page는 단순 요약이 아니라 “나중에 코딩/기획 작업에서 다시 쓸 수 있는 durable context”로 작성합니다.
- 결정 사항은 배경, 선택지, 결정, 영향, 미해결 질문을 분리합니다.
- 멘토링 문서는 사람 중심 page와 topic 중심 page에 각각 필요한 만큼만 반영합니다.
- 출처 링크는 가능한 한 `raw/...` 또는 `wiki/sources/...`로 남깁니다.
- 확실하지 않은 추론은 caveat로 남기고 사실처럼 단정하지 않습니다.

## ACP에 대한 판단

ACP는 Zed/IDE agent panel에서 `llm-wiki:research`, `llm-wiki:ingest`, `llm-wiki:lint` 같은 workflow를 streaming으로 실행하기 위한 선택적 transport입니다.

우리 운영 기준은 다음과 같습니다.

- 기본 remote 운영: MCP HTTP + Bearer token
- agent compile workflow: Codex/Claude 같은 MCP client가 수행
- ACP: IDE streaming workflow가 필요할 때만 추가 검토

ACP의 `llm-wiki:ingest`도 engine의 `ops::ingest`를 호출하는 finalize 계층입니다. raw를 의미 있는 wiki knowledge로 바꾸는 판단은 여전히 외부 agent/skill이 담당합니다.

## 권장 agent prompt

새 문서를 ingest할 때 agent에게 아래 형태로 요청합니다.

```text
이 raw 문서를 LLM Wiki에 ingest해줘.
- 원문은 raw/<category>/에 보존해줘.
- 기존 wiki를 검색해서 관련 people/topics/sources를 확인해줘.
- source summary page를 만들고, 필요한 topic/person page를 갱신해줘.
- 변경 후 wiki_ingest와 wiki_lint를 실행해줘.
- 단순 요약이 아니라 이후 코딩/기획 작업에 재사용 가능한 SSOT context로 정리해줘.
```
