"""서버 렌더 HTML. 프레임워크 없이 f-string + html.escape. 화면 목록은 docs/qa-platform.md §4 5.x."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2330;--mut:#6b7280;--line:#e5e7eb;--ok:#15803d;--okbg:#dcfce7;--bad:#b91c1c;--badbg:#fee2e2;
--warn:#b45309;--warnbg:#fef3c7;--info:#1d4ed8;--infobg:#dbeafe;--gray:#374151;--graybg:#e5e7eb}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;color:var(--ink);background:var(--bg)}
a{color:var(--info);text-decoration:none}a:hover{text-decoration:underline}
nav{background:#111827;color:#fff;padding:0 20px;display:flex;align-items:center;gap:18px;height:48px}
nav a{color:#d1d5db}nav a.on{color:#fff;font-weight:600}nav .brand{font-weight:700;color:#fff;margin-right:8px}nav .op{margin-left:auto;color:#9ca3af}
main{max-width:1180px;margin:0 auto;padding:20px}
h1{font-size:20px;margin:0 0 14px}h2{font-size:15px;margin:22px 0 8px;color:var(--gray)}h3{font-size:14px;margin:14px 0 6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mut);font-weight:600;font-size:12px}
tr:last-child td{border-bottom:0}.mut{color:var(--mut)}.small{font-size:12px}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.b{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;line-height:18px}
.b.pass,.b.finished-pass{color:var(--ok);background:var(--okbg)}.b.fail,.b.error,.b.finished-fail,.b.finished-error{color:var(--bad);background:var(--badbg)}
.b.skipped,.b.canceled,.b.queued,.b.finished-skipped,.b.finished-canceled{color:var(--gray);background:var(--graybg)}.b.running{color:var(--warn);background:var(--warnbg)}
.b.smoke{color:var(--info);background:var(--infobg)}.b.sanity{color:#6d28d9;background:#ede9fe}.b.manual{color:var(--gray);background:var(--graybg)}
.b.warn{color:var(--warn);background:var(--warnbg)}.b.ok{color:var(--ok);background:var(--okbg)}
button,.btn{display:inline-block;border:1px solid #d1d5db;background:#fff;color:var(--ink);border-radius:7px;padding:6px 12px;font:inherit;cursor:pointer}
button.primary,.btn.primary{background:#111827;color:#fff;border-color:#111827}button.danger{color:var(--bad);border-color:#fca5a5}
button:disabled{opacity:.5;cursor:default}form.inline{display:inline}
input,select,textarea{font:inherit;padding:6px 8px;border:1px solid #d1d5db;border-radius:6px;background:#fff}textarea{width:100%;min-height:60px}
pre{background:#0f172a;color:#e2e8f0;padding:10px 12px;border-radius:8px;overflow:auto;font-size:12px;margin:6px 0}
details{margin:6px 0}summary{cursor:pointer}.kv{display:grid;grid-template-columns:120px 1fr;gap:4px 10px}.kv div:nth-child(odd){color:var(--mut)}
.flash{padding:10px 14px;border-radius:8px;margin-bottom:14px}.flash.err{background:var(--badbg);color:var(--bad)}.flash.ok{background:var(--okbg);color:var(--ok)}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.chk{display:block;padding:3px 0}.right{text-align:right}
"""


def e(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def kst(iso: str | None) -> str:
    if not iso:
        return "–"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(KST).strftime("%m-%d %H:%M")
    except ValueError:
        return iso


def badge(v: str | None, extra: str = "") -> str:
    v = v or "–"
    return f'<span class="b {e(v)} {extra}">{e(v)}</span>'


def run_badge(r: dict) -> str:
    if r["status"] == "finished":
        return badge(r.get("verdict"))
    return badge(r["status"])


TRIGGER_KO = {"deploy-sanity": "배포 검증", "sprint-smoke": "스프린트 smoke", "release": "릴리스 QA", "manual": "임의 실행"}
ACTION_KO = {"run.create": "런 생성", "run.cancel": "런 취소", "run.triage": "Hermes 진단", "release.decide": "릴리스 판단",
             "cases.reload": "케이스 재로드", "draft.generate": "초안 생성", "draft.approve": "초안 승인", "draft.reject": "초안 반려",
             "wiki.publish": "위키 발행", "explorer.send": "탐색기 전송"}


def page(title: str, body: str, *, active: str = "", operator: str = "", flash: tuple[str, str] | None = None) -> str:
    nav = "".join(
        f'<a href="{href}" class="{"on" if active == key else ""}">{label}</a>'
        for key, href, label in (("dash", "/", "대시보드"), ("runs", "/runs", "런"), ("cases", "/cases", "케이스"), ("activity", "/activity", "활동"))
    )
    fl = f'<div class="flash {e(flash[0])}">{e(flash[1])}</div>' if flash else ""
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)} · QA</title><style>{CSS}</style></head><body>'
            f'<nav><span class="brand">Plady QA</span>{nav}<span class="op">{("운영자: " + e(operator)) if operator else "운영자 미선택"}</span></nav>'
            f'<main>{fl}{body}</main></body></html>')


