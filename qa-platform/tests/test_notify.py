"""알림 QA (docs/qa-platform-v2.md §15) — 플랫폼이 테스트 계정의 웹 푸시 기기와 메일함이 되고, 스크립트의 알림 기다리기 단계가 받은 알림을 맞춘다."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
import types
import unittest
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App, BadRequest  # noqa: E402
from qa import httpx, inbox as I, pushrecv, ui_inbox  # noqa: E402
from qa.cases import CaseError, parse_one  # noqa: E402
from qa.config import Config  # noqa: E402

SPEC = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"
BASE = "https://api.dev.moimyeon.plady.io"
MAILBOX = "moimyeon.qa@gmail.com"
FCM = {"apiKey": "k", "appId": "1:2:web:3", "projectId": "moimyeon-development", "messagingSenderId": "2"}

PUSH = {"notification": {"title": "새 댓글이 달렸어요", "body": "'[QA] 알림 룸'에 새 댓글이 달렸어요."},
        "data": {"eventId": "ev-1", "eventType": "ROOM_COMMENT_POSTED"}, "fcmOptions": {"link": "https://dev.moimyeon.plady.io/rooms/r-1"},
        "from": "2", "fcmMessageId": "m-1"}


def mail(to: str, subject: str, body: str, link: str, mid: str = "<1@ses>") -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "no-reply@moimyeon.plady.io", to, subject, mid
    m["Date"] = "Sat, 03 Oct 2099 10:00:00 +0000"
    m.set_content(f"{body}\n\n{link}")
    return m.as_bytes()


class Backend:
    """dev 흉내 — 요청을 적고, 댓글을 달면 그 룸 참여자에게 웹 푸시가 온 것처럼 수신기 콜백을 부른다."""

    def __init__(self):
        self.sent = []
        self.subs = {}
        self.on_comment = None
        self.emails = {"guest-1": "moimyeon.qa+qa-guest@gmail.com", "host-1": "moimyeon.qa+qa-host@gmail.com"}

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        self.sent.append((method, url, body))
        who = (headers or {}).get("Authorization", "").replace("Bearer tok-", "")
        if url.endswith("/v1/auth/dev-sessions"):
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"accessToken": "tok-" + body["memberId"]}}), 1)
        if url.endswith(pushrecv.SUB_PATH):
            if method == "PUT":
                self.subs[body["registration"]] = who
            else:
                self.subs.pop(body["registration"], None)
            return httpx.HttpResult(204 if method == "DELETE" else 200, {}, "", 1)
        if url.endswith("/v1/members/me"):
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"memberId": who, "email": self.emails.get(who, "x@qa.moimyeon.test")}}), 1)
        if url.endswith("/comments") and method == "POST":
            if self.on_comment:
                threading.Timer(0.3, self.on_comment).start()          # 백엔드 worker 가 조금 뒤에 보낸다
            return httpx.HttpResult(201, {}, json.dumps({"result": "SUCCESS", "data": {"commentId": "c-1"}}), 1)
        return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {}}), 1)


class FakeClient:
    """firebase_messaging.FcmPushClient 흉내."""
    made = []

    def __init__(self, callback, fcm_config, credentials=None, credentials_updated_callback=None, *, callback_context=None, config=None):
        self.callback, self.ctx, self.credentials = callback, callback_context, credentials
        self.started = False
        FakeClient.made.append(self)

    async def checkin_or_register(self):
        if not self.credentials:
            self.credentials = {"fcm": {"registration": {"token": f"fcm-{self.ctx}"}}}
        return self.credentials["fcm"]["registration"]["token"]

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    def push(self, msg, pid):
        self.callback(msg, pid, self.ctx)


def fake_lib():
    return types.SimpleNamespace(FcmRegisterConfig=lambda **kw: kw, FcmPushClient=FakeClient, FcmPushClientConfig=lambda **kw: kw)


class FakeImap:
    """imaplib.IMAP4_SSL 흉내 — INBOX 와 스팸함."""

    def __init__(self, boxes):
        self.boxes, self.cur = boxes, None

    def login(self, u, p):
        return "OK", []

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Junk) "/" "[Gmail]/&wqTVOA-"']

    def select(self, name, readonly=True):
        self.cur = name.strip('"')
        return ("OK", []) if self.cur in self.boxes else ("NO", [])

    def response(self, code):
        return code, [b"7"]

    def uid(self, cmd, *args):
        msgs = self.boxes[self.cur]
        if cmd == "search":
            q = args[-1]
            lo = int(q.split()[1].split(":")[0]) if q.startswith("UID") else 1
            return "OK", [" ".join(str(i) for i in range(lo, len(msgs) + 1)).encode()]
        return "OK", [(b"1 (BODY[] {n})", msgs[int(args[0]) - 1]), b")"]

    def logout(self):
        pass


class ParseTest(unittest.TestCase):
    def test_push_and_mail(self):
        p = I.from_push(PUSH)
        self.assertEqual((p["type"], p["title"], I.path_of(p["link"]), p["event_id"]), ("ROOM_COMMENT_POSTED", "새 댓글이 달렸어요", "/rooms/r-1", "ev-1"))
        m = I.from_mail(mail("moimyeon.qa+qa-guest@gmail.com", "참가 신청이 마감되었어요", "'[QA] x' 모임이 확정되어 참가 신청이 마감되었어요.",
                             "https://dev.moimyeon.plady.io/rooms/r-2"))
        self.assertEqual((m["type"], m["address"], m["link"]), ("ROOM_APPLICATION_CLOSED", "moimyeon.qa+qa-guest@gmail.com", "https://dev.moimyeon.plady.io/rooms/r-2"))
        self.assertNotIn("https://", m["body"])
        self.assertTrue(I.same_type("ROOM_CONFIRMED", m["type"]))                           # 같은 eventType 에서 받는 사람마다 제목이 다르다

    def test_validate_and_judge(self):
        for bad, frag in (({"type": "ROOM_CONFIRMED"}, "to"), ({"to": "qa-guest", "channels": ["sms"]}, "channels"), ({"to": "a", "type": "X"}, "type"),
                          ({"to": "a", "within": "1h"}, "within"), ({"to": "a", "within": "1s"}, "5초"), ({"to": "a", "expect": {"x": 1}}, "expect")):
            with self.assertRaises(I.NotifyError) as cm:
                I.validate(bad)
            self.assertIn(frag, str(cm.exception))
        spec = I.validate({"to": "qa-guest", "type": "ROOM_COMMENT_POSTED", "within": "2m", "expect": {"link": "/rooms/r-1"}})
        self.assertEqual((spec["channels"], spec["within"]), (["web_push"], 120))
        item = {**I.from_push(PUSH), "id": 3}
        ok, checks = I.judge(spec, {"web_push": [item]})
        self.assertTrue(ok)
        self.assertEqual(checks[0]["ids"], [3])
        other = {**item, "id": 4, "type": "ROOM_CANCELED", "title": "모임이 취소되었어요"}
        ok, checks = I.judge(spec, {"web_push": [other]})
        self.assertFalse(ok)
        self.assertIn("온 것: 모임이 취소되었어요(종류가 모임 취소)", checks[0]["actual"])           # 다른 종류가 온 것과 아무것도 안 온 것을 구분한다
        ok, _ = I.judge({**spec, "none": True}, {"web_push": []})
        self.assertTrue(ok)

    def test_case_with_notify_step(self):
        text = """
