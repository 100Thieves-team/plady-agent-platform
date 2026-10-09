"""알림 QA — 받은 웹 푸시·메일을 알림 한 건으로 읽고, 스크립트의 알림 기다리기 단계와 맞춘다 (docs/qa-platform-v2.md §15).

알림 내용의 정본은 백엔드 NotificationComposer 다(moimyeon-backend core-api). 메일에는 알림 종류가 실려 오지 않아서
제목으로 종류를 알아낸다. 제목은 종류마다 하나씩이다(모임이 취소되었어요 는 취소만).
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import json
import re
from email.utils import getaddresses

CHANNELS = ("web_push", "email")
CHANNEL_KO = {"web_push": "웹 푸시", "email": "메일"}

# 백엔드 EventType → 화면 이름, 메일 제목
TYPES = {
    "ROOM_APPLICATION_SUBMITTED": ("새 참가 신청", "새 참가 신청이 왔어요"),
    "ROOM_APPLICATION_ACCEPTED": ("참가 신청 수락", "참가 신청이 수락되었어요"),
    "ROOM_APPLICATION_REJECTED": ("참가 신청 반려", "참가 신청 결과를 알려드려요"),
    "ROOM_CONFIRMED": ("진행 확정", "모임이 확정되었어요"),
    "ROOM_APPLICATION_CLOSED": ("참가 신청 마감", "참가 신청이 마감되었어요"),     # 메일 제목으로만 구분된다. 웹 푸시의 eventType 은 ROOM_CONFIRMED
    "ROOM_COMPLETED": ("모임 완료", "모임이 완료되었어요"),
    "ROOM_CANCELED": ("모임 취소", "모임이 취소되었어요"),
    "ROOM_HOST_DELEGATED": ("방장 위임", "방장이 되었어요"),
    "ROOM_HOST_CHANGED": ("방장 바뀜", "방장이 바뀌었어요"),                         # 웹 푸시의 eventType 은 ROOM_HOST_DELEGATED
    "REVIEW_PUBLISHED": ("후기 공개", "새 후기가 도착했어요"),
    "ROOM_COMMENT_POSTED": ("새 댓글", "새 댓글이 달렸어요"),
    "ROOM_RECRUITING_REOPENED": ("모집 재개", "모집이 다시 열렸어요"),
}
TYPE_KO = {k: v[0] for k, v in TYPES.items()}
TITLE_TYPE = {v[1]: k for k, v in TYPES.items()}
TITLE_TYPE["참여자가 나가 모집이 다시 열렸어요"] = "ROOM_RECRUITING_REOPENED"         # 방장이 받는 문구
# 같은 eventType 안에서 받는 사람에 따라 제목이 다른 것 — 스크립트는 둘 중 아무 이름으로 써도 된다
SAME_EVENT = {"ROOM_APPLICATION_CLOSED": "ROOM_CONFIRMED", "ROOM_HOST_CHANGED": "ROOM_HOST_DELEGATED"}

_URL = re.compile(r"https?://\S+")


def type_of(title: str | None, event_type: str | None = None) -> str | None:
    """제목이 알려진 것이면 그 종류(더 자세하다), 아니면 웹 푸시의 eventType."""
    return TITLE_TYPE.get((title or "").strip()) or event_type or None


def same_type(want: str, got: str | None) -> bool:
    if not got:
        return False
    return want == got or SAME_EVENT.get(want) == got or SAME_EVENT.get(got) == want


def _find(d, *keys):
    for k in keys:
        if isinstance(d, dict) and k in d:
            return d[k]
    return None


def from_push(msg: dict) -> dict:
    """FCM 웹 푸시(복호화된 JSON) → 알림 한 건. 웹 SDK 와 같은 모양: notification · data · fcmOptions.link."""
    note = _find(msg, "notification") or {}
    data = _find(msg, "data") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            data = {}
    opts = _find(msg, "fcmOptions", "fcm_options") or {}
    title = _find(note, "title") or _find(data, "title")
    body = _find(note, "body") or _find(data, "body")
    link = _find(opts, "link") or _find(note, "click_action") or _find(data, "link")
    ev = _find(data, "eventType")
    return {"channel": "web_push", "title": title, "body": body, "link": link, "event_id": _find(data, "eventId"),
            "type": type_of(title, ev), "address": None}


def from_mail(raw: bytes) -> dict:
    """메일 원문 → 알림 한 건. 백엔드 메일은 평문: 제목 = 알림 제목, 본문 = 알림 본문 + 빈 줄 + 이동 주소."""
    m = email.message_from_bytes(raw, policy=email.policy.default)
    subject = str(m.get("Subject") or "").strip()
    part = m.get_body(preferencelist=("plain", "html"))
    text = part.get_content() if part else ""
    if part is not None and part.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    text = text.strip()
    urls = _URL.findall(text)
    link = urls[-1].rstrip(").,") if urls else None
    body = text[: text.rfind(urls[-1])].strip() if urls else text
    to = [a for _, a in getaddresses([str(m.get(h) or "") for h in ("Delivered-To", "To", "X-Original-To")]) if a]
    return {"channel": "email", "title": subject, "body": body, "link": link, "event_id": None, "type": type_of(subject),
            "address": to[0].lower() if to else None, "message_id": str(m.get("Message-ID") or "").strip(), "to_all": [a.lower() for a in to]}


def dedup_key(item: dict, extra: str = "") -> str:
    basis = item.get("message_id") or item.get("persistent_id") or json.dumps([item.get(k) for k in ("channel", "address", "title", "body", "link", "event_id")], ensure_ascii=False)
    return hashlib.sha256(f"{basis}|{extra}".encode()).hexdigest()[:32]


def path_of(link: str | None) -> str | None:
    """https://dev.moimyeon.plady.io/interviews/1 → /interviews/1"""
    if not link:
        return None
    m = re.match(r"^[a-z]+://[^/]+(/.*)?$", link)
    return (m.group(1) or "/") if m else link