# ---- 대시보드 ------------------------------------------------------------------------------
def dashboard(*, deploys: list[dict], sprint: dict, sprint_runs: list[dict], recent: list[dict], cfg_summary: dict,
              case_count: int, case_errors: list[str], gh_error: str | None, runner_current: str | None) -> str:
    rows = ""
    for d in deploys:
        pr = d.get("pr") or {}
        runs = d.get("runs") or []
        if runs:
            last = runs[0]
            state = f'<a href="/runs/{e(last["id"])}">{run_badge(last)}</a> <span class="small mut">{len(runs)}회</span>'
        else:
            state = badge("미검증", "warn")
        btn = (f'<a class="btn" href="/runs/new?trigger=deploy-sanity&sha={e(d["sha"])}&deploy_run_id={e(d["run_id"])}'
               f'{"&pr=" + str(pr["number"]) if pr.get("number") else ""}">검증</a>')
        rows += (f'<tr><td class="mono"><a href="{e(d["url"])}">{e((d["sha"] or "")[:8])}</a></td>'
                 f'<td>{("<a href=\"" + e(pr["url"]) + "\">#" + str(pr["number"]) + "</a> ") if pr.get("number") else ""}{e(pr.get("title") or d.get("title"))}</td>'
                 f'<td class="small mut">{kst(d["at"])}</td><td>{state}</td><td class="right">{btn}</td></tr>')
    if not rows:
        rows = f'<tr><td colspan="5" class="mut">{"조회 실패: " + e(gh_error) if gh_error else "성공한 dev 배포가 없다"}</td></tr>'
    unverified = sum(1 for d in deploys if not d.get("runs"))

    s_state = ("이번 스프린트 smoke: " + " ".join(f'<a href="/runs/{e(r["id"])}">{run_badge(r)}</a>' for r in sprint_runs[:3])) if sprint_runs \
        else badge("이번 스프린트 smoke 미실행", "warn")
    sprint_card = (f'<div class="card"><h3 style="margin-top:0">스프린트 Cycle {sprint["number"]} '
                   f'<span class="small mut">{sprint["starts_at"].astimezone(KST).strftime("%m-%d")} ~ {(sprint["ends_at"] - timedelta(days=1)).astimezone(KST).strftime("%m-%d")}</span></h3>'
                   f'<p>{s_state}</p><div class="actions"><a class="btn primary" href="/runs/new?trigger=sprint-smoke">스프린트 smoke 실행</a>'
                   f'<a class="btn" href="/runs/new?trigger=release">릴리스 검증</a><a class="btn" href="/runs/new?trigger=manual">임의 실행</a></div></div>')

    cfg_lines = (f'대상 <span class="mono">{e(cfg_summary["target"])}</span> · 케이스 {case_count}개 · 배우 {", ".join(cfg_summary["actors"]) or "<b style=\"color:var(--warn)\">없음</b>"}'
                 f' · Hermes {"on" if cfg_summary["hermes"] else "off"} · Slack {"on" if cfg_summary["slack"] else "off"}'
                 f' · 러너 {("실행 중 " + e(runner_current)) if runner_current else "대기"}')
    errs = "".join(f'<li class="small" style="color:var(--bad)">{e(x)}</li>' for x in case_errors)
    status_card = f'<div class="card"><h3 style="margin-top:0">상태</h3><p class="small">{cfg_lines}</p>{("<ul>" + errs + "</ul>") if errs else ""}</div>'

    rec = "".join(
        f'<tr><td><a href="/runs/{e(r["id"])}" class="mono">{e(r["id"])}</a></td><td>{e(TRIGGER_KO.get(r["trigger"], r["trigger"]))}</td>'
        f'<td>{e(r["operator"])}</td><td class="mono small">{e((r.get("sha") or "")[:8])}{(" #" + str(r["pr_number"])) if r.get("pr_number") else ""}</td>'
        f'<td>{run_badge(r)} <span class="small mut">{r["passed"]}/{r["total"]}</span></td><td class="small mut">{kst(r["created_at"])}</td></tr>'
        for r in recent) or '<tr><td colspan="6" class="mut">아직 런이 없다</td></tr>'

    return (f'<h1>대시보드</h1><div class="grid">{sprint_card}{status_card}</div>'
            f'<h2>dev 배포 {badge(f"미검증 {unverified}", "warn" if unverified else "ok")}</h2><div class="card">'
            f'<table><tr><th>SHA</th><th>PR</th><th>배포</th><th>검증</th><th></th></tr>{rows}</table>'
            f'<p class="small mut">GitHub Actions 의 성공한 dev 배포를 읽어 표시한다. 검증은 사람이 [검증] 을 눌러야 시작된다.</p></div>'
            f'<h2>최근 런</h2><div class="card"><table><tr><th>ID</th><th>트리거</th><th>운영자</th><th>대상</th><th>판정</th><th>시각</th></tr>{rec}</table></div>')


