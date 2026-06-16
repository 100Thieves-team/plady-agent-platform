# Wiki 데이터 저장소 구조

결론부터 말하면, MCP로 `wiki_ingest` 요청을 날렸을 때 쌓이는 회의록/ADR/멘토링 정리 데이터는 이 wrapper repo가 아니라 **별도 git repo인 `wiki-workspace/`**에 저장됩니다.

## 저장소 역할

| 경로/저장소 | 역할 | Git 관리 |
| --- | --- | --- |
| `100Thieves-wiki-mcp` | Docker Compose, Terraform, upstream `llm-wiki`, Hugo UI scaffold | 이 repository |
| `wiki-workspace/` | 실제 wiki content, raw 문서, schema, llm-wiki ingest 결과 | llm-wiki가 init하는 별도 git repo |

현재 로컬 구조는 아래처럼 동작합니다.

```text
100Thieves-wiki-mcp/
  compose.yaml
  docker/
  llm-wiki/
  llm-wiki-hugo-cms/
  wiki-workspace/        # 별도 git repo, wrapper repo에서는 .gitignore 처리
    .git/
    wiki.toml
    raw/
    wiki/
    schemas/
```

EC2에서는 기본적으로 아래 경로가 됩니다.

```text
/opt/100thieves-wiki-mcp/wiki-workspace/
```

## ingest 시 일어나는 일

`llm-wiki` MCP 서버는 Docker Compose에서 `/workspace`를 `./wiki-workspace`에 mount합니다.

```yaml
llm-wiki:
  volumes:
    - ./wiki-workspace:/workspace
```

따라서 `wiki_ingest` 또는 content write/commit 류 작업은 다음 저장소에 반영됩니다.

```bash
cd wiki-workspace
git status
git log --oneline
```

즉, 이 wrapper repo에 commit이 생기는 것이 아니라 `wiki-workspace` 내부 git history에 wiki 데이터 commit이 쌓입니다.

## 운영 권장 구조

운영에서는 `wiki-workspace`에도 별도 GitHub remote를 붙이는 것을 권장합니다.

예시 repo 이름:

```text
100Thieves-team/100Thieves-wiki-data
```

초기 연결:

```bash
cd wiki-workspace
git remote add origin git@github.com:100Thieves-team/100Thieves-wiki-data.git
git branch -M main
git push -u origin main
```

HTTPS token을 쓸 경우:

```bash
cd wiki-workspace
git remote add origin https://github.com/100Thieves-team/100Thieves-wiki-data.git
git branch -M main
git push -u origin main
```

## 새 서버에서 데이터 복원

기존 wiki 데이터 repo가 있다면 app repo를 clone한 뒤, Compose 실행 전에 `wiki-workspace` 위치에 데이터 repo를 clone합니다.

```bash
git clone https://github.com/100Thieves-team/100Thieves-wiki-mcp.git /opt/100thieves-wiki-mcp
cd /opt/100thieves-wiki-mcp
rm -rf wiki-workspace
git clone https://github.com/100Thieves-team/100Thieves-wiki-data.git wiki-workspace
docker compose up -d --build
```

## 주의사항

- `wiki-workspace/`는 wrapper repo의 `.gitignore` 대상입니다.
- llm-wiki는 로컬 git commit을 만들 수 있지만, GitHub remote로 자동 push하지는 않습니다.
- 운영에서는 주기적 `git push`, 백업 정책, 또는 별도 동기화 작업을 정해야 합니다.
- EC2 인스턴스를 destroy하면 local `wiki-workspace`도 사라질 수 있으므로, 반드시 remote push 정책을 먼저 정하세요.