id: room.comment-notify
title: 댓글을 달면 다른 참여자에게 웹 푸시가 간다
suite: sanity
covers: [C.room.comment]
actor: qa-host
steps:
  - name: 댓글을 단다
    request: {method: POST, path: /v1/rooms/r-1/comments, body: {content: hi}}
    expect: {status: 201}
  - name: 참여자에게 알림이 온다
    notify: {to: qa-guest, type: ROOM_COMMENT_POSTED, within: 30s, expect: {link: "/rooms/{{roomId}}"}}
    covers: [C.room.comment]
  - name: 작성자에게는 오지 않는다
    notify: {to: qa-host, type: ROOM_COMMENT_POSTED, none: true, within: 10s}
"""
        c = parse_one(text, "t")
        self.assertEqual([bool(s.get("notify")) for s in c.steps], [False, True, True])
        self.assertEqual(len(c.api_steps), 1)
        self.assertNotIn("request", c.steps[1])
        c2 = parse_one(c.run_yaml(), "snap")                                                   # 실행 스냅샷을 다시 읽어도 같다
        self.assertEqual(c2.steps[1]["notify"], c.steps[1]["notify"])
        with self.assertRaises(CaseError):
            parse_one(text.replace("notify: {to: qa-host", "request: {method: GET, path: /x}\n    notify: {to: qa-host"), "t")
        self.assertIn("notify:", c.to_yaml())                                                   # 파일에 쓸 때 요청을 지어내지 않는다
        self.assertNotIn("NOTIFY", c.to_yaml())


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig, self.orig_lib = httpx.request, pushrecv._lib
        self.net = Backend()
        httpx.request = self.net
        pushrecv._lib = fake_lib
        FakeClient.made = []
        self.cfg = {"QA_DATA_DIR": self.tmp.name, "QA_SPEC_FILE": str(SPEC), "QA_SCENARIOS_DIR": str(Path(self.tmp.name, "none")),
                    "QA_ACTORS": json.dumps({"qa-host": "host-1", "qa-guest": "guest-1"}), "QA_OPERATORS": "bebe",
                    "QA_FCM_WEB_CONFIG": json.dumps(FCM), "QA_MAIL_USER": MAILBOX, "QA_MAIL_APP_PASSWORD": "x", "QA_MAIL_POLL": "3600"}
        self.app = App(Config(self.cfg))
        self.boxes = {"INBOX": [], "[Gmail]/&wqTVOA-": []}
        self.app.mail.connect = lambda: FakeImap(self.boxes)

    def tearDown(self):
        httpx.request, pushrecv._lib = self.orig, self.orig_lib
        for c in FakeClient.made:
            c.started = False
        self.tmp.cleanup()

    def run_case(self, text):
        from qa.cases import parse_one as p
        c = p(text, "t")
        self.app.cases[c.id] = c
        rid = self.app.create_run(trigger="manual", operator="bebe", case_ids=[c.id], sha=None, ref=None, pr_number=None, deploy_run_id=None,
                                  reason="", basis="", extra={}, session_hash=None, ip=None, notify=False, enqueue=False)
        self.app.runner.execute(rid)
        rc = self.app.store.list_run_cases(rid)[0]
        return rc, self.app.store.list_steps(rc["id"])

    CASE = """