# ---- 런 생성(확인 화면) ------------------------------------------------------------------------
def run_new(*, trigger: str, target: dict, suggested: list, all_cases: list, basis: str, operators: list[str],
            operator: str, hidden: dict, warnings: list[str]) -> str:
    sug_ids = {c.id for c in suggested}
    groups: dict[str, list] = {}
    for c in all_cases:
        groups.setdefault(c.suite, []).append(c)
    lists = ""
    for suite in ("sanity", "smoke", "manual"):
        cs = groups.get(suite) or []
        if not cs:
            continue
        items = "".join(
            f'<label class="chk"><input type="checkbox" name="case_ids" value="{e(c.id)}" {"checked" if c.id in sug_ids else ""}> '
            f'<span class="mono">{e(c.id)}</span> {e(c.title)}{(" <span class=\"small mut\">배우 " + e(c.actor) + "</span>") if c.actor else ""}</label>'
            for c in cs)
        lists += f'<h3>{badge(suite)} {len(cs)}개</h3>{items}'
    ops = "".join(f'<option value="{e(o)}" {"selected" if o == operator else ""}>{e(o)}</option>' for o in operators)
    hid = "".join(f'<input type="hidden" name="{e(k)}" value="{e(v)}">' for k, v in hidden.items() if v not in (None, ""))
    warn = "".join(f'<div class="flash err">{e(w)}</div>' for w in warnings)
    tgt = "".join(f'<div>{e(k)}</div><div>{v}</div>' for k, v in target.items())
    return (f'<h1>{e(TRIGGER_KO.get(trigger, trigger))} — 실행 전 확인</h1>{warn}'
            f'<form method="post" action="/runs">{hid}<input type="hidden" name="trigger" value="{e(trigger)}">'
            f'<div class="grid"><div class="card"><h3 style="margin-top:0">대상</h3><div class="kv">{tgt}</div>'
            f'<p class="small mut" style="margin-bottom:0">선택 근거: {e(basis)}</p></div>'
            f'<div class="card"><h3 style="margin-top:0">운영자</h3><p><select name="operator" required><option value="">— 선택 —</option>{ops}</select>'
            f' <span class="small mut">자기 신고. 세션은 팀 공용이라 인증 신원이 아니다 (설계 §6.2)</span></p>'
            f'<p><input name="reason" placeholder="사유 (선택)" style="width:100%"></p></div></div>'
            f'<div class="card"><h3 style="margin-top:0">범위 — {len(suggested)}개 선택됨</h3>{lists}</div>'
            f'<div class="actions"><button class="primary" type="submit">실행</button><a class="btn" href="/">취소</a></div></form>')


