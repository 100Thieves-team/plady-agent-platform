"""Sanity 화면 (docs/qa-platform-v2.md §4, §7.3) — 왼쪽 PR 목록, 오른쪽 고른 PR 의 Sanity. 노트북 기준."""
from __future__ import annotations

from datetime import datetime, timezone

from . import sanity as S
from .ui import badge, e, h, kst

CSS = """<style>
.split{display:grid;grid-template-columns:380px minmax(0,1fr);gap:16px;align-items:start}
.split .plist{position:sticky;top:22px;max-height:calc(100vh - 44px);overflow:auto}
.steps{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;padding:14px 18px}
.stp{display:flex;align-items:center;gap:8px}.stp .c{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:12px;flex:none;background:var(--graybg);color:var(--mut)}
.stp.done .c{background:var(--info);color:#fff}.stp.need .c{background:var(--warn);color:#fff}.stp.run .c{background:var(--infobg);color:var(--info);box-shadow:0 0 0 2px var(--info) inset}.stp.bad .c{background:var(--bad);color:#fff}
.stp .n{font-weight:700;font-size:13px;line-height:1.3}.stp .d{color:var(--mut);font-size:12px}.stp.need .d{color:var(--warn);font-weight:600}
.banner{display:flex;gap:12px;align-items:center;padding:12px 18px;border-top:1px solid var(--line)}.banner b{display:block}.banner span{color:var(--ink2);font-size:13px}
.banner.warn{background:var(--warnbg)}.banner.bad{background:var(--badbg)}.banner.ok{background:var(--okbg)}.banner.info{background:var(--infobg)}
.find{display:grid;grid-template-columns:1fr 1fr 1.15fr;gap:12px;padding:16px 18px;border-bottom:1px solid var(--line)}.find:last-child{border-bottom:0}
.find .hd{grid-column:1/-1;display:flex;align-items:baseline;gap:10px}.find .hd .k{font-size:12px;font-weight:700;color:var(--warn);white-space:nowrap}.find .hd .k.info{color:var(--mut)}
.find .hd .t{font-weight:700;flex:1}
.box{background:var(--bg);border-radius:10px;padding:10px 12px;font-size:13px;color:var(--ink2);word-break:break-word}.box b{display:block;font-size:11px;color:var(--mut);margin-bottom:3px}
.box.q{background:var(--infobg)}.box.q b{color:var(--info)}.box.q .rec{margin-top:6px;color:var(--mut);font-size:12px}
.box.q form{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap;align-items:center}.box.q input[name=note]{height:30px;flex:1;min-width:120px;font-size:12px}
.box.q form button{height:30px;font-size:12px;padding:0 10px}
.done-mark{color:var(--ok);font-weight:700;font-size:13px;margin-top:10px}.done-mark.cont{color:var(--warn)}
.reqs{margin:0;padding:0;list-style:none}.reqs li{display:grid;grid-template-columns:44px 1fr;gap:6px;font-size:13px;color:var(--ink2);padding:2px 0}
.metrics{display:grid;grid-template-columns:repeat(3,1fr)}.metrics div{padding:14px 18px;border-right:1px solid var(--line)}.metrics div:last-child{border-right:0}
.metrics span{color:var(--mut);font-size:12px}.metrics b{display:block;font-size:22px;font-weight:800}
.logl{font-size:12px;color:var(--ink2);padding:8px 18px;border-bottom:1px solid var(--line);display:flex;gap:10px}.logl:last-child{border-bottom:0}.logl .mut{white-space:nowrap}
dialog{border:0;border-radius:16px;padding:22px 24px 18px;width:480px;box-shadow:0 16px 48px rgba(0,0,0,.18)}dialog::backdrop{background:rgba(25,31,40,.28)}
dialog h3{margin:0 0 4px;font-size:18px}dialog .sd{color:var(--ink2);margin:0 0 14px}dialog .mf{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
</style>"""
JS = """<script>document.addEventListener('click',function(ev){var d=ev.target.closest('[data-dialog]');if(d){var x=document.getElementById(d.dataset.dialog);if(x)x.showModal()}
var c=ev.target.closest('[data-close-dialog]');if(c)c.closest('dialog').close()});
document.addEventListener('submit',function(ev){var b=ev.submitter;if(b&&b.classList.contains('primary')){setTimeout(function(){b.disabled=true;b.textContent='보내는 중…'},0)}});</script>"""


