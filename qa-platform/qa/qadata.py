"""dev 전용 QA 테스트 데이터 API(백엔드 PR #135, `/v1/dev/...`)를 부르는 얇은 클라이언트. docs/qa-platform-api.md §11.6.

- 호출은 전부 qa-host 테스트 계정 토큰(dev-sessions)으로 한다 — API 가 인증을 요구하고, 회원 UUID 는 서버(SSM)에만 있다.
- 지우는 것은 백엔드가 `[QA]` 접두로 막는다(E2201). 플랫폼은 그 규칙을 믿고 따로 검사하지 않는다.
- 여기서 하는 행위(삭제·초기화)는 테스트 실행이 아니라서 실행 기록에는 안 남고 감사 로그(events `qa_data.*`)에만 남는다.
"""
from __future__ import annotations

from . import httpx

LIST_OP = "listQaData"       # OpenAPI 에 이 op 가 있어야 백엔드가 dev QA API 를 갖춘 것


class QaData:
    def __init__(self, app):
        self.app = app

    # ---- 가능 여부 -------------------------------------------------------------
    @property
    def spec_has_api(self) -> bool:
        spec = self.app.spec.get()
        return bool(spec and LIST_OP in spec.ops)

    @property
    def actor(self) -> str | None:
        """토큰을 받을 테스트 계정 — qa-host 가 있으면 그것, 없으면 아무 계정."""
        actors = self.app.cfg.actors
        if "qa-host" in actors:
            return "qa-host"
        return next(iter(actors), None)

    def why_unavailable(self) -> str | None:
        if not self.spec_has_api:
            return "백엔드 API 문서에 dev QA 데이터 API(listQaData)가 없다 — dev 브랜치에 PR #135 가 배포됐는지 확인"
        if not self.actor:
            return "테스트 계정(QA_ACTORS)이 설정돼 있지 않아 dev API 에 인증할 수 없다"
        return None

    # ---- 호출 ------------------------------------------------------------------
    def _call(self, method: str, path: str, query: dict | None = None, body=None) -> tuple[bool, dict, int]:
        """(ok, data 또는 error, status). 네트워크 오류는 ok=False, error={"code": "NETWORK", "message": …}."""
        cfg = self.app.cfg
        try:
            token = self.app.runner.actors.token(self.actor, cfg.target_base_url)
        except Exception as e:  # 토큰 발급 실패도 화면에 그대로
            return False, {"code": "AUTH", "message": f"테스트 계정 토큰 발급 실패: {e}"}, 0
        url = cfg.target_base_url + path
        if query:
            from urllib.parse import urlencode
            url += "?" + urlencode({k: v for k, v in query.items() if v not in (None, "")})
        r = httpx.request(method, url, headers={"Accept": "application/json", "Authorization": "Bearer " + token}, body=body, timeout=cfg.request_timeout)
        if r.error:
            return False, {"code": "NETWORK", "message": r.error}, r.status
        js = r.json if isinstance(r.json, dict) else {}
        if r.status == 200 and js.get("result") == "SUCCESS":
            return True, js.get("data") or {}, r.status
        # 우리 규약(error: {code, message})이 아닐 수도 있다 — Spring 기본 오류 몸체는 error 가 문자열("Not Found")이고,
        # 인증 필터는 빈 몸체로 401/403 을 준다. 어떤 꼴이든 상태 코드와 몸체 요약을 그대로 보여 준다.
        err = js.get("error")
        if isinstance(err, dict):
            code, message = err.get("code") or str(r.status), err.get("message") or ""
        else:
            code, message = str(r.status), (str(err) if err else "") or (js.get("message") if isinstance(js.get("message"), str) else "") or (r.text or "")[:200]
        hint = ""
        if r.status == 404:
            hint = " — dev 서버에 아직 이 API 가 없다. 백엔드 PR #135 가 dev 에 배포됐는지 확인"
        elif r.status in (401, 403):
            hint = " — 인증이 거부됐다. 테스트 계정 토큰(dev-sessions)이 dev 에서 유효한지 확인"
        return False, {"code": code, "message": (message or "(몸체 없음)") + hint}, r.status

    def list(self) -> tuple[bool, dict, int]:
        return self._call("GET", "/v1/dev/qa-data")

    def delete_room(self, room_id: str) -> tuple[bool, dict, int]:
        return self._call("DELETE", f"/v1/dev/rooms/{room_id}")

    def delete_all(self, host_member_id: str | None = None, include_members: bool = False) -> tuple[bool, dict, int]:
        return self._call("DELETE", "/v1/dev/qa-data", query={"hostMemberId": host_member_id, "includeMembers": "true" if include_members else None})

    def reset_member(self, member_id: str) -> tuple[bool, dict, int]:
        return self._call("POST", f"/v1/dev/members/{member_id}/reset")

    def delete_member(self, member_id: str) -> tuple[bool, dict, int]:
        return self._call("DELETE", f"/v1/dev/members/{member_id}")

    def create_member(self) -> tuple[bool, dict, int]:
        """QA 테스트 회원 생성. 응답의 accessToken 은 쓰지 않는다 — 나중에 dev-sessions 로 memberId 만 있으면 토큰을 받는다."""
        ok, data, status = self._call("POST", "/v1/dev/members")
        if ok:
            data = {k: v for k, v in data.items() if k != "accessToken"}
        return ok, data, status

    # ---- 화면용 스냅샷 -----------------------------------------------------------
    def snapshot(self) -> dict:
        """정리 화면 한 장에 필요한 것: 가능 여부·목록·테스트 계정 이름 대응. 회원 UUID 는 이름으로 바꾸고 나머지는 앞 8자리만."""
        why = self.why_unavailable()
        if why:
            return {"available": False, "why": why, "rooms": [], "members": [], "actors": list(self.app.cfg.actors)}
        ok, data, status = self.list()
        if not ok:
            return {"available": True, "why": None, "error": data, "rooms": [], "members": [], "actors": list(self.app.cfg.actors)}
        by_uuid = {v: k for k, v in self.app.all_actors().items()}
        rooms = []
        for r in data.get("rooms") or []:
            host = r.get("hostMemberId")
            rooms.append(dict(r, host_label=(by_uuid.get(host) or (host[:8] + "…" if host else "(방장 없음)"))))
        members = [dict(m, label=by_uuid.get(m.get("memberId"))) for m in (data.get("members") or [])]
        return {"available": True, "why": None, "error": None, "rooms": rooms, "members": members, "actors": list(self.app.cfg.actors)}