# ---- API 가 보내는 알림 (백엔드 NotificationComposer · NotificationPolicy, dev 2026-10-09) ---------------------
# 채널: PUSH_AND_EMAIL 은 웹 푸시와 메일 둘 다. PUSH_ELSE_EMAIL 은 웹 푸시가 닿으면 메일을 보내지 않으니 web_push 만 기다린다. PUSH_ONLY 는 web_push.
# 이동 주소는 /interviews/{roomId} (백엔드 0fb9127b, 2026-10-05).
# always: 이 API 가 성공하면 늘 보내는 알림. False 면 조건이 맞을 때만 보내서 알림 단계가 없어도 빠졌다고 하지 않는다.
SENDS: dict[str, list[dict]] = {
    "submitRoomApplication": [{"type": "ROOM_APPLICATION_SUBMITTED", "to": "방장", "channels": ["web_push"], "always": True}],
    "acceptApplication": [{"type": "ROOM_APPLICATION_ACCEPTED", "to": "신청자", "channels": ["web_push", "email"], "always": True}],
    "rejectApplication": [{"type": "ROOM_APPLICATION_REJECTED", "to": "신청자", "channels": ["web_push"], "always": True}],
    "confirmRoom": [{"type": "ROOM_CONFIRMED", "to": "방장을 포함한 참여자 전원", "channels": ["web_push", "email"], "always": True},
                    {"type": "ROOM_APPLICATION_CLOSED", "to": "아직 대기 중이던 신청자", "channels": ["web_push"], "always": False}],
    "completeRoomProgress": [{"type": "ROOM_COMPLETED", "to": "방장을 포함한 확정 참여자 전원", "channels": ["web_push"], "always": True}],
    "autoCompleteQaRoom": [{"type": "ROOM_COMPLETED", "to": "방장을 포함한 확정 참여자 전원", "channels": ["web_push"], "always": True}],
    "roomLeave": [{"type": "ROOM_HOST_DELEGATED", "to": "방장이 나가고 참여자가 남으면 남은 참여자 전원(새 방장은 '방장이 되었어요', 나머지는 '방장이 바뀌었어요')",
                   "channels": ["web_push"], "always": False},
                  {"type": "ROOM_CANCELED", "to": "방장이 나가고 넘겨받을 참여자가 없으면 나간 방장과 대기 중이던 신청자", "channels": ["web_push", "email"], "always": False},
                  {"type": "ROOM_RECRUITING_REOPENED", "to": "참여자가 나가 최소 진행 인원보다 적어지면 방장과 남은 참여자", "channels": ["web_push"], "always": False}],
    "createRoomComment": [{"type": "ROOM_COMMENT_POSTED", "to": "작성자를 뺀 참여자 전원(작성자 말고 참여자가 없으면 보내지 않는다)", "channels": ["web_push"], "always": True}],
    # 후기는 작성 3시간 뒤 공개되고 그때 알림이 간다. 바로 공개하는 dev 도구가 없어 스크립트로는 기다릴 수 없다.
    "submitReview": [{"type": "REVIEW_PUBLISHED", "to": "후기 대상자(작성 3시간 뒤 공개될 때)", "channels": ["web_push"], "always": False, "no_wait": True}],
}


