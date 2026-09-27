"""대상 서버 (docs/qa-platform-v2.md §13, 사용자 결정 2026-09-27). 기본은 dev, [+ 대상 추가]로 다른 서버를 등록한다.

- 요청은 플랫폼 서버가 보낸다. 운영 플랫폼(EC2)에서 localhost 는 EC2 자신이다 — 로컬 서버는 터널 공개 주소로 등록하거나,
  플랫폼을 노트북에서 띄워 localhost 로 쓴다(allow_local).
- live 는 등록할 수 없다(고정 규칙: 검증 대상은 dev, live 와 무관).
- 운영 플랫폼에서는 내부 주소(localhost · 사설 IP · 169.254 · 점 없는 도커 서비스 이름)를 막는다. 서버가 자기 내부를 부르지 않게.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from . import httpx

DEV_ID = "dev"
LIVE_HOSTS = ("api.moimyeon.plady.io", "moimyeon.plady.io", "www.moimyeon.plady.io")


class TargetError(ValueError):
    pass


_resolve = socket.getaddrinfo          # 시험에서 바꿔 끼운다


def normalize(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if u and "://" not in u:
        u = "https://" + u
    return u


def _internal(host: str) -> bool:
    if host in ("localhost",) or host.endswith(".localhost") or "." not in host:
        return True
    try:
        infos = _resolve(host, None)
    except OSError:
        raise TargetError(f"{host} 의 주소를 찾지 못했어요. 주소를 다시 확인해 주세요")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return True
    return False


def check(url: str, *, allow_local: bool, live_hosts: tuple = LIVE_HOSTS) -> str:
    """등록할 수 있는 주소면 정리한 주소를, 아니면 TargetError."""
    u = normalize(url)
    parts = urlsplit(u)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise TargetError("http:// 나 https:// 로 시작하는 서버 주소를 적어 주세요")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise TargetError("경로 없이 서버 주소만 적어 주세요 (예: https://abc.trycloudflare.com)")
    host = parts.hostname.lower()
    if host in live_hosts:
        raise TargetError("live 서버는 대상으로 쓸 수 없어요. 검증 대상은 dev 와 로컬 서버예요")
    if not allow_local:
        if parts.scheme != "https":
            raise TargetError("운영 플랫폼에서는 https 주소만 쓸 수 있어요. 로컬 서버는 cloudflared·ngrok 같은 터널로 https 주소를 받아 주세요")
        if _internal(host):
            raise TargetError("운영 플랫폼은 EC2 에서 요청을 보내서 localhost·내부 주소에 닿지 않아요. 로컬 서버는 터널 공개 주소로 등록하거나, "
                              "플랫폼을 노트북에서 띄워 localhost 로 써 주세요")
    return u


def probe(base_url: str, timeout: int = 8) -> dict:
    """등록할 때 한 번 불러 본다 — 헬스와 dev-sessions(빈 몸체면 400 이 정상). 결과는 보여 주기만 하고 막지 않는다."""
    out = {}
    r = httpx.request("GET", base_url + "/actuator/health", timeout=timeout)
    out["health"] = {"status": r.status, "ok": r.status == 200, "error": r.error}
    r = httpx.request("POST", base_url + "/v1/auth/dev-sessions", body={}, timeout=timeout)
    out["dev_sessions"] = {"status": r.status, "ok": r.status in (400, 200), "error": r.error}
    return out