def _ago(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    h_ = int((datetime.now(timezone.utc) - dt).total_seconds() // 3600)
    return f"{h_}시간 전" if h_ < 24 else f"{h_ // 24}일 전"


def _status(s: dict | None, api: bool) -> str:
    if s:
        return f'<span class="b {S.STATUS_BADGE.get(s["status"], "none")}">{e(S.STATUS_KO.get(s["status"], s["status"]))}</span>'
    return '<span class="b none">검증 안 함</span>' if api else ""


def _pr_row(p: dict, sel: int | None) -> str:
    return (f'<a class="li {"sel" if p["number"] == sel else ""} {"" if p["api"] else "faded"}" href="/sanity/{p["number"]}">'
            f'<div class="tx"><div class="t">#{p["number"]} {e(p["title"])}</div>'
            f'<div class="d">{e(p.get("author"))} · {_ago(p.get("merged_at"))} · 파일 {p["changed_files"]}개 '
            f'<span style="color:var(--ok)">+{p["additions"]:,}</span> <span style="color:var(--bad)">−{p["deletions"]:,}</span></div></div>{_status(p.get("sanity"), p["api"])}</a>')


def _pr_head(p: dict, badge_html: str, actions: str) -> str:
    link = f' · <a href="{e(p["url"])}">GitHub</a>' if p.get("url") else ""
    return (f'<div class="ch" style="align-items:flex-start"><div style="flex:1;min-width:0"><div class="small mut">PR #{p["number"]} · {e(p.get("author"))} · {_ago(p.get("merged_at"))} 머지 · 파일 {p["changed_files"]}개{link}</div>'
            f'<div style="font-size:17px;font-weight:800;margin-top:2px">{e(p["title"])}</div><div style="margin-top:6px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">{badge_html}</div></div>{actions}</div>')


def _start_dialog(p: dict, operator: str, target: str) -> str:
    return (f'<dialog id="dlg-start"><h3>PR #{p["number"]} Sanity 를 시작할까요?</h3><p class="sd">{e(p["title"])}</p>'
            f'<div class="kvl" style="border:1px solid var(--line);border-radius:10px;padding:2px 14px;font-size:13px">'
            f'<div style="display:flex;justify-content:space-between;padding:8px 0"><span class="mut">담당자</span><b>{e(operator)}</b></div>'
            f'<div style="display:flex;justify-content:space-between;padding:8px 0;border-top:1px solid var(--line)"><span class="mut">대상</span><b class="mono">{e(target)}</b></div>'
            f'<div style="display:flex;justify-content:space-between;padding:8px 0;border-top:1px solid var(--line)"><span class="mut">하는 일</span><b>스펙 찾기 → 점검 → 준비 → 스크립트 → 실행</b></div></div>'
            f'<p class="small mut" style="margin:10px 0 0">스펙이 모호하거나 코드와 다르면 그 자리에서 멈춰요. Hermes 가 만든 스크립트는 검증을 통과하면 바로 저장돼요(Hermes 작성 표시). 시작한 사람과 시각은 감사 로그에 남아요.</p>'
            f'<form method="post" action="/sanity/start" class="mf"><input type="hidden" name="pr" value="{p["number"]}"><input type="hidden" name="operator" value="{e(operator)}">'
            f'<button type="button" data-close-dialog>닫기</button><button class="primary lg" {"" if operator else "disabled"}>시작하기</button></form></dialog>')


def _not_started(p: dict, operator: str, target: str, hermes: bool) -> str:
    why = "" if hermes else '<p class="hint bad" style="padding:0 18px">HERMES_API_KEY 가 없어 지금은 시작할 수 없어요.</p>'
    if p["api"]:
        body = ('<div class="empty" style="padding:48px"><b>아직 이 PR 을 검증하지 않았어요</b>시작하면 관련 스펙 찾기 → 스펙 점검 → 케이스 준비 → 스크립트 만들기 → 실행 순서로 진행해요.'
                '<br>스펙이 모호하거나 코드와 다르면 그 자리에서 멈추고 알려 드려요.</div>')
        btn = f'<button class="primary lg" data-dialog="dlg-start" data-tour="start" {"" if (operator and hermes) else "disabled"}>Sanity 시작</button>'
        st = '<span class="b none">검증 안 함</span>'
    else:
        body = '<div class="empty" style="padding:48px"><b>API 를 바꾼 파일이 없어요</b>인프라·로그·문서만 바뀐 PR 이에요. 보통은 Sanity 가 필요 없어요.</div>'
        btn = f'<button class="lg" data-dialog="dlg-start" {"" if (operator and hermes) else "disabled"}>그래도 시작</button>'
        st = '<span class="small mut">API 변경 없음</span>'
    return f'<div class="card flush">{_pr_head(p, st, btn)}{why}{body}</div>{_start_dialog(p, operator, target)}'


def _steps(s: dict) -> str:
    step, st = s.get("step") or 0, s["status"]
    out = ""
    last = {x["step"]: x["text"] for x in s.get("log") or []}
    for i, name in enumerate(S.STEPS, 1):
        cls, mark = "", str(i)
        if i < step or (i == step and st not in ("running", "queued", "needs_spec", "error")) or (i == step == 5):
            cls, mark = "done", "✓"
        if i == step and st == "needs_spec":
            cls, mark = "need", "!"
        elif i == step + 1 and st in ("running", "queued"):
            cls = "run"
        elif i == step and st in ("error",):
            cls, mark = "bad", "✕"
        out += f'<div class="stp {cls}"><div class="c">{mark}</div><div><div class="n">{name}</div><div class="d">{e(last.get(i, ""))[:40]}</div></div></div>'
    return f'<div class="steps" data-tour="steps">{out}</div>'


def _banner(s: dict, left: int) -> str:
    st = s["status"]
    if st in ("queued", "running"):
        return f'<div class="banner info"><div><b>{"기다리는 중이에요" if st == "queued" else "Hermes 와 플랫폼이 진행하고 있어요"}</b><span>이 화면은 4초마다 새로 고쳐져요. 창을 닫아도 계속 돌아요.</span></div></div>'
    if st == "needs_spec":
        return (f'<div class="banner warn"><div><b>{"스펙을 정해야 할 곳이 " + str(left) + "군데 있어요" if left else "모두 정했어요. 이어서 진행할 수 있어요"}</b>'
                f'<span>정하면 케이스를 준비하고 스크립트를 만들어 dev 에서 확인해요. [이대로 계속]하면 정하지 않은 항목에 걸린 케이스는 스크립트를 만들지 않아요.</span></div></div>')
    if st == "passed":
        return '<div class="banner ok"><div><b>이 PR 이 닿는 케이스가 모두 통과했어요</b></div></div>'
    if st == "failed":
        return '<div class="banner bad"><div><b>실패한 스크립트가 있어요</b><span>실행 결과에서 Hermes 실패 분석을 확인해 주세요.</span></div></div>'
    if st == "empty":
        return f'<div class="banner info"><div><b>확인할 것이 없어요</b><span>{e((s.get("log") or [{}])[-1].get("text", ""))}</span></div></div>'
    return f'<div class="banner bad"><div><b>{e(S.STATUS_KO.get(st, st))}</b><span>{e(s.get("error") or "다시 시작하거나 이어서 할 수 있어요")}</span></div></div>'


def _finding(f: dict, sid: str, operator: str, can_edit: bool) -> str:
    blocking = f["kind"] in S.BLOCKING
    res = ""
    if f.get("resolved_at"):
        how = {"recommended": "추천대로 정했어요", "other": "다르게 정했어요", "continued": "정하지 않고 계속했어요"}.get(f.get("resolution"), "정했어요")
        res = (f'<div class="done-mark {"cont" if f.get("resolution") == "continued" else ""}">✓ {how} · {e(f.get("resolved_by"))} · {kst(f.get("resolved_at"))}'
               f'{(" · " + e(f["note"])) if f.get("note") else ""}</div>')
    elif blocking and can_edit:
        res = (f'<form method="post" action="/sanity/{e(sid)}/resolve"><input type="hidden" name="fid" value="{e(f["id"])}"><input type="hidden" name="operator" value="{e(operator)}">'
               f'<button class="primary" name="choice" value="recommended" {"" if operator else "disabled"}>추천대로</button>'
               f'<input name="note" placeholder="다르게 정한다면 어떻게"><button name="choice" value="other" {"" if operator else "disabled"}>다르게</button></form>')
    extra = f'<div class="small mut" style="margin-top:6px">요구 {e(", ".join(f["reqs"]))}</div>' if f.get("reqs") else ""
    scripts = f'<div class="small mut" style="margin-top:6px">스크립트 {" ".join("<a class=mono href=/cases/" + e(x) + ">" + e(x) + "</a>" for x in f["scripts"])}</div>' if f.get("scripts") else ""
    q = (f'<div class="box q"><b>질문</b>{e(f.get("question"))}<div class="rec">{e(f.get("suggestion"))}</div>{res}</div>' if (f.get("question") or res)
         else f'<div class="box"><b>메모</b>{e(f.get("suggestion"))}</div>')
    src = "Hermes 가" if f.get("source") == "hermes" else "플랫폼이"
    return (f'<div class="find"><div class="hd"><span class="k {"" if blocking else "info"}">{e(S.KIND_KO.get(f["kind"], f["kind"]))}</span><span class="t">{e(f["title"])}</span>'
            f'<span class="small mut">{src} 찾음</span></div>'
            f'<div class="box"><b>스펙</b>{e(f.get("spec"))}{extra}</div><div class="box"><b>코드</b>{e(f.get("code"))}{scripts}</div>{q}</div>')


def _detail(p: dict, s: dict, *, operator: str, cases: list[dict], run: dict | None, history: list[dict]) -> str:
    st = s["status"]
    live = st in ("queued", "running")
    fs = s.get("findings") or []
    left = sum(1 for f in fs if f["kind"] in S.BLOCKING and not f.get("resolved_at"))
    sid = s["id"]
    acts = ""
    if live:
        acts = (f'<form method="post" action="/sanity/{e(sid)}/cancel"><input type="hidden" name="operator" value="{e(operator)}">'
                f'<button class="danger lg" {"" if operator else "disabled"}>그만두기</button></form>')
    else:
        cont = "" if st in ("passed", "empty") else f'<button class="primary lg" data-dialog="dlg-cont" {"" if operator else "disabled"}>{"이대로 계속" if st == "needs_spec" else "이어서 하기"}</button>'
        acts = (f'<div style="display:flex;gap:8px"><form method="post" action="/sanity/{e(sid)}/recheck"><input type="hidden" name="operator" value="{e(operator)}">'
                f'<button class="lg" {"" if operator else "disabled"}>{"위키 고친 뒤 다시 점검" if st == "needs_spec" else "다시 점검"}</button></form>'
                + (f'<button class="lg" data-dialog="dlg-start" {"" if operator else "disabled"}>새로 시작</button>' if st in ("passed", "failed", "empty") else "") + f'{cont}</div>')
    head = _pr_head(p, f'<span class="b {S.STATUS_BADGE.get(st, "none")}">{e(S.STATUS_KO.get(st, st))}</span><span class="small mut">{e(s["operator"])} 가 {kst(s["created_at"])} 에 시작</span>'
                    + (f'<a class="small" href="/runs/{e(run["id"])}">실행 결과 {badge(run.get("verdict") or run["status"])}</a>' if run else ""), acts)
    blocking = [f for f in fs if f["kind"] in S.BLOCKING]
    other = [f for f in fs if f["kind"] not in S.BLOCKING]
    fhtml = ""
    if fs:
        slack_btn = (f'<form method="post" action="/sanity/{e(sid)}/slack" style="margin:0"><input type="hidden" name="operator" value="{e(operator)}">'
                     f'<button {"" if (operator and left) else "disabled"}>남은 질문 Slack 으로 묻기</button></form>') if blocking else ""
        fhtml = (f'<div class="card flush" data-tour="findings"><div class="ch"><h2>스펙 확인{h("sanity.findings")}</h2><span class="small mut">{len(blocking)}건 중 {len(blocking) - left}건 정함</span>{slack_btn}</div>'
                 + "".join(_finding(f, sid, operator, not live) for f in blocking + other) + '</div>')
    items = (s.get("scope") or {}).get("items") or []
    scope = ""
    if items:
        scope = ('<div class="card flush"><div class="ch"><h2>관련 스펙</h2><span class="small mut">요구 ' + str(sum(len(x["reqs"]) for x in items)) + '개</span></div><table>'
                 + "".join(f'<tr><td style="width:34%"><a style="font-weight:600;color:var(--ink)" href="/features/{e(x["slug"])}#{e(x["scenario"])}">{e(x["feature"])}</a>'
                           f'<div class="small mut">{e(x["scenario"])} {e(x.get("title"))}</div><div class="small mut">{e(x.get("why"))}</div></td>'
                           f'<td><ul class="reqs">{"".join("<li><span class=mono>" + e(r) + "</span><span>" + e((x.get("req_texts") or {}).get(r, "")) + "</span></li>" for r in x["reqs"]) or "<li><span></span><span class=mut>정상 흐름만</span></li>"}</ul></td></tr>'
                           for x in items) + '</table></div>')
    auto = sum(1 for c in cases if c["state"] == "auto")
    make = sum(1 for c in cases if c["state"] == "untested" and c["mode"] != "manual" and c["checks"])
    man = len(cases) - auto - make
    metrics = (f'<div class="card flush" data-tour="cases"><div class="ch"><h2>이번 범위의 케이스</h2><span class="small mut">관련 요구에 걸린 케이스와 그 시나리오의 정상 흐름</span></div>'
               f'<div class="metrics"><div><span>스크립트 있음</span><b>{auto}</b></div><div><span>Hermes 가 만들 스크립트</span><b style="color:var(--info)">{make}</b></div>'
               f'<div><span>사람이 확인 · 근거 없음</span><b style="color:var(--warn)">{man}</b></div></div>'
               f'<table style="border-top:1px solid var(--line)"><tr><th>기능 · 시나리오</th><th>종류</th><th>케이스</th><th>상태</th></tr>'
               + "".join(f'<tr><td class="small mut" style="white-space:nowrap">{e(c["feature"])} {e(c["scenario"])}</td><td style="white-space:nowrap">{e(c["kind_ko"])}</td>'
                         f'<td><a href="{e(c["href"])}" style="color:var(--ink)">{e(c["title"])}</a> <span class="mono">{e(c["key"])}</span></td><td>{c["state_html"]}</td></tr>' for c in cases)
               + '</table></div>') if cases else ""
    log = "".join(f'<div class="logl"><span class="mut">{kst(x["at"])}</span><span>{x["step"]}. {e(S.STEPS[x["step"] - 1])} — {e(x["text"])}</span></div>' for x in reversed(s.get("log") or []))
    older = "".join(f'<div class="logl"><span class="mut">{kst(o["created_at"])}</span><span>{e(o["operator"])} · {e(S.STATUS_KO.get(o["status"], o["status"]))}</span></div>' for o in history[1:6])
    side = (f'<div class="card flush"><div class="ch"><h2>진행 기록</h2></div>{log or "<div class=empty>아직 기록이 없어요</div>"}</div>'
            + (f'<div class="card flush"><div class="ch"><h2>이 PR 의 지난 Sanity</h2></div>{older}</div>' if older else ""))
    cont = (f'<dialog id="dlg-cont"><h3>{"정하지 않은 " + str(left) + "건을 두고 계속할까요?" if left else "3단계부터 이어서 할까요?"}</h3>'
            f'<p class="sd">케이스 준비 → 스크립트 만들기 → 실행을 이어서 해요.{" 정하지 않은 항목에 걸린 요구의 케이스는 스크립트를 만들지 않아요." if left else ""}</p>'
            f'<form method="post" action="/sanity/{e(sid)}/continue"><input type="hidden" name="operator" value="{e(operator)}">'
            f'<div class="field"><label>사유{"<i class=req></i>" if left else ""}</label><input name="reason" style="width:100%" {"required" if left else ""} placeholder="예: 기획 확인 중, 나머지만 먼저 돌린다"></div>'
            f'<div class="mf"><button type="button" data-close-dialog>닫기</button><button class="primary lg">이어서 하기</button></div></form></dialog>')
    return (f'{"<meta http-equiv=refresh content=4>" if live else ""}<div class="card flush">{head}{_steps(s)}{_banner(s, left)}</div>{fhtml}'
            f'<div class="cols" style="grid-template-columns:minmax(0,1.3fr) minmax(0,1fr)"><div>{scope}</div><div>{side}</div></div>{metrics}{cont}')


def sanity_page(prs: list[dict], sel: dict | None, sanity: dict | None, *, operator: str, target: str, hermes: bool, cases: list[dict],
                run: dict | None, history: list[dict], gh_error: str | None = None, flt: str = "all") -> str:
    api = [p for p in prs if p["api"]]
    rest = [p for p in prs if not p["api"]]
    counts = {"all": len(prs), "todo": sum(1 for p in api if not p.get("sanity")), "need": sum(1 for p in prs if (p.get("sanity") or {}).get("status") == "needs_spec"),
              "done": sum(1 for p in prs if (p.get("sanity") or {}).get("status") in ("passed", "failed", "empty"))}
    keep = {"all": lambda p: True, "todo": lambda p: p["api"] and not p.get("sanity"), "need": lambda p: (p.get("sanity") or {}).get("status") == "needs_spec",
            "done": lambda p: (p.get("sanity") or {}).get("status") in ("passed", "failed", "empty")}[flt if flt in ("all", "todo", "need", "done") else "all"]
    seln = sel["number"] if sel else None
    tabs = "".join(f'<a class="{"on" if flt == k else ""}" href="/sanity{"" if k == "all" else "?f=" + k}">{n} {counts[k]}</a>'
                   for k, n in (("all", "전체"), ("todo", "검증 안 함"), ("need", "확인 필요"), ("done", "끝남")))
    lst = ('<div class="sec-h">API 가 바뀐 PR</div>' + ("".join(_pr_row(p, seln) for p in api if keep(p)) or '<div class="empty">없어요</div>')
           + ('<div class="sec-h">API 변경이 없는 PR</div>' + "".join(_pr_row(p, seln) for p in rest if keep(p)) if any(keep(p) for p in rest) else ""))
    if gh_error and not prs:
        lst = f'<div class="empty"><b>PR 목록을 못 읽었어요</b>{e(gh_error)}</div>'
    if sel is None:
        right = '<div class="card"><div class="empty" style="padding:60px"><b>왼쪽에서 PR 을 골라 주세요</b>dev 로 머지된 PR 이 최신순으로 있어요.</div></div>'
    elif sanity is None:
        right = _not_started(sel, operator, target, hermes)
    else:
        right = _detail(sel, sanity, operator=operator, cases=cases, run=run, history=history) + _start_dialog(sel, operator, target)
    return (f'{CSS}<div style="display:flex;align-items:flex-end;gap:16px;margin-bottom:16px"><div style="flex:1"><h1 style="margin:0">Sanity 테스트{h("sanity.page")}</h1>'
            f'<p class="lead" style="margin:4px 0 0">머지된 PR 하나를 골라 스펙대로 동작하는지 확인해요. 시작은 사람이 눌러요.</p></div><div class="tabs" data-tour="tabs">{tabs}</div></div>'
            f'<div class="split"><div class="card flush plist" data-tour="prs">{lst}</div><div>{right}</div></div>{JS}')
