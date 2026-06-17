# Wiki 데이터 저장소 구조

결론부터 말하면, MCP로 `wiki_ingest` 요청을 날렸을 때 쌓이는 회의록/ADR/멘토링 정리 데이터는 이 wrapper repo가 아니라 **별도 git repo인 [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)**에 저장되도록 구성합니다.

로컬/컨테이너 내부에서는 그 repo가 `wiki-workspace/` 경로로 mount됩니다.

## 저장소 역할

| 저장소/경로 | 역할 | Git 관리 |
| --- | --- | --- |
| [`100Thieves-team/100Thieves-wiki-mcp`](https://github.com/100Thieves-team/100Thieves-wiki-mcp) | Docker Compose, Terraform, upstream `llm-wiki`, Hugo UI scaffold | app wrapper repo |
| [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2) | 실제 wiki content, raw 문서, schema, llm-wiki ingest 결과 | wiki data SSOT repo |
| `wiki-workspace/` | `team-wiki-v2`가 clone되는 로컬 작업 디렉터리 | wrapper repo에서는 `.gitignore` 처리 |

현재 구조는 아래처럼 동작합니다.

```text
100Thieves-wiki-mcp/
  compose.yaml
  docker/
  llm-wiki/
  llm-wiki-hugo-cms/
  wiki-workspace/        # team-wiki-v2 clone 위치
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
git remote -v
```

즉, app wrapper repo에 데이터 commit이 생기는 것이 아니라 `wiki-workspace` 내부 git history에 wiki 데이터 commit이 쌓입니다. EC2 배포에서는 `wiki-workspace`의 remote가 [`team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)로 설정됩니다.

## 안전한 GitHub 인증 방식

PAT는 범위가 넓고 회전/감사가 불편하므로 기본 방식으로 쓰지 않습니다. 대신 repo별 GitHub Deploy Key를 사용합니다.

- app repo deploy key: [`100Thieves-team/100Thieves-wiki-mcp`](https://github.com/100Thieves-team/100Thieves-wiki-mcp) read-only clone용
- wiki data deploy key: [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2) clone/push용, write 허용
- private key는 AWS SSM Parameter Store `SecureString`에 저장
- Terraform state에는 SSM parameter 이름만 저장

## EC2 자동 push

EC2 bootstrap은 `team-wiki-v2`를 `wiki-workspace/`로 clone하고, `llm-wiki-data-sync.timer`를 활성화합니다.

이 timer는 주기적으로 아래 작업을 수행합니다.

1. `wiki-workspace` 상태 확인
2. 필요 시 local 변경 commit
3. `origin main`으로 push

확인:

```bash
sudo systemctl status llm-wiki-data-sync.timer
sudo journalctl -u llm-wiki-data-sync.service -n 100 --no-pager
```

수동 실행:

```bash
sudo /usr/local/bin/llm-wiki-data-sync
```

## 새 서버에서 데이터 복원

기존 wiki 데이터 repo를 새 서버에 붙이려면 app repo를 clone한 뒤, Compose 실행 전에 `wiki-workspace` 위치에 [`team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)를 clone합니다.

```bash
git clone https://github.com/100Thieves-team/100Thieves-wiki-mcp.git /opt/100thieves-wiki-mcp
cd /opt/100thieves-wiki-mcp
rm -rf wiki-workspace
git clone https://github.com/100Thieves-team/team-wiki-v2.git wiki-workspace
docker compose up -d --build
```

## 주의사항

- `wiki-workspace/`는 wrapper repo의 `.gitignore` 대상입니다.
- 운영 SSOT는 [`team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)입니다.
- EC2 인스턴스를 destroy하기 전에 `llm-wiki-data-sync`가 최신 commit을 push했는지 확인하세요.
- data repo Deploy Key는 write 권한이 필요하지만, 권한 범위가 `team-wiki-v2` 단일 repo로 제한되므로 PAT보다 안전합니다.

## Legacy `team-wiki` migration

기존 [`100Thieves-team/team-wiki`](https://github.com/100Thieves-team/team-wiki) 문서는 `scripts/migrate-team-wiki.sh`로 새 llm-wiki data workspace에 이관합니다.

기본은 dry-run입니다.

```bash
scripts/migrate-team-wiki.sh
```

실제 복사:

```bash
scripts/migrate-team-wiki.sh --apply
```

이관 구조:

```text
wiki-workspace/
  raw/legacy-team-wiki/raw/          # 기존 raw 원문
  raw/legacy-team-wiki/Clippings/    # 기존 clipping 문서
  raw/legacy-team-wiki/attachments/  # 이미지/첨부파일
  raw/legacy-team-wiki/views/        # 기존 view 정의
  raw/legacy-team-wiki/root/         # 루트 markdown/html 문서
  wiki/                              # 기존 curated wiki seed pages
  migration/team-wiki-migration-report.md
```

이관 후에는 한 번에 전부 재작성하지 말고 batch별로 검증합니다.

```bash
scripts/check-mcp-tools.sh
# MCP에서 wiki_ingest, wiki_lint, wiki_index_rebuild를 batch별로 실행
```

권장 순서:

1. `wiki/people`
2. `wiki/topics`
3. `wiki/sources`
4. `raw/legacy-team-wiki/raw`
5. `raw/legacy-team-wiki/Clippings`

마지막으로 `wiki-workspace`에서 `git status`를 확인하고, 문제가 없으면 `team-wiki-v2`에 commit/push합니다.