id: room.comment-notify
title: 댓글 알림
suite: sanity
covers: [C.room.comment]
actor: qa-host
steps:
  - name: 댓글을 단다
    request: {method: POST, path: /v1/rooms/r-1/comments, body: {content: hi}}
    expect: {status: 201}
  - name: 참여자에게 웹 푸시가 온다
    notify: {to: qa-guest, type: ROOM_COMMENT_POSTED, within: 10s, expect: {link: /rooms/r-1}}
  - name: 작성자에게는 오지 않는다
    notify: {to: qa-host, type: ROOM_COMMENT_POSTED, none: true, within: 5s}
"""

    def test_receiver_on_push_arrives_and_step_matches(self):
        with self.assertRaises(BadRequest):
            self.app.receiver_on("qa-guest", operator="")
        self.app.receiver_on("qa-guest", operator="bebe")
        self.app.receiver_on("qa-host", operator="bebe")
        self.assertEqual(self.net.subs, {"fcm-qa-guest": "guest-1", "fcm-qa-host": "host-1"})          # 그 회원 이름으로 기기 등록
        r = self.app.store.get_receiver(BASE, "qa-guest")
        self.assertEqual((r["status"], r["email"]), ("listening", "moimyeon.qa+qa-guest@gmail.com"))
        guest = next(c for c in FakeClient.made if c.ctx == "qa-guest")
        self.net.on_comment = lambda: guest.push(PUSH, "p-1")
        rc, steps = self.run_case(self.CASE)
        self.assertEqual(rc["verdict"], "pass", rc["error"])
        self.assertEqual([s["verdict"] for s in steps], ["pass", "pass", "pass"])
        self.assertEqual(steps[1]["request"]["method"], "NOTIFY")
        self.assertEqual([x["title"] for x in steps[1]["inbox"]], ["새 댓글이 달렸어요"])            # 받은 알림이 단계에 붙는다
        guest.push(PUSH, "p-1")                                                                     # FCM 재전달은 한 번만 담긴다
        self.assertEqual(len(self.app.store.list_inbox(actor="qa-guest")), 1)
        # 작성자에게도 가면 실패
        host = next(c for c in FakeClient.made if c.ctx == "qa-host")
        self.net.on_comment = lambda: (guest.push(PUSH, "p-2"), host.push(PUSH, "p-3"))
        rc, steps = self.run_case(self.CASE)
        self.assertEqual((rc["verdict"], steps[2]["verdict"]), ("fail", "fail"))
        self.assertIn("1건 옴", steps[2]["error"])
        self.app.receiver_off("qa-guest", operator="bebe")
        self.assertNotIn("fcm-qa-guest", self.net.subs)
        acts = [x["action"] for x in self.app.store.list_events(20)]
        for a in ("notify.receiver.on", "notify.receiver.off"):
            self.assertIn(a, acts)

    def test_not_ready_is_skipped_but_case_goes_on(self):
        self.net.on_comment = None
        rc, steps = self.run_case(self.CASE)
        self.assertEqual(rc["verdict"], "pass")                                                     # API 단계는 통과
        self.assertEqual([s["verdict"] for s in steps], ["pass", "skipped", "skipped"])
        self.assertIn("웹 푸시 받기가 꺼져 있다", rc["error"])
        self.assertIn("알림 확인을 건너뛰었다", rc["error"])

    def test_mail_reader_and_email_step(self):
        self.boxes["INBOX"].append(mail("someone@else.com", "광고", "x", "https://x.io"))                         # QA 주소가 아니면 담지 않는다
        self.boxes["[Gmail]/&wqTVOA-"].append(mail("moimyeon.qa+qa-guest@gmail.com", "참가 신청이 수락되었어요", "'[QA] 룸' 모임에 참여할 수 있게 되었어요.",
                                                   "https://dev.moimyeon.plady.io/rooms/r-9", "<2@ses>"))
        self.assertEqual(self.app.mail.poll(), 1)                                                   # 스팸함도 읽는다
        self.assertEqual(self.app.mail.poll(), 0)                                                   # 이미 읽은 것은 다시 담지 않는다
        x = self.app.store.list_inbox(channel="email")[0]
        self.assertEqual((x["actor"], x["type"], I.path_of(x["link"])), ("qa-guest", "ROOM_APPLICATION_ACCEPTED", "/rooms/r-9"))
        self.assertIsNone(self.app.notify_ready("qa-guest", "email", BASE))
        self.net.emails["host-1"] = "qa-abc@qa.moimyeon.test"
        self.app._actor_email("qa-host", refresh=True)
        self.assertIn("플랫폼 메일함 주소가 아니다", self.app.notify_ready("qa-host", "email", BASE))
        self.assertIn("기본 대상(dev)만", self.app.notify_ready("qa-guest", "email", "https://abc.trycloudflare.com"))
        case = """
