"""웹 푸시 수신기 — 플랫폼이 QA 회원의 웹 푸시 기기가 된다 (docs/qa-platform-v2.md §15.2).

FCM 웹 클라이언트를 흉내 내는 firebase-messaging 라이브러리로 FCM 토큰을 받아, 그 토큰을 QA 회원 이름으로
백엔드에 기기 등록(PUT /v1/members/me/web-push-subscriptions)한다. 이후 백엔드가 그 회원에게 보낸 웹 푸시가 여기로 온다.
받기만 한다. 알림이 왔다고 실행을 시작하지 않는다.

라이브러리와 Firebase 웹 앱 설정(QA_FCM_WEB_CONFIG)이 없으면 꺼진다. 처음에는 기본 대상(dev)만 지원한다.
"""
from __future__ import annotations

import asyncio
import json
import threading
import traceback

from . import httpx
from . import inbox as I
from .store import now_iso

SUB_PATH = "/v1/members/me/web-push-subscriptions"
SETTING_PATH = "/v1/members/me/notification-setting"       # 알림 수신 설정 (moimyeon-backend #147, MOI-544)


class PushError(RuntimeError):
    pass


def _lib():
    try:
        import firebase_messaging  # noqa: F401
        return firebase_messaging
    except Exception:
        return None


