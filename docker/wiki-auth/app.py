#!/usr/bin/env python3
"""wiki-auth: llm-wiki 플랫폼의 접근 제어 사이드카 (stdlib 전용).

계약: docs/wiki-token-issuer.md. 두 가지 흐름을 한 프로세스로 서빙한다.

[A] MCP API 흐름 — mcp.agent.plady.io (mcp-proxy/nginx가 auth_request로 위임)
  POST /auth/token          {"password", "ttl_seconds"?} → 단기 JWT 발급
  GET  /auth/verify         Authorization 헤더 검증 (정적 토큰 or JWT) → 204/401

[B] 브라우저 흐름 — wiki.agent.plady.io (Caddy가 forward_auth로 위임)
  GET  /auth/verify-browser 세션 쿠키 검증 → 204 / 302 → /auth/login
  GET  /auth/login          비밀번호 입력 페이지
  POST /auth/login          비밀번호 검증 → 세션 쿠키(JWT) 발급 → 원래 경로로 302
  GET  /auth/logout         쿠키 제거

  GET  /health              → 200

환경변수:
  MCP_BEARER_TOKEN            기존 정적 토큰 (하위호환 검증용; 필수)
  WIKI_TOKEN_PASSWORD_HASH    pbkdf2_sha256:<iters>:<salt_hex>:<hash_hex>
                              (콜론 구분 — .env/compose 보간과 충돌하는 '$' 금지)
  WIKI_TOKEN_JWT_SECRET       HS256 서명 시크릿 (hex 권장)
  WIKI_SESSION_TTL            브라우저 세션 쿠키 수명 (기본 7일)
  두 secret 중 하나라도 비면 발급기/로그인은 꺼지고(503) 정적 토큰 검증만 동작.

secret 값·비밀번호는 절대 로그에 남기지 않는다.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8790"))
STATIC_TOKEN = os.environ.get("MCP_BEARER_TOKEN", "")
PASSWORD_HASH = os.environ.get("WIKI_TOKEN_PASSWORD_HASH", "")
JWT_SECRET = os.environ.get("WIKI_TOKEN_JWT_SECRET", "")
TTL_MIN = int(os.environ.get("WIKI_TOKEN_MIN_TTL", "900"))            # 15m
TTL_DEFAULT = int(os.environ.get("WIKI_TOKEN_DEFAULT_TTL", "43200"))  # 12h
TTL_MAX = int(os.environ.get("WIKI_TOKEN_MAX_TTL", "86400"))          # 24h
SESSION_TTL = int(os.environ.get("WIKI_SESSION_TTL", str(7 * 86400)))  # 7d
COOKIE_NAME = "wiki_session"
FAIL_DELAY_SECONDS = 1.0

_fail_lock = threading.Lock()

LOGIN_PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Plady Wiki 로그인</title>
<style>
  body {{ font-family: -apple-system, sans-serif; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; margin: 0; background: #f5f5f7; }}
  form {{ background: #fff; padding: 2rem 2.5rem; border-radius: 12px;
          box-shadow: 0 2px 12px rgba(0,0,0,.08); width: 20rem; }}
  h1 {{ font-size: 1.1rem; margin: 0 0 1rem; }}
  input[type=password] {{ width: 100%; box-sizing: border-box; padding: .6rem;
          border: 1px solid #ccc; border-radius: 8px; font-size: 1rem; }}
  button {{ width: 100%; margin-top: 1rem; padding: .6rem; border: 0; border-radius: 8px;
          background: #111; color: #fff; font-size: 1rem; cursor: pointer; }}
  .err {{ color: #c0392b; font-size: .85rem; margin: .5rem 0 0; }}
</style></head><body>
<form method="post" action="/auth/login">
  <h1>Plady Wiki</h1>
  <input type="password" name="password" placeholder="팀 비밀번호" autofocus required>
  <input type="hidden" name="next" value="{next}">
  {error}
  <button type="submit">들어가기</button>
</form></body></html>"""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issuer_configured() -> bool:
    return bool(PASSWORD_HASH) and bool(JWT_SECRET)


def check_password(password: str) -> bool:
    try:
        scheme, iters, salt_hex, hash_hex = PASSWORD_HASH.split(":")
        if scheme != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(derived, bytes.fromhex(hash_hex))
    except (ValueError, TypeError):
        return False


def mint_jwt(ttl: int, subject: str) -> tuple[str, int]:
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "sub": subject,
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_hex(8),
    }).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = _b64url(hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}", now + ttl


def verify_jwt(token: str) -> bool:
    if not JWT_SECRET:
        return False
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
            return False
        payload = json.loads(_b64url_decode(payload_b64))
        return int(payload.get("exp", 0)) > time.time()
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


def verify_bearer(auth_header: str) -> bool:
    if not auth_header.startswith("Bearer "):
        return False
    token = auth_header[len("Bearer "):].strip()
    if not token:
        return False
    if STATIC_TOKEN and hmac.compare_digest(token, STATIC_TOKEN):
        return True
    return verify_jwt(token)


def _fail_delay():
    with _fail_lock:  # 무차별 대입 완화: 실패를 직렬화 + 지연
        time.sleep(FAIL_DELAY_SECONDS)