def _ok_status(expect: dict) -> bool:
    st = str((expect or {}).get("status") or "")
    return not (expect or {}).get("error_code") and (st.startswith("2") or (not st and (expect or {}).get("result") == "SUCCESS"))


def missing_notify(case, op_for) -> list[tuple[str, str]]:
    """정상 흐름에서 늘 알림을 보내는 API 를 성공으로 확인하는데 그 알림을 기다리는 단계가 없는 것 [(operationId, 알림 종류)].
    op_for(method, path) → operationId. 확인 대상(covers)이 있는 이 스크립트의 단계만 본다. 준비 단계·카드 단계는 보지 않는다."""
    waited = {str(s["notify"].get("type") or "") for s in case.steps if s.get("notify") and not s["notify"].get("none")}
    any_wait = any(s.get("notify") and not s["notify"].get("none") and not s["notify"].get("type") for s in case.steps)
    out = []
    for s in case.own_steps:
        if not s.get("request") or not s.get("covers") or not _ok_status(s.get("expect") or {}):
            continue
        try:
            op = op_for(str(s["request"].get("method") or ""), str(s["request"].get("path") or ""))
        except Exception:
            op = None
        for row in SENDS.get(op or "", []):
            if row["always"] and not any_wait and not any(same_type(row["type"], w) for w in waited):
                out.append((op, row["type"]))
    return list(dict.fromkeys(out))


def sends_text(ops) -> str:
    """Hermes 근거용: 이 API 들이 보내는 알림 표."""
    lines = []
    for op in dict.fromkeys(ops):
        for r in SENDS.get(op, []):
            if r.get("no_wait"):
                lines.append(f"- {op} → {r['type']}: {r['to']}. 스크립트로 기다릴 수 없다. 알림 단계를 쓰지 않는다")
                continue
            chans = ", ".join(r["channels"])
            lines.append(f"- {op} → {r['type']} · 받는 사람: {r['to']} · channels: [{chans}]" + ("" if r["always"] else " · 조건이 맞을 때만"))
    return "\n".join(lines)


# ---- 스크립트의 알림 기다리기 단계 ----------------------------------------------------------
NOTIFY_KEYS = {"to", "type", "channel", "channels", "within", "none", "expect"}
EXPECT_KEYS = {"title_contains", "body_contains", "link"}


class NotifyError(ValueError):
    pass


def parse_within(v) -> int:
    """'60s' · '2m' · 90 → 초. 5초에서 10분 사이."""
    if v is None:
        return 60
    m = re.fullmatch(r"\s*(\d+)\s*(s|m)?\s*", str(v))
    if not m:
        raise NotifyError(f"within 은 60s · 2m 같은 시간: {v!r}")
    sec = int(m.group(1)) * (60 if m.group(2) == "m" else 1)
    if not 5 <= sec <= 600:
        raise NotifyError(f"within 은 5초에서 10분 사이: {v!r}")
    return sec