class PushReceivers:
    def __init__(self, cfg, store, actors):
        self.cfg, self.store, self.actors = cfg, store, actors
        self.base = cfg.target_base_url
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: dict[str, object] = {}
        self._lock = threading.Lock()

    # ---- 상태 ---------------------------------------------------------------------------
    def unavailable(self, base_url: str | None = None) -> str | None:
        """못 쓰는 이유. None 이면 쓸 수 있다."""
        if not self.cfg.fcm_web:
            return "Firebase 웹 앱 설정(QA_FCM_WEB_CONFIG)이 없다"
        if _lib() is None:
            return "firebase-messaging 라이브러리가 없다"
        if base_url and base_url.rstrip("/") != self.base:
            return "웹 푸시 수신은 기본 대상(dev)만 지원한다"
        return None

    def ready(self, actor: str, base_url: str) -> str | None:
        """이 회원의 웹 푸시를 받을 수 있나. None 이면 받는 중."""
        why = self.unavailable(base_url)
        if why:
            return why
        r = self.store.get_receiver(self.base, actor)
        if not r or not r["enabled"] or not r["push_token"]:
            return f"{actor} 의 웹 푸시 받기가 꺼져 있다. 알림함에서 켠다"
        if r["status"] != "listening":
            return f"{actor} 의 웹 푸시 수신기가 {r['status'] or '멈춤'} 상태다 ({r['error'] or ''})"
        return None

    # ---- 이벤트 루프 ---------------------------------------------------------------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, name="fcm-receivers", daemon=True).start()
                self._loop = loop
            return self._loop

    def _run(self, coro, timeout: float = 40):
        return asyncio.run_coroutine_threadsafe(coro, self._ensure_loop()).result(timeout)

    def start(self) -> None:
        """재시작 뒤 켜 두었던 수신기를 다시 연다(새로 등록하지 않는다 — 저장한 자격으로 다시 접속)."""
        if self.unavailable():
            return
        for r in self.store.list_receivers(self.base):
            if r["enabled"] and r["credentials"]:
                threading.Thread(target=self._restore, args=(r["actor"],), daemon=True).start()

    def _restore(self, actor: str) -> None:
        try:
            self._connect(actor, register=False)
        except Exception as ex:
            self.store.save_receiver(self.base, actor, status="error", error=str(ex)[:300])

    # ---- 켜기·끄기 -------------------------------------------------------------------------
    def enable(self, actor: str, *, operator: str) -> dict:
        why = self.unavailable()
        if why:
            raise PushError(why)
        if not self.actors.member_id(actor, self.base):
            raise PushError(f"테스트 계정 {actor} 가 없다")
        self.store.save_receiver(self.base, actor, enabled=1, status="connecting", error=None, operator=operator)
        try:
            self._connect(actor, register=True)
        except Exception as ex:
            self.store.save_receiver(self.base, actor, status="error", error=str(ex)[:300])
            raise PushError(f"웹 푸시 수신기를 켜지 못했다: {ex}") from ex
        return self.store.get_receiver(self.base, actor)

    def disable(self, actor: str, *, operator: str) -> None:
        r = self.store.get_receiver(self.base, actor) or {}
        client = self._clients.pop(actor, None)
        if client is not None:
            try:
                self._run(client.stop(), 10)
            except Exception:
                pass
        if r.get("push_token"):
            try:
                # 끄기는 그 회원의 웹 푸시 수신 설정을 끈다 — 백엔드가 모든 기기 등록을 지운다(#147). 예전 백엔드는 등록 해제 API
                self._call("PATCH", actor, SETTING_PATH, {"isWebPushAllowed": False}, fallback=("DELETE", SUB_PATH, {"registration": r["push_token"]}))
            except Exception:
                pass                     # 회원이 지워졌으면 등록도 이미 없다
        self.store.save_receiver(self.base, actor, enabled=0, status="off", error=None, push_token=None, operator=operator)

    # ---- 내부 ---------------------------------------------------------------------------
    def _call(self, method: str, actor: str, path: str, body: dict | None = None, *, fallback: tuple | None = None):
        """테스트 계정으로 백엔드를 부른다. 404·405 면 fallback (method, path, body) 로 — #147 전의 백엔드."""
        token = self.actors.token(actor, self.base)
        r = httpx.request(method, self.base + path, headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                          body=body, timeout=self.cfg.request_timeout)
        if fallback and r.status in (404, 405):
            return self._call(fallback[0], actor, fallback[1], fallback[2])
        if r.error or r.status >= 300:
            raise PushError(f"{method} {path} → {r.status or r.error}: {(r.text or '')[:200]}")
        return r.json

    def setting(self, actor: str) -> dict | None:
        """그 계정의 알림 수신 설정(GET notification-setting). 예전 백엔드거나 못 읽으면 None."""
        try:
            return ((self._call("GET", actor, SETTING_PATH) or {}).get("data")) or None
        except Exception:
            return None

    def _register_config(self):
        fm = _lib()
        c = self.cfg.fcm_web
        return fm.FcmRegisterConfig(project_id=c.get("projectId") or c.get("project_id"), app_id=c.get("appId") or c.get("app_id"),
                                    api_key=c.get("apiKey") or c.get("api_key"),
                                    messaging_sender_id=str(c.get("messagingSenderId") or c.get("messaging_sender_id") or ""),
                                    **({"vapid_key": c["vapidKey"]} if c.get("vapidKey") else {}))

    def _connect(self, actor: str, *, register: bool) -> None:
        fm = _lib()
        row = self.store.get_receiver(self.base, actor) or {}
        creds = json.loads(row["credentials"]) if row.get("credentials") else None

        def on_creds(new):
            self.store.save_receiver(self.base, actor, credentials=json.dumps(new))

        client = fm.FcmPushClient(self._on_message, self._register_config(), creds, on_creds, callback_context=actor,
                                  config=fm.FcmPushClientConfig(abort_on_sequential_error_count=None))
        token = self._run(client.checkin_or_register())
        self.store.save_receiver(self.base, actor, credentials=json.dumps(client.credentials))
        if register:                # [웹 푸시 받기] — 그 계정의 웹 푸시 수신을 켜고 이 기기를 등록한다(#147). 예전 백엔드는 등록만
            self._call("PATCH", actor, SETTING_PATH, {"isWebPushAllowed": True, "webPushRegistration": token},
                       fallback=("PUT", SUB_PATH, {"registration": token}))
        elif token != row.get("push_token"):
            self._call("PUT", actor, SUB_PATH, {"registration": token})   # 다시 접속했는데 토큰이 바뀌었으면 등록만 갱신(끈 회원이면 백엔드가 무시)
        me = {}
        try:
            me = (self._call("GET", actor, "/v1/members/me") or {}).get("data") or {}
        except Exception:
            pass
        self._run(client.start())
        old = self._clients.pop(actor, None)
        if old is not None:
            try:
                self._run(old.stop(), 10)
            except Exception:
                pass
        self._clients[actor] = client
        self.store.save_receiver(self.base, actor, push_token=token, status="listening", error=None,
                                 member_id=me.get("memberId") or row.get("member_id"), email=(me.get("email") or row.get("email") or "").lower() or None)

    def _on_message(self, msg: dict, persistent_id: str, actor) -> None:
        try:
            item = I.from_push(msg)
            item["persistent_id"] = persistent_id
            self.store.add_inbox(channel="web_push", base_url=self.base, actor=actor, address=None, type=item["type"], title=item["title"],
                                 body=item["body"], link=item["link"], event_id=item["event_id"], raw=json.dumps(msg, ensure_ascii=False)[:20000],
                                 dedup=I.dedup_key(item, actor or ""))
            self.store.save_receiver(self.base, actor, last_at=now_iso())
        except Exception:
            traceback.print_exc()