# ---- 런 목록·상세 ------------------------------------------------------------------------------
def runs_list(runs: list[dict]) -> str:
    rows = "".join(
        f'<tr><td><a href="/runs/{e(r["id"])}" class="mono">{e(r["id"])}</a></td><td>{e(TRIGGER_KO.get(r["trigger"], r["trigger"]))}</td>'
        f'<td>{e(r["operator"])}</td><td class="mono small">{e((r.get("sha") or "")[:8])}{(" #" + str(r["pr_number"])) if r.get("pr_number") else ""}</td>'
        f'<td>{run_badge(r)}</td><td class="small">{r["passed"]} / {r["failed"]} / {r["errored"]} / {r["skipped"]}</td>'
        f'<td class="small mut">{kst(r["created_at"])}</td></tr>' for r in runs) or '<tr><td colspan="7" class="mut">런이 없다</td></tr>'
    return f'<h1>런</h1><div class="card"><table><tr><th>ID</th><th>트리거</th><th>운영자</th><th>대상</th><th>판정</th><th>통과/실패/오류/skip</th><th>시각</th></tr>{rows}</table></div>'


def _checks_html(checks: list[dict]) -> str:
    if not checks:
        return ""
    return "".join(
        f'<div class="small">{"✅" if c["ok"] else "❌"} {e(c["check"])}{(" <span class=\"mono\">" + e(c["path"]) + "</span>") if c.get("path") else ""}'
        f' 기대 <span class="mono">{e(json.dumps(c["expected"], ensure_ascii=False))}</span> 실제 <span class="mono">{e(json.dumps(c["actual"], ensure_ascii=False))}</span></div>'
        for c in checks)