id: app.accept-mail
title: 수락 메일
suite: sanity
covers: [C.application.accept]
actor: qa-host
steps:
  - name: 아무 호출
    request: {method: GET, path: /v1/members/me}
    expect: {status: 200}
  - name: 신청자에게 수락 메일이 온다
    notify: {to: qa-guest, channel: email, type: ROOM_APPLICATION_ACCEPTED, within: 10s}
"""
        self.app.store._x("UPDATE inbox SET received_at='2099-01-01T00:00:00Z'")                      # 단계보다 뒤에 온 메일로
        rc, steps = self.run_case(case)
        self.assertEqual(rc["verdict"], "pass", rc["error"])
        self.assertEqual(steps[1]["inbox"][0]["channel"], "email")

    def test_inbox_page(self):
        self.app.receiver_on("qa-guest", operator="bebe")
        next(c for c in FakeClient.made if c.ctx == "qa-guest").push(PUSH, "p-9")
        items = self.app.inbox_items({})
        self.assertEqual(len(items), 1)
        receivers = {r["actor"]: r for r in self.app.store.list_receivers(BASE)}
        html = ui_inbox.inbox_page(items=items, actors=self.app.notify_actors(), receivers=receivers, filters={}, operator="bebe",
                                   push_why=self.app.push.unavailable(), mail_why=self.app.mail.unavailable(),
                                   mail_state={"user": MAILBOX}, mail_mine=self.app.mail.mine, counts={"all": 1}, target={"default": True})
        for frag in ("알림함", "● 웹 푸시 받는 중", "새 댓글이 달렸어요", "→ /rooms/r-1", "웹 푸시 받기", "메일 받는 중", "메일함 지금 읽기"):
            self.assertIn(frag, html)
        self.assertEqual(self.app.inbox_items({}, after_id=items[0]["id"]), [])
        self.assertEqual(len(self.app.inbox_items({"channel": "email"})), 0)

    def test_unavailable_without_config(self):
        a = App(Config({**self.cfg, "QA_DATA_DIR": self.tmp.name + "/b", "QA_FCM_WEB_CONFIG": "", "QA_MAIL_USER": ""}))
        self.assertIn("QA_FCM_WEB_CONFIG", a.push.unavailable())
        self.assertIn("QA_MAIL_USER", a.mail.unavailable())
        with self.assertRaises(BadRequest):
            a.receiver_on("qa-guest", operator="bebe")
        self.assertIn("QA_FCM_WEB_CONFIG", a.notify_ready("qa-guest", "web_push", BASE))


if __name__ == "__main__":
    unittest.main()
