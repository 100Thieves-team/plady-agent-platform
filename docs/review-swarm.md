# Code Review Agent: review-swarm 배선 (구현계획 Phase 3)

다이어그램의 Code Review Agent는 [`100Thieves-team/review-swarm`](https://github.com/100Thieves-team/review-swarm)을 사용합니다. self-hosted 러너에서 로컬 Claude Code/Codex CLI로 멀티에이전트 리뷰(안전 게이트 → verify → debate → mediator → 결정론적 policy gate)를 실행하고, 에이전트별 GitHub App 봇으로 PR 인라인 리뷰를 게시합니다.

## 이 저장소에 배선된 것

- [`.github/workflows/review-swarm.yml`](../.github/workflows/review-swarm.yml): PR opened/synchronize/reopened 에서 `100Thieves-team/review-swarm@main` 액션 실행. **repository variable `REVIEW_SWARM_ENABLED=true` 일 때만 잡이 뜬다** — 러너가 없는 상태에서 잡이 무기한 queued 로 남는 것을 막는 게이트.
- [`.review-swarm.yaml`](../.review-swarm.yaml): 시작 설정. `publish.mode: single`(워크플로 `GITHUB_TOKEN` 단일 계정 게시)로 배선을 검증한 뒤 App 자격 등록 후 `apps`로 전환한다.
- `.gitignore`에 실행 산출물 디렉터리 `.review-swarm/` 추가.

## 🙋 사람이 직접 해야 하는 일 (활성화 체크리스트)

1. **러너 준비**: `[self-hosted, review-swarm]` 라벨의 러너 등록. Node.js ≥ 20.19 + git 필요. 러너 실행 사용자 계정으로 `claude setup-token` 또는 `codex login` 완료(서비스로 돌리면 `HOME`/`CLAUDE_CONFIG_DIR`/`CODEX_HOME` 정합 확인). 호스트 결정 필요: 기존 EC2(무인 배포 호스트라 CLI 로그인 세션 유지가 관건) vs 별도 머신.
2. **배선 검증**: repository variable `REVIEW_SWARM_ENABLED=true` 설정 후 테스트 PR로 `publish.mode: single` 동작 확인. (러너에서 `node dist/cli.js doctor`로 사전 점검 가능.)
3. **GitHub App 등록**: 에이전트별 App 7개 생성(권한: Pull requests RW, Contents RO, webhook 비활성) → 이 저장소에 설치 → Actions secrets에 `SWARM_<AGENT>_APP_ID`/`SWARM_<AGENT>_PRIVATE_KEY` 등록 → `.review-swarm.yaml`의 `publish.mode`를 `apps`로 변경. 상세 절차는 review-swarm README.
4. **머지 차단(선택)**: 브랜치 보호 `Require approvals` 또는 워크플로 `fail-on: request_changes` + required check.

## 팀 지식 연결 (다이어그램의 "llm-wiki → Code Review Agent" 화살표)

review-swarm 의 Blackboard는 대상 저장소의 팀 규칙 파일을 컨텍스트로 수집한다. 위키의 팀 규칙(팀 규칙/ADR/knowledge 문서)을 리뷰에 반영하려면:

- 단기: 대상 저장소의 `AGENTS.md`/`.agents/` 규칙 파일을 최신으로 유지한다(이 저장소는 이미 [`../.agents/`](../.agents/) 체계 사용).
- 후속: Blackboard 수집 단계에서 WIKI MCP read-only(`llm-wiki-mcp-bearer-token` 계약 소비)로 팀 규칙 페이지를 조회하는 확장 — review-swarm 저장소 쪽 이슈로 진행.

리뷰 게시 외 쓰기 권한은 부여하지 않는다(레지스트리 default-deny 원칙).