def run_detail(run: dict, cases: list[dict], steps_by_case: dict[int, list[dict]], *, operators: list[str], operator: str,
               checklist: list[str], public_url: str) -> str:
    live = run["status"] in ("queued", "running")
    refresh = '<meta http-equiv="refresh" content="4">' if live else ""
    meta = run.get("meta") or {}
    kv = {
        "트리거": e(TRIGGER_KO.get(run["trigger"], run["trigger"])), "운영자": e(run["operator"]),
        "대상": f'<span class="mono">{e(run["base_url"])}</span>',
        "SHA / PR": f'<span class="mono">{e(run.get("sha") or "–")}</span>' + (f' · <a href="{e(meta.get("pr_url"))}">#{run["pr_number"]}</a> {e(meta.get("pr_title") or "")}' if run.get("pr_number") else ""),
        "선택 근거": e(meta.get("basis") or "–"), "사유": e(meta.get("reason") or "–"),
        "시각": f'{kst(run["created_at"])} 생성 · {kst(run.get("started_at"))} 시작 · {kst(run.get("finished_at"))} 종료',
        "결과": f'{run_badge(run)} 통과 {run["passed"]} · 실패 {run["failed"]} · 오류 {run["errored"]} · skip {run["skipped"]} / {run["total"]}',
    }
    kvh = "".join(f'<div>{k}</div><div>{v}</div>' for k, v in kv.items())
    cancel = (f'<form class="inline" method="post" action="/runs/{e(run["id"])}/cancel"><input type="hidden" name="operator" value="{e(operator)}">'
              f'<button class="danger" {"" if operator else "disabled title=\"운영자를 먼저 고르세요\""}>취소</button></form>') if live else ""

    body_cases = ""
    for rc in cases:
        steps = steps_by_case.get(rc["id"], [])
        st = ""
        for s in steps:
            req, resp = s["request"], s.get("response") or {}
            rbody = resp.get("json") if resp.get("json") is not None else resp.get("text")
            st += (f'<details {"open" if s["verdict"] not in ("pass",) else ""}><summary>{badge(s["verdict"])} {s["ord"] + 1}. {e(s["name"])} '
                   f'<span class="mono small">{e(req.get("method"))} {e(req.get("path"))}</span>'
                   f'{(" <span class=\"small mut\">배우 " + e(req.get("actor")) + "</span>") if req.get("actor") else ""}'
                   f' <span class="small mut">{s.get("duration_ms") or 0} ms</span></summary>'
                   f'{("<div class=\"small\" style=\"color:var(--bad)\">" + e(s.get("error")) + "</div>") if s.get("error") else ""}'
                   f'{_checks_html(s["checks"])}'
                   f'<details><summary class="small mut">요청</summary><pre>{e(json.dumps({k: v for k, v in req.items() if k in ("url", "body", "query", "headers")}, ensure_ascii=False, indent=1))}</pre></details>'
                   f'<details><summary class="small mut">응답 {e(resp.get("status"))}</summary><pre>{e(json.dumps(rbody, ensure_ascii=False, indent=1) if not isinstance(rbody, str) else rbody)}</pre></details></details>')
        tri = ""
        if rc["verdict"] in ("fail", "error"):
            tri = (f'<form class="inline" method="post" action="/runs/{e(run["id"])}/triage"><input type="hidden" name="run_case_id" value="{rc["id"]}">'
                   f'<input type="hidden" name="operator" value="{e(operator)}"><button {"" if operator else "disabled title=\"운영자를 먼저 고르세요\""}>Hermes 진단</button></form>')
            if rc.get("triage"):
                tri += f'<div class="card" style="margin-top:8px;background:#f8fafc"><div class="small mut">Hermes 진단 · {kst(rc.get("triaged_at"))}</div><pre style="background:#fff;color:var(--ink);border:1px solid var(--line)">{e(rc["triage"])}</pre></div>'
        body_cases += (f'<div class="card"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">{badge(rc["verdict"])} {badge(rc["case_suite"])} '
                       f'<a href="/cases/{e(rc["case_id"])}" class="mono">{e(rc["case_id"])}</a> <b>{e(rc["case_title"])}</b>'
                       f'<span class="small mut">{rc.get("duration_ms") or 0} ms · 스냅샷 {e(rc["case_hash"])}</span><span style="margin-left:auto">{tri}</span></div>'
                       f'{("<div class=\"small\" style=\"color:var(--bad);margin-top:4px\">" + e(rc.get("error")) + "</div>") if rc.get("error") and rc["verdict"] == "skipped" else ""}{st}</div>')

    release = ""
    if run["trigger"] == "release":
        dec = meta.get("release")
        if dec:
            done = "".join(f'<li>{"☑" if i in dec.get("checked", []) else "☐"} {e(i)}</li>' for i in dec.get("items", []))
            release = (f'<h2>릴리스 판단</h2><div class="card">{badge("GO" if dec["decision"] == "go" else "NO-GO", "ok" if dec["decision"] == "go" else "warn")} '
                       f'{e(dec["operator"])} · {kst(dec["at"])}<p>{e(dec.get("reason") or "")}</p><ul>{done}</ul></div>')
        else:
            items = "".join(f'<label class="chk"><input type="checkbox" name="checked" value="{e(i)}"> {e(i)}</label>' for i in checklist) or '<p class="mut">체크리스트를 가져오지 못했다 (backend docs/knowledge/release-checklist.md)</p>'
            ops = "".join(f'<option value="{e(o)}" {"selected" if o == operator else ""}>{e(o)}</option>' for o in operators)
            release = (f'<h2>릴리스 판단</h2><div class="card"><form method="post" action="/runs/{e(run["id"])}/decide">'
                       f'<p class="small mut">항목은 백엔드 <span class="mono">docs/knowledge/release-checklist.md</span> 에서 읽어 온다. 판단은 기록만 하고 승격을 막지 않는다 (설계 §13-5).</p>'
                       f'{items}<p><select name="decision"><option value="go">GO — 승격해도 된다</option><option value="no-go">NO-GO — 보류</option></select> '
                       f'<select name="operator" required><option value="">— 운영자 —</option>{ops}</select></p><p><textarea name="reason" placeholder="판단 사유"></textarea></p>'
                       f'<button class="primary" {"disabled" if live else ""}>판단 기록</button></form></div>')

    return (f'{refresh}<h1>런 <span class="mono">{e(run["id"])}</span> {run_badge(run)}</h1>'
            f'<div class="card"><div class="kv">{kvh}</div><div class="actions">{cancel}<a class="btn" href="/api/runs/{e(run["id"])}">JSON</a></div></div>'
            f'{release}<h2>케이스</h2>{body_cases}')


# ---- 케이스 --------------------------------------------------------------------------------------
def cases_list(cases: list, last: dict[str, dict], errors: list[str]) -> str:
    rows = "".join(
        f'<tr><td><a href="/cases/{e(c.id)}" class="mono">{e(c.id)}</a></td><td>{e(c.title)}</td><td>{badge(c.suite)}</td>'
        f'<td class="small">{e(", ".join(c.domains))}</td><td class="small">{e(c.actor or "–")}</td><td class="small mono">{e(c.file)}</td>'
        f'<td>{(("<a href=\"/runs/" + e(last[c.id]["run_id"]) + "\">" + badge(last[c.id]["verdict"]) + "</a> <span class=\"small mut\">" + kst(last[c.id]["created_at"]) + "</span>") if c.id in last else "<span class=\"mut small\">–</span>")}</td></tr>'
        for c in cases)
    errs = "".join(f'<li style="color:var(--bad)">{e(x)}</li>' for x in errors)
    return (f'<h1>케이스 <span class="small mut">{len(cases)}개 · 정본은 git <span class="mono">qa-platform/cases/</span></span></h1>'
            f'{("<div class=\"flash err\"><b>로드 오류</b><ul>" + errs + "</ul></div>") if errs else ""}'
            f'<div class="card"><table><tr><th>ID</th><th>제목</th><th>스위트</th><th>도메인</th><th>배우</th><th>파일</th><th>마지막 판정</th></tr>{rows}</table>'
            f'<form method="post" action="/cases/reload" class="actions"><button>파일에서 다시 읽기</button></form></div>')