def _safe_next(raw: str) -> str:
    # open redirect 방지: 사이트 내부 경로만 허용
    return raw if raw.startswith("/") and not raw.startswith("//") else "/"


class Handler(BaseHTTPRequestHandler):
    server_version = "wiki-auth/0.2"

    def _send(self, status: int, body: bytes = b"", headers: dict | None = None,
              content_type: str = "application/json"):
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if body:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_json(self, status: int, obj: dict, headers: dict | None = None):
        self._send(status, json.dumps(obj).encode(), headers)

    def log_message(self, fmt, *args):  # Authorization/쿠키가 찍히지 않게 경로/코드만
        print(f"{self.address_string()} {self.command} {self.path.split('?')[0]} "
              f"{args[1] if len(args) > 1 else ''}")

    # ---- 세션 쿠키 ----

    def _session_valid(self) -> bool:
        cookies = self.headers.get("Cookie", "")
        for part in cookies.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME and verify_jwt(value):
                return True
        return False

    def _login_html(self, next_path: str, error: str = "") -> bytes:
        err = '<p class="err">비밀번호가 올바르지 않습니다.</p>' if error else ""
        safe = urllib.parse.quote(_safe_next(next_path), safe="/?=&")
        return LOGIN_PAGE.format(next=safe, error=err).encode()

    # ---- 라우팅 ----

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = urllib.parse.parse_qs(query)

        if path == "/health":
            self._send_json(200, {"status": "ok", "issuer": "on" if issuer_configured() else "off"})

        elif path == "/auth/verify":
            if verify_bearer(self.headers.get("Authorization", "")):
                self._send(204)
            else:
                self._send_json(401, {"error": "invalid or expired token"},
                                {"WWW-Authenticate": "Bearer"})

        elif path == "/auth/verify-browser":
            if not issuer_configured():
                # 게이트 미구성(SSM 해시/시크릿 부재) 동안은 공개 유지 — 로그인
                # 페이지가 503뿐인데 302로 보내면 위키 전체가 잠겨버린다.
                # 값이 주입되는 순간부터 fail-closed로 전환된다.
                self._send(204)
            elif self._session_valid():
                self._send(204)
            else:
                original = self.headers.get("X-Forwarded-Uri", "/")
                location = "/auth/login?next=" + urllib.parse.quote(_safe_next(original), safe="")
                self._send(302, headers={"Location": location})

        elif path == "/auth/login":
            next_path = (params.get("next") or ["/"])[0]
            if self._session_valid():
                self._send(302, headers={"Location": _safe_next(next_path)})
            elif not issuer_configured():
                self._send(503, "wiki-auth not configured (password hash / jwt secret absent)".encode(),
                           content_type="text/plain; charset=utf-8")
            else:
                self._send(200, self._login_html(next_path), content_type="text/html; charset=utf-8")

        elif path == "/auth/logout":
            self._send(302, headers={
                "Location": "/auth/login",
                "Set-Cookie": f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax",
            })

        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.partition("?")[0]
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 4096)
            raw = self.rfile.read(length)
        except ValueError:
            self._send_json(400, {"error": "bad request"})
            return

        if path == "/auth/token":
            if not issuer_configured():
                self._send_json(503, {"error": "token issuer not configured (password hash / jwt secret absent)"})
                return
            try:
                body = json.loads(raw or b"{}")
                password = body.get("password", "")
                ttl = int(body.get("ttl_seconds", TTL_DEFAULT))
            except (ValueError, json.JSONDecodeError):
                self._send_json(400, {"error": "invalid JSON body"})
                return
            if not isinstance(password, str) or not password:
                self._send_json(400, {"error": "password required"})
                return
            ttl = max(TTL_MIN, min(ttl, TTL_MAX))
            if not check_password(password):
                _fail_delay()
                self._send_json(401, {"error": "invalid password"})
                return
            token, expires_at = mint_jwt(ttl, "wiki-mcp")
            self._send_json(200, {
                "token": token,
                "token_type": "Bearer",
                "expires_in": ttl,
                "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires_at)),
            })

        elif path == "/auth/login":
            if not issuer_configured():
                self._send(503, "wiki-auth not configured".encode(),
                           content_type="text/plain; charset=utf-8")
                return
            form = urllib.parse.parse_qs(raw.decode(errors="replace"))
            password = (form.get("password") or [""])[0]
            next_path = _safe_next((form.get("next") or ["/"])[0])
            if not check_password(password):
                _fail_delay()
                self._send(401, self._login_html(next_path, error="1"),
                           content_type="text/html; charset=utf-8")
                return
            token, _ = mint_jwt(SESSION_TTL, "wiki-ui")
            cookie = (f"{COOKIE_NAME}={token}; Path=/; Max-Age={SESSION_TTL}; "
                      f"HttpOnly; Secure; SameSite=Lax")
            self._send(302, headers={"Location": next_path, "Set-Cookie": cookie})

        else:
            self._send_json(404, {"error": "not found"})


def main():
    state = "on" if issuer_configured() else "OFF (static-token verify only)"
    print(f"wiki-auth listening on :{PORT} | issuer: {state}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
