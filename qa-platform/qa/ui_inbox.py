"""알림함 화면과 알림 카드 (docs/qa-platform-v2.md §15.5). 노트북 기준 두 칸: 왼쪽 받는 계정, 오른쪽 받은 알림."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

from . import inbox as I
from .ui import e, kst

CSS = """
.ibx{display:grid;grid-template-columns:300px 1fr;gap:16px;align-items:start}
.ibx .who .li .dot{font-size:12px}.ibx .who .st{font-size:12px;color:var(--mut);line-height:1.45}.ibx .who .st span{display:block}
.ibx .who .st b{font-weight:600}.ibx .who .st .on{color:var(--ok)}.ibx .who .st .off{color:var(--mut)}.ibx .who .st .err{color:var(--bad)}
.ibx .who form{margin:0}.ibx .who .li{padding:10px 14px}
.ibx .fbar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:12px 16px;border-bottom:1px solid var(--line)}
.ibx .fbar .tabs a{margin:0}.ibx .fbar select{height:30px;font-size:13px}.ibx .fbar .sp{flex:1}
.ibx .health{display:flex;gap:18px;flex-wrap:wrap;padding:12px 16px;border-bottom:1px solid var(--line);font-size:13px;color:var(--ink2)}
.ibx .health span b{margin-right:4px}.ibx .health .ok{color:var(--ok)}.ibx .health .off{color:var(--mut)}.ibx .health .bad{color:var(--bad)}
.nt{display:flex;gap:12px;padding:14px 16px;border-bottom:1px solid var(--line)}.nt:last-child{border-bottom:0}
.nt .ico{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;flex:none;font-size:16px}
.nt.web_push .ico{background:var(--infobg);color:var(--info)}.nt.email .ico{background:#F1ECFE;color:#6d28d9}
.nt .bd{flex:1;min-width:0}.nt .top{display:flex;gap:8px;align-items:center;font-size:12px;color:var(--mut)}.nt .top .tm{margin-left:auto;white-space:nowrap}
.nt .tt{font-weight:700;margin-top:2px}.nt .tx{color:var(--ink2);margin-top:1px;white-space:pre-wrap}.nt .lk{font-size:12px;margin-top:4px}
.nt.new{animation:ntnew 2.4s ease-out}@keyframes ntnew{from{background:#FFF8E1}to{background:transparent}}
.nt details{margin:6px 0 0}.nt details pre{max-height:260px}
.ntl .nt{padding:10px 0}.ntl .nt:last-child{border-bottom:0}
"""

ICON = {"web_push": "🔔", "email": "✉"}


def _ago(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    s = int((datetime.now(timezone.utc) - dt).total_seconds())
    if s < 60:
        return "방금"
    if s < 3600:
        return f"{s // 60}분 전"
    if s < 86400:
        return f"{s // 3600}시간 전"
    return f"{s // 86400}일 전"


def card(x: dict, *, new: bool = False, raw: bool = True) -> str:
    """알림 한 건. 웹 푸시는 브라우저 알림처럼, 메일은 메일처럼."""
    ch = x["channel"]
    who = e(x.get("actor") or "") or f'<span class="mono">{e(x.get("address") or "알 수 없는 회원")}</span>'
    typ = I.TYPE_KO.get(x.get("type") or "")
    run = (f' · <a href="/runs/{e(x["run_id"])}">실행 단계 {int(x["step_ord"]) + 1}</a>' if x.get("run_id") and x.get("step_ord") is not None else "")
    link = I.path_of(x.get("link"))
    det = (f'<details><summary class="small mut">원본 보기</summary><pre>{e(x.get("raw") or "")}</pre></details>' if raw and x.get("raw") else "")
    return (f'<div class="nt {e(ch)}{" new" if new else ""}" data-id="{x["id"]}"><div class="ico">{ICON.get(ch, "•")}</div><div class="bd">'
            f'<div class="top"><b style="color:var(--ink2)">{I.CHANNEL_KO.get(ch, ch)}</b><span>{who}</span>'
            f'{("<span class=\"b none\">" + e(typ) + "</span>") if typ else ""}{run}'
            f'<span class="tm" title="{e(kst(x.get("received_at")))}">{_ago(x.get("received_at"))} · {e(kst(x.get("received_at")))}</span></div>'
            f'<div class="tt">{e(x.get("title") or "제목 없음")}</div>{("<div class=\"tx\">" + e(x.get("body")) + "</div>") if x.get("body") else ""}'
            f'{("<div class=\"lk mono\">→ " + e(link) + "</div>") if link else ""}{det}</div></div>')


def cards(items: list[dict], *, new: bool = False) -> str:
    return "".join(card(x, new=new) for x in items)


def _receiver_row(actor: str, r: dict | None, *, selected: bool, operator: str, push_why: str | None, mail_why: str | None, mail_mine) -> str:
    r = r or {}
    if push_why:
        push = f'<span class="off">웹 푸시 쓸 수 없음</span>'
    elif r.get("enabled") and r.get("status") == "listening":
        push = '<span class="on">● 웹 푸시 받는 중</span>'
    elif r.get("enabled") and r.get("status") == "error":
        push = f'<span class="err" title="{e(r.get("error"))}">웹 푸시 오류</span>'
    elif r.get("enabled"):
        push = f'<span class="off">웹 푸시 {e(r.get("status") or "연결 중")}</span>'
    else:
        push = '<span class="off">웹 푸시 꺼짐</span>'
    em = r.get("email")
    if mail_why:
        mail = '<span class="off">메일 쓸 수 없음</span>'
    elif em and mail_mine(em):
        mail = f'<span class="on" title="{e(em)}">메일 받는 중</span>'
    elif em:
        mail = f'<span class="err" title="{e(em)} 는 플랫폼 메일함 주소가 아니에요">메일 주소가 달라요</span>'
    else:
        mail = '<span class="off">메일 주소 모름</span>'
    dis = "" if operator else 'disabled title="담당자를 먼저 고르세요"'
    if push_why:
        btn = ""
    elif r.get("enabled"):
        btn = (f'<form method="post" action="/inbox/receivers/off" onclick="event.stopPropagation()"><input type="hidden" name="actor" value="{e(actor)}">'
               f'<input type="hidden" name="operator" value="{e(operator)}"><button {dis} title="이 계정의 웹 푸시 기기 등록을 지워요">끄기</button></form>')
    else:
        btn = (f'<form method="post" action="/inbox/receivers/on" onclick="event.stopPropagation()"><input type="hidden" name="actor" value="{e(actor)}">'
               f'<input type="hidden" name="operator" value="{e(operator)}"><button class="soft" {dis} title="플랫폼을 이 계정의 웹 푸시 기기로 등록해요">웹 푸시 받기</button></form>')
    last = f' · 마지막 {_ago(r.get("last_at"))}' if r.get("last_at") else ""
    return (f'<div class="li link{" sel" if selected else ""}" onclick="location.href=\'/inbox?{urlencode({"actor": actor})}\'"><div class="dot info">{e(actor.removeprefix("qa-")[:2].upper())}</div>'
            f'<div class="tx"><div class="t">{e(actor)}</div><div class="st">{push}{mail}{("<span>" + e(last.strip(" ·")) + "</span>") if last else ""}</div></div>{btn}</div>')


def inbox_page(*, items: list[dict], actors: list[str], receivers: dict, filters: dict, operator: str, push_why: str | None, mail_why: str | None,
               mail_state: dict, mail_mine, counts: dict, target: dict) -> str:
    actor = filters.get("actor") or ""
    who = (f'<div class="li link{" sel" if not actor else ""}" onclick="location.href=\'/inbox\'"><div class="dot">전체</div>'
           f'<div class="tx"><div class="t">모든 계정</div><div class="st">받은 알림 {counts.get("all", 0)}건</div></div></div>')
    who += "".join(_receiver_row(a, receivers.get(a), selected=a == actor, operator=operator, push_why=push_why, mail_why=mail_why, mail_mine=mail_mine)
                   for a in actors) or '<div class="empty"><b>테스트 계정이 없어요</b>QA 데이터 화면에서 QA 회원을 만들어 주세요.</div>'
    if push_why:
        push = f'<span><b>웹 푸시</b><span class="off">꺼짐</span> · {e(push_why)}</span>'
    else:
        on = sum(1 for r in receivers.values() if r.get("enabled") and r.get("status") == "listening")
        push = f'<span><b>웹 푸시</b><span class="ok">켜짐</span> · {on}개 계정 받는 중</span>'
    if mail_why:
        mail = f'<span><b>메일</b><span class="off">꺼짐</span> · {e(mail_why)}</span>'
    elif mail_state.get("error"):
        mail = f'<span><b>메일</b><span class="bad">읽기 실패</span> · {e(mail_state["error"])}</span>'
    else:
        mail = f'<span><b>메일</b><span class="ok">켜짐</span> · {e(mail_state.get("user"))} · 마지막 확인 {e(kst(mail_state.get("last_ok")) or "아직")}</span>'
    refresh = ("" if mail_why else
               f'<form method="post" action="/inbox/refresh" style="margin-left:auto"><input type="hidden" name="operator" value="{e(operator)}">'
               f'<button {"" if operator else "disabled title=\"담당자를 먼저 고르세요\""} title="메일함을 지금 읽어요. 평소에는 15초마다 읽어요">메일함 지금 읽기</button></form>')

    def tab(key, val, label):
        q = {k: v for k, v in {**filters, key: val}.items() if v}
        return f'<a class="{"on" if (filters.get(key) or "") == val else ""}" href="/inbox?{urlencode(q)}">{label}</a>'
    chans = "".join(tab("channel", v, l) for v, l in (("", "전체"), ("web_push", "웹 푸시"), ("email", "메일")))
    wins = "".join(tab("window", v, l) for v, l in (("", "최근 1시간"), ("10m", "10분"), ("today", "오늘"), ("all", "전체")))
    types = "".join(f'<option value="{e(k)}" {"selected" if filters.get("type") == k else ""}>{e(v)}</option>' for k, v in I.TYPE_KO.items())
    hidden = "".join(f'<input type="hidden" name="{k}" value="{e(v)}">' for k, v in filters.items() if v and k != "type")
    typesel = (f'<form method="get" action="/inbox" style="margin:0">{hidden}<select name="type" onchange="this.form.submit()">'
               f'<option value="">모든 종류</option>{types}</select></form>')
    if items:
        lst = cards(items)
    else:
        lst = ('<div class="empty" id="ibx-empty"><b>아직 받은 알림이 없어요</b>'
               'dev 웹에서 테스트 계정으로 댓글을 달거나 참가 신청을 해 보세요. 백엔드가 알림을 보내면 몇 초 안에 여기에 나타나요.<br>'
               '스크립트의 알림 기다리기 단계가 받은 알림도 여기에 쌓여요.</div>')
    q = urlencode({k: v for k, v in filters.items() if v})
    last_id = max((x["id"] for x in items), default=0)
    js = ("<script>(function(){var L=document.getElementById('ibx-list'),last=" + str(last_id) + ",q=" + repr(q) + ";"
          "function tick(){fetch('/inbox/items?after='+last+(q?'&'+q:''),{headers:{Accept:'text/html'}}).then(function(r){return r.ok?r.text():''}).then(function(h){"
          "if(!h||!h.trim())return;var t=document.createElement('div');t.innerHTML=h;var n=t.querySelectorAll('.nt');if(!n.length)return;"
          "var em=document.getElementById('ibx-empty');if(em)em.remove();for(var i=n.length-1;i>=0;i--){L.insertBefore(n[i],L.firstChild);last=Math.max(last,+n[i].dataset.id)}"
          "}).catch(function(){})}setInterval(tick,4000)})()</script>")
    tgt = "" if target.get("default") else f'<div class="flash err">알림 수신은 기본 대상(dev)만 지원해요. 지금 대상은 {e(target.get("name"))} 예요.</div>'
    return (f'<style>{CSS}</style><h1>알림함</h1>'
            f'<p class="lead">플랫폼이 테스트 계정의 웹 푸시 기기와 메일함이 되어, 백엔드가 실제로 보낸 알림을 받아 보여 줘요. 새 알림은 몇 초 안에 위에 나타나요.</p>{tgt}'
            f'<div class="ibx"><div class="card flush who" data-tour="inbox-who"><div class="ch"><h2>받는 계정</h2></div>{who}</div>'
            f'<div class="card flush" data-tour="inbox-list"><div class="health">{push}{mail}{refresh}</div>'
            f'<div class="fbar"><div class="tabs">{chans}</div><span style="width:8px"></span><div class="tabs">{wins}</div><span class="sp"></span>{typesel}</div>'
            f'<div id="ibx-list">{lst}</div></div></div>{js}')


def step_cards(items: list[dict]) -> str:
    """실행 결과의 알림 기다리기 단계 아래에 붙는 받은 알림."""
    if not items:
        return ""
    return f'<div class="ntl" style="margin:6px 0 4px 6px"><style>{CSS}</style>{"".join(card(x, raw=True) for x in items)}</div>'