def case_detail(c, history: list[dict]) -> str:
    hist = "".join(
        f'<tr><td><a href="/runs/{e(h["run_id"])}" class="mono">{e(h["run_id"])}</a></td><td>{badge(h["verdict"])}</td><td>{e(TRIGGER_KO.get(h["trigger"], h["trigger"]))}</td>'
        f'<td>{e(h["operator"])}</td><td class="mono small">{e((h.get("sha") or "")[:8])}</td><td class="small mut">{kst(h["created_at"])}</td>'
        f'<td class="small" style="color:var(--bad)">{e(h.get("error") or "")}</td></tr>' for h in history) or '<tr><td colspan="7" class="mut">실행 이력 없음</td></tr>'
    src = "".join(f'<li>{e(s)}</li>' for s in c.source) or '<li class="mut">근거 미기재</li>'
    return (f'<h1><span class="mono">{e(c.id)}</span> {badge(c.suite)}</h1><div class="card"><b>{e(c.title)}</b>'
            f'{("<p>" + e(c.description) + "</p>") if c.description else ""}'
            f'<div class="kv"><div>도메인</div><div>{e(", ".join(c.domains) or "–")}</div><div>operation</div><div class="mono">{e(", ".join(c.operations) or "–")}</div>'
            f'<div>배우</div><div>{e(c.actor or "비로그인")}</div><div>근거</div><div><ul style="margin:0;padding-left:18px">{src}</ul></div><div>파일</div><div class="mono">{e(c.file)} · {e(c.hash)}</div></div></div>'
            f'<h2>정의</h2><pre>{e(c.to_yaml())}</pre>'
            f'<h2>실행 이력</h2><div class="card"><table><tr><th>런</th><th>판정</th><th>트리거</th><th>운영자</th><th>SHA</th><th>시각</th><th>오류</th></tr>{hist}</table></div>')


# ---- 활동(감사 로그) ----------------------------------------------------------------------------
def activity(events: list[dict], operators: list[str], actions: list[str], f_op: str, f_act: str) -> str:
    rows = "".join(
        f'<tr><td class="small mut">{kst(ev["at"])}</td><td>{e(ev["operator"])}</td><td>{e(ACTION_KO.get(ev["action"], ev["action"]))}</td>'
        f'<td>{("<a href=\"/runs/" + e(ev["target"]) + "\" class=\"mono\">" + e(ev["target"]) + "</a>") if (ev.get("target") or "").startswith("r-") else e(ev.get("target") or "")}</td>'
        f'<td class="small mono">{e(json.dumps(ev["detail"], ensure_ascii=False)[:300])}</td><td class="small mut mono">{e(ev.get("session_hash") or "")} {e(ev.get("ip") or "")}</td></tr>'
        for ev in events) or '<tr><td colspan="6" class="mut">기록 없음</td></tr>'
    ops = "".join(f'<option value="{e(o)}" {"selected" if o == f_op else ""}>{e(o)}</option>' for o in operators)
    acts = "".join(f'<option value="{e(a)}" {"selected" if a == f_act else ""}>{e(ACTION_KO.get(a, a))}</option>' for a in actions)
    return (f'<h1>활동</h1><form class="card" method="get"><select name="operator"><option value="">운영자 전체</option>{ops}</select> '
            f'<select name="action"><option value="">행위 전체</option>{acts}</select> <button>필터</button>'
            f' <span class="small mut">모든 사람 행위의 감사 로그. 운영자는 자기 신고, 세션 해시·IP 는 대조용.</span></form>'
            f'<div class="card"><table><tr><th>시각</th><th>운영자</th><th>행위</th><th>대상</th><th>상세</th><th>세션/IP</th></tr>{rows}</table></div>')
