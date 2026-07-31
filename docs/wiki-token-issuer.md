# wiki-auth: 위키 접근 제어 + 단기 토큰 발급 런북

`wiki-auth` 사이드카([`docker/wiki-auth/app.py`](../docker/wiki-auth/app.py))가 llm-wiki 플랫폼의 두 접근 경로를 하나의 팀 비밀번호로 통제합니다. 상위 endpoint/secret 이름 계약은 [`platform-contract.md`](platform-contract.md)가 SSOT입니다.

| 경로 | 소비자 | 흐름 |
| --- | --- | --- |
| `https://wiki.agent.plady.io` (브라우저) | 팀원 | 세션 쿠키 없으면 `/auth/login`으로 302 → 비밀번호 입력 → 세션 쿠키(JWT, 기본 7일) → 원래 페이지로 복귀 |
| `https://mcp.agent.plady.io/mcp` (API) | 에이전트/스크립트 | `POST /auth/token`에 비밀번호 → 단기 JWT(기본 12h, 15m~24h) → `Authorization: Bearer`로 사용. 기존 정적 토큰(`llm-wiki-mcp-bearer-token`)도 계속 유효(하위호환) |

## 배선 구조

```
브라우저 → ALB → Caddy @wiki ─ /auth/* ──────────→ wiki-auth (로그인/세션 발급)
                        └─ 그 외: forward_auth → wiki-auth /auth/verify-browser
                                   └─ 204 → wiki-ui:1313 / 401·302 → 로그인
에이전트 → ALB → Caddy @mcp → mcp-proxy(nginx)
                        ├─ /auth/token ──────────→ wiki-auth (JWT 발급)
                        └─ 그 외: auth_request → wiki-auth /auth/verify
                                   └─ 정적 토큰 or JWT → llm-wiki:18765
```

- ALB 기본(default) 라우트는 health check 전용 plain 200만 응답한다 — 임의 Host 헤더로 wiki 세션 게이트를 우회하지 못하게 하기 위한 계약.
- 발급기는 `WIKI_TOKEN_PASSWORD_HASH`·`WIKI_TOKEN_JWT_SECRET` **둘 다** 있어야 켜진다. 하나라도 없으면 로그인/발급은 503이고 정적 토큰 검증만 동작한다(기존 스택과 동일 — 안전한 점진 롤아웃).
- 로컬 `compose.yaml`에는 Caddy가 없으므로 브라우저 게이트는 EC2 전용이다. 로컬 wiki-ui(`:1313`)는 종전대로 열려 있고, 로컬 MCP(`:18765`)는 동일한 발급/검증이 동작한다.

## 🙋 활성화 절차 (사람)

1. 비밀번호 해시 생성 (원문은 어디에도 저장하지 않는다):
   ```bash
   scripts/gen-wiki-token-password-hash.py
   ```
2. SSM에 해시와 서명 시크릿 저장 (`AWS_PROFILE=plady-service`):
   ```bash
   aws ssm put-parameter --region ap-northeast-2 --type SecureString \
     --name /plady/agent-platform/dev/wiki-token-password-hash --value "<1번 출력값>"
   aws ssm put-parameter --region ap-northeast-2 --type SecureString \
     --name /plady/agent-platform/dev/wiki-token-jwt-secret --value "$(openssl rand -hex 32)"
   ```
3. 재배포(`scripts/ec2-deploy.sh`가 SSM → `.env.ec2`로 주입) 또는 EC2에서 수동 반영:
   ```bash
   # EC2: .env.ec2 갱신 후
   sudo docker compose --env-file .env.ec2 -f compose.ec2.yaml up -d caddy mcp-proxy wiki-auth
   ```

## smoke

```bash
# 브라우저 게이트: 쿠키 없이 → 302 /auth/login
curl -si https://wiki.agent.plady.io/ | grep -i 'HTTP/\|location'
# MCP: 무인증 → 401 (기존 계약 유지)
curl -i https://mcp.agent.plady.io/mcp
# 발급 → 검증
eval "$(scripts/wiki-token.sh)"   # 비밀번호 프롬프트 → MCP_BEARER_TOKEN export
scripts/mcp-call.py list-tools --url https://mcp.agent.plady.io/mcp
```

## 운영 메모

- **비밀번호 변경**: 1~3번 반복. 해시만 바뀌므로 이미 발급된 세션/토큰은 만료까지 유효하다. 즉시 전체 무효화가 필요하면 `wiki-token-jwt-secret`도 회전한다.
- **정적 토큰 폐기(선택)**: 팀이 발급기 경로에 정착하면 `llm-wiki-mcp-bearer-token`을 회전해 구 토큰을 무효화하고, hermes 등 서버 소비자만 새 정적 토큰을 쓰게 한다.
- 실패 응답은 1초 지연으로 무차별 대입을 완화한다. 공개 endpoint이므로 비밀번호는 12자 이상(생성 스크립트가 강제).
- 쿠키는 `HttpOnly; Secure; SameSite=Lax`. TLS는 ALB 종단이므로 Secure 플래그가 유효하다.