def validate(spec) -> dict:
    """스크립트의 notify 블록 검사 → 정리한 블록. 틀리면 NotifyError."""
    if not isinstance(spec, dict):
        raise NotifyError("notify 는 맵")
    bad = sorted(set(spec) - NOTIFY_KEYS)
    if bad:
        raise NotifyError(f"notify 에 모르는 키 {bad} (허용: {sorted(NOTIFY_KEYS)})")
    if not str(spec.get("to") or "").strip():
        raise NotifyError("notify.to 에 받는 테스트 계정 이름이 필요하다 (예: qa-guest)")
    chans = spec.get("channels") if spec.get("channels") is not None else [spec.get("channel") or "web_push"]
    if isinstance(chans, str):
        chans = [chans]
    if not chans or any(c not in CHANNELS for c in chans):
        raise NotifyError(f"notify.channels 는 {list(CHANNELS)} 중에서: {chans!r}")
    typ = spec.get("type")
    if typ is not None and not (str(typ) in TYPES or str(typ).startswith("{{")):
        raise NotifyError(f"notify.type 은 {sorted(TYPES)} 중 하나: {typ!r}")
    exp = spec.get("expect") or {}
    if not isinstance(exp, dict) or set(exp) - EXPECT_KEYS:
        raise NotifyError(f"notify.expect 는 {sorted(EXPECT_KEYS)} 만 쓴다: {exp!r}")
    if spec.get("none") not in (None, True, False):
        raise NotifyError("notify.none 은 true/false (그 시간 동안 오지 않아야 통과)")
    out = {"to": str(spec["to"]).strip(), "channels": list(dict.fromkeys(chans)), "within": parse_within(spec.get("within"))}
    if typ is not None:
        out["type"] = str(typ)
    if exp:
        out["expect"] = exp
    if spec.get("none"):
        out["none"] = True
    return out


def describe(spec: dict) -> str:
    """화면용 한 줄: qa-guest · 참가 신청 수락 · 웹 푸시·메일 · 60초 안에"""
    chans = "·".join(CHANNEL_KO[c] for c in spec.get("channels") or ["web_push"])
    typ = TYPE_KO.get(spec.get("type") or "", spec.get("type") or "모든 알림")
    tail = f"{spec.get('within', 60)}초 동안 오지 않아야" if spec.get("none") else f"{spec.get('within', 60)}초 안에"
    return f"{spec.get('to')} · {typ} · {chans} · {tail}"


def match(item: dict, spec: dict) -> list[str]:
    """알림 한 건이 단계 조건과 맞는지. 맞지 않는 이유 목록(빈 목록이면 맞음). 받는 사람·채널은 고를 때 이미 맞췄다."""
    why = []
    if spec.get("type") and not same_type(spec["type"], item.get("type")):
        why.append(f"종류가 {TYPE_KO.get(item.get('type') or '', item.get('type') or '모름')}")
    exp = spec.get("expect") or {}
    if exp.get("title_contains") and str(exp["title_contains"]) not in (item.get("title") or ""):
        why.append(f"제목에 '{exp['title_contains']}' 가 없다")
    if exp.get("body_contains") and str(exp["body_contains"]) not in (item.get("body") or ""):
        why.append(f"본문에 '{exp['body_contains']}' 가 없다")
    if exp.get("link"):
        want, got = str(exp["link"]), item.get("link") or ""
        if not (got == want or path_of(got) == want or got.endswith(want)):
            why.append(f"이동 주소가 {path_of(got) or '없음'}")
    return why


def judge(spec: dict, got: dict[str, list[dict]]) -> tuple[bool, list[dict]]:
    """채널마다 받은 알림(그 회원, 그 시간 창) → (통과, 검사 목록). none 이면 맞는 알림이 하나도 없어야 통과."""
    checks = []
    for ch in spec.get("channels") or ["web_push"]:
        items = got.get(ch) or []
        hits = [x for x in items if not match(x, spec)]
        if spec.get("none"):
            checks.append({"check": CHANNEL_KO[ch], "channel": ch, "expected": "오지 않음", "actual": f"{len(hits)}건 옴" if hits else "오지 않음", "ok": not hits,
                           "ids": [x["id"] for x in hits if x.get("id")]})
        else:
            near = ""
            if not hits and items:
                near = " · 온 것: " + ", ".join(f"{x.get('title') or '제목 없음'}({'; '.join(match(x, spec))})" for x in items[:3])
            checks.append({"check": CHANNEL_KO[ch], "channel": ch, "expected": TYPE_KO.get(spec.get("type") or "", "알림") + " 도착",
                           "actual": (f"{len(hits)}건 도착" if hits else "오지 않음") + near, "ok": bool(hits),
                           "ids": [x["id"] for x in hits if x.get("id")]})
    return all(c["ok"] for c in checks), checks
