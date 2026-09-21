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
.b.policy{color:#0f766e;background:#ccfbf1}.b.contract{color:#9a3412;background:#ffedd5}.b.manual{color:var(--gray);background:var(--graybg)}
.b.covered{color:var(--ok);background:var(--okbg)}.b.uncovered{color:var(--bad);background:var(--badbg)}.b.excluded{color:var(--mut);background:var(--graybg)}
.b.drift{color:var(--warn);background:var(--warnbg)}.b.unchecked{color:var(--mut);background:var(--graybg)}
tr.ex td{color:var(--mut)}.tabs a{display:inline-block;padding:4px 10px;border-radius:6px;margin:0 4px 6px 0;border:1px solid var(--line);background:#fff}.tabs a.on{background:#111827;color:#fff;border-color:#111827}
.mx{font-size:12px}.mx td,.mx th{padding:4px 6px;text-align:center}.mx td:first-child{text-align:left}
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


TRIGGER_KO = {"deploy-sanity": "배포 검증", "sprint-smoke": "스프린트 smoke", "release": "릴리스 QA", "manual": "임의 실행",
              "draft-check": "초안 확인", "explorer": "탐색기"}
ACTION_KO = {"run.create": "런 생성", "run.cancel": "런 취소", "run.triage": "Hermes 진단", "release.decide": "릴리스 판단",
             "cases.reload": "케이스 재로드", "draft.generate": "케이스 초안 생성", "draft.rejected_by_validation": "케이스 초안 검증 탈락",
             "draft.save": "케이스 초안 편집", "draft.check": "케이스 초안 확인 실행", "draft.approve": "케이스 초안 승인", "draft.reject": "케이스 초안 반려",
             "run.publish": "위키 발행", "explorer.send": "탐색기 전송", "sprint.remind": "스프린트 smoke 리마인드(Slack)"}
DRAFT_KO = {"draft": "검토 대기", "checked": "dev 확인됨", "approved": "승인", "rejected": "반려"}


def page(title: str, body: str, *, active: str = "", operator: str = "", flash: tuple[str, str] | None = None) -> str:
    nav = "".join(
        f'<a href="{href}" class="{"on" if active == key else ""}">{label}</a>'
        for key, href, label in (("dash", "/", "대시보드"), ("runs", "/runs", "런"), ("cases", "/cases", "케이스"), ("catalog", "/catalog", "기준"), ("drafts", "/drafts", "케이스 초안"), ("explorer", "/explorer", "탐색기"), ("activity", "/activity", "활동"), ("guide", "/guide", "가이드"))
    )
    fl = f'<div class="flash {e(flash[0])}">{e(flash[1])}</div>' if flash else ""
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)} · QA</title><style>{CSS}</style></head><body>'
            f'<nav><span class="brand">Plady QA</span>{nav}<span class="op">{("운영자: " + e(operator)) if operator else "운영자 미선택"}</span></nav>'
            f'<main>{fl}{body}</main></body></html>')


# ---- 대시보드 ------------------------------------------------------------------------------
def tc_link(tid: str, label: str | None = None) -> str:
    from urllib.parse import quote
    return f'<a href="/catalog/tc?id={quote(tid, safe="")}" class="mono">{e(label or tid)}</a>'


def coverage_card(catalog, coverage: dict | None, error: str | None) -> str:
    if catalog is None or coverage is None:
        return f'<div class="card"><h3 style="margin-top:0">기준 커버리지</h3><p class="mut small">카탈로그 없음{(": " + e(error)) if error else ""}</p></div>'
    layers = [l for l in ("policy", "contract", "manual") if any(l in v for v in coverage["matrix"].values())]
    head = "".join(f"<th>{l}</th>" for l in layers)
    rows = ""
    tot = {"covered": 0, "total": 0, "excluded": 0}
    for d in catalog.domains():
        cells = ""
        for l in layers:
            c = coverage["matrix"].get(d, {}).get(l)
            if not c:
                cells += "<td class='mut'>–</td>"
                continue
            denom = c["total"] - c["excluded"]
            cells += (f'<td><a href="/catalog?domain={e(d)}&layer={l}">{c["covered"]}/{denom}</a>'
                      f'{(" <span class=\"mut\">(제외 " + str(c["excluded"]) + ")</span>") if c["excluded"] else ""}</td>')
            for k in tot:
                tot[k] += c[k]
        rows += f'<tr><td><a href="/catalog?domain={e(d)}">{e(d)}</a></td>{cells}</tr>'
    v = catalog.versions
    return (f'<div class="card"><h3 style="margin-top:0">기준 커버리지 <span class="small mut">덮음 {tot["covered"]} / {tot["total"] - tot["excluded"]} (제외 {tot["excluded"]})</span></h3>'
            f'<table class="mx"><tr><th>도메인</th>{head}</tr>{rows}</table>'
            f'<p class="small mut" style="margin-bottom:0">SSOT <span class="mono">{e(v.get("ssot") or "–")}</span> · OpenAPI <span class="mono">{e(v.get("openapi") or "–")}</span> · {kst(catalog.built_at)} 계산'
            f'{(" · <b style=\"color:var(--warn)\">경고 " + str(len(catalog.warnings)) + "</b>") if catalog.warnings else ""}</p></div>')


def dashboard(*, deploys: list[dict], sprint: dict, sprint_runs: list[dict], recent: list[dict], cfg_summary: dict,
              case_count: int, case_errors: list[str], gh_error: str | None, runner_current: str | None,
              catalog=None, coverage: dict | None = None, catalog_error: str | None = None) -> str:
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

    cfg_lines = (f'대상 <span class="mono">{e(cfg_summary["target"])}</span> · 케이스 {case_count}개 · 테스트 계정 {", ".join(cfg_summary["actors"]) or "<b style=\"color:var(--warn)\">없음</b>"}'
                 f' · Hermes {"on" if cfg_summary["hermes"] else "off"} · Slack {"on" if cfg_summary["slack"] else "off"}'
                 f' · 러너 {("실행 중 " + e(runner_current)) if runner_current else "대기"}')
    errs = "".join(f'<li class="small" style="color:var(--bad)">{e(x)}</li>' for x in case_errors)
    status_card = f'<div class="card"><h3 style="margin-top:0">상태</h3><p class="small">{cfg_lines}</p>{("<ul>" + errs + "</ul>") if errs else ""}</div>'

    rec = "".join(
        f'<tr><td><a href="/runs/{e(r["id"])}" class="mono">{e(r["id"])}</a></td><td>{e(TRIGGER_KO.get(r["trigger"], r["trigger"]))}</td>'
        f'<td>{e(r["operator"])}</td><td class="mono small">{e((r.get("sha") or "")[:8])}{(" #" + str(r["pr_number"])) if r.get("pr_number") else ""}</td>'
        f'<td>{run_badge(r)} <span class="small mut">{r["passed"]}/{r["total"]}</span></td><td class="small mut">{kst(r["created_at"])}</td></tr>'
        for r in recent) or '<tr><td colspan="6" class="mut">아직 런이 없다</td></tr>'

    return (f'<h1>대시보드</h1><div class="grid">{sprint_card}{status_card}</div>{coverage_card(catalog, coverage, catalog_error)}'
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
            f'<span class="mono">{e(c.id)}</span> {e(c.title)}{(" <span class=\"small mut\">테스트 계정 " + e(c.actor) + "</span>") if c.actor else ""}</label>'
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
def runs_list(runs: list[dict], show_all: bool = False) -> str:
    rows = "".join(
        f'<tr><td><a href="/runs/{e(r["id"])}" class="mono">{e(r["id"])}</a></td><td>{e(TRIGGER_KO.get(r["trigger"], r["trigger"]))}</td>'
        f'<td>{e(r["operator"])}</td><td class="mono small">{e((r.get("sha") or "")[:8])}{(" #" + str(r["pr_number"])) if r.get("pr_number") else ""}</td>'
        f'<td>{run_badge(r)}</td><td class="small">{r["passed"]} / {r["failed"]} / {r["errored"]} / {r["skipped"]}</td>'
        f'<td class="small mut">{kst(r["created_at"])}</td></tr>' for r in runs) or '<tr><td colspan="7" class="mut">런이 없다</td></tr>'
    toggle = '<a href="/runs">탐색기 전송 숨기기</a>' if show_all else '<a href="/runs?all=1">탐색기 전송도 보기</a>'
    return f'<h1>런 <span class="small mut">{toggle}</span></h1><div class="card"><table><tr><th>ID</th><th>트리거</th><th>운영자</th><th>대상</th><th>판정</th><th>통과/실패/오류/skip</th><th>시각</th></tr>{rows}</table></div>'


def _checks_html(checks: list[dict]) -> str:
    if not checks:
        return ""
    return "".join(
        f'<div class="small">{"✅" if c["ok"] else "❌"} {e(c["check"])}{(" <span class=\"mono\">" + e(c["path"]) + "</span>") if c.get("path") else ""}'
        f' 기대 <span class="mono">{e(json.dumps(c["expected"], ensure_ascii=False))}</span> 실제 <span class="mono">{e(json.dumps(c["actual"], ensure_ascii=False))}</span></div>'
        for c in checks)


def run_detail(run: dict, cases: list[dict], steps_by_case: dict[int, list[dict]], *, operators: list[str], operator: str,
               checklist: list[str], public_url: str, can_publish: bool = False) -> str:
    live = run["status"] in ("queued", "running")
    refresh = '<meta http-equiv="refresh" content="4">' if live else ""
    meta = run.get("meta") or {}
    kv = {
        "트리거": e(TRIGGER_KO.get(run["trigger"], run["trigger"])), "운영자": e(run["operator"]),
        "대상": f'<span class="mono">{e(run["base_url"])}</span>',
        "SHA / PR": f'<span class="mono">{e(run.get("sha") or "–")}</span>' + (f' · <a href="{e(meta.get("pr_url"))}">#{run["pr_number"]}</a> {e(meta.get("pr_title") or "")}' if run.get("pr_number") else ""),
        "선택 근거": e(meta.get("basis") or "–"), "사유": e(meta.get("reason") or "–"),
        "기준 버전": (f'SSOT <span class="mono">{e((meta.get("catalog") or {}).get("ssot") or "–")}</span> · OpenAPI <span class="mono">{e((meta.get("catalog") or {}).get("openapi") or "–")}</span>'
                   f' · 덮는 TC {len(meta.get("covers") or [])}') if meta.get("catalog") else "–",
        "시각": f'{kst(run["created_at"])} 생성 · {kst(run.get("started_at"))} 시작 · {kst(run.get("finished_at"))} 종료',
        "결과": f'{run_badge(run)} 통과 {run["passed"]} · 실패 {run["failed"]} · 오류 {run["errored"]} · skip {run["skipped"]} / {run["total"]}',
    }
    kvh = "".join(f'<div>{k}</div><div>{v}</div>' for k, v in kv.items())
    cancel = (f'<form class="inline" method="post" action="/runs/{e(run["id"])}/cancel"><input type="hidden" name="operator" value="{e(operator)}">'
              f'<button class="danger" {"" if operator else "disabled title=\"운영자를 먼저 고르세요\""}>취소</button></form>') if live else ""
    publish = ""
    if not live and run["trigger"] in ("sprint-smoke", "release", "deploy-sanity"):
        pub = meta.get("published")
        if pub:
            publish = f'<span class="small">위키에 발행됨 · <a href="{e(pub.get("url"))}" class="mono">{e(pub.get("slug"))}</a> · {e(pub.get("by"))} {kst(pub.get("at"))}</span> '
        dis = "" if (operator and can_publish) else ("disabled title=\"운영자를 먼저 고르세요\"" if can_publish else "disabled title=\"LLM_WIKI_MCP_* 미설정\"")
        publish += (f'<form class="inline" method="post" action="/runs/{e(run["id"])}/publish"><input type="hidden" name="operator" value="{e(operator)}">'
                    f'<button {dis}>{"다시 " if pub else ""}위키에 발행</button> <button name="dry" value="1" {dis}>dry-run</button></form>'
                    f'<span class="small mut">wiki/qa/ 에 generated 페이지로. 사람이 누를 때만 · UUID 마스킹</span>')

    body_cases = ""
    for rc in cases:
        steps = steps_by_case.get(rc["id"], [])
        st = ""
        for s in steps:
            req, resp = s["request"], s.get("response") or {}
            rbody = resp.get("json") if resp.get("json") is not None else resp.get("text")
            st += (f'<details {"open" if s["verdict"] not in ("pass",) else ""}><summary>{badge(s["verdict"])} {s["ord"] + 1}. {e(s["name"])} '
                   f'<span class="mono small">{e(req.get("method"))} {e(req.get("path"))}</span>'
                   f'{(" <span class=\"small mut\">테스트 계정 " + e(req.get("actor")) + "</span>") if req.get("actor") else ""}'
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
            f'<div class="card"><div class="kv">{kvh}</div><div class="actions">{cancel}{publish}<a class="btn" href="/api/runs/{e(run["id"])}">JSON</a></div></div>'
            f'{release}<h2>케이스</h2>{body_cases}')


# ---- 케이스 --------------------------------------------------------------------------------------
def audit_badge(c, drift: list | None = None) -> str:
    st = c.audit.get("status", "unchecked")
    label = {"ok": "대조 OK", "warn": "경고", "error": "대조 오류", "unchecked": "미대조"}[st]
    n = len(c.audit.get("errors") or []) + len(c.audit.get("warnings") or [])
    out = f'<span class="b {"pass" if st == "ok" else ("warn" if st == "warn" else ("fail" if st == "error" else "unchecked"))}" title="{e("; ".join((c.audit.get("errors") or []) + (c.audit.get("warnings") or [])))}">{label}{(" " + str(n)) if n and st != "ok" else ""}</span>'
    if drift:
        out += f' <span class="b drift" title="{e("; ".join(d["id"] + " " + d["kind"] + " " + d["at"] for d in drift))}">근거 변경 {len(drift)}</span>'
    return out


def cases_list(cases: list, last: dict[str, dict], errors: list[str], drift: dict | None = None) -> str:
    drift = drift or {}
    rows = "".join(
        f'<tr><td><a href="/cases/{e(c.id)}" class="mono">{e(c.id)}</a></td><td>{e(c.title)}</td><td>{badge(c.suite)}</td>'
        f'<td class="small">{e(", ".join(c.domains))}</td><td class="small">{e(c.actor or "–")}</td>'
        f'<td class="small">{len(c.covers)} {audit_badge(c, drift.get(c.id))}</td>'
        f'<td>{(("<a href=\"/runs/" + e(last[c.id]["run_id"]) + "\">" + badge(last[c.id]["verdict"]) + "</a> <span class=\"small mut\">" + kst(last[c.id]["created_at"]) + "</span>") if c.id in last else "<span class=\"mut small\">–</span>")}</td></tr>'
        for c in cases)
    errs = "".join(f'<li style="color:var(--bad)">{e(x)}</li>' for x in errors)
    blocked = [c.id for c in cases if c.blocked]
    return (f'<h1>케이스 <span class="small mut">{len(cases)}개 · 정본은 git <span class="mono">qa-platform/cases/</span></span></h1>'
            f'{("<div class=\"flash err\"><b>로드 오류</b><ul>" + errs + "</ul></div>") if errs else ""}'
            f'{("<div class=\"flash err\"><b>카탈로그 대조 오류</b> — covers 선언이 카탈로그와 맞지 않아 스위트에서 빠진 케이스: " + e(", ".join(blocked)) + "</div>") if blocked else ""}'
            f'<div class="card"><table><tr><th>ID</th><th>제목</th><th>스위트</th><th>도메인</th><th>테스트 계정</th><th>덮는 TC · 대조</th><th>마지막 판정</th></tr>{rows}</table>'
            f'<p class="small mut">대조 = covers 의 TC 가 카탈로그에 있고 단계의 method·path·기대 코드가 계약과 맞는지. 근거 변경 = 덮는 TC 가 마지막 검토(reviewed) 이후 바뀜.</p>'
            f'<form method="post" action="/cases/reload" class="actions"><button>파일에서 다시 읽기</button></form></div>')


def case_detail(c, history: list[dict], tc_records: dict | None = None, drift: list | None = None) -> str:
    tc_records = tc_records or {}
    changed = {d["id"]: d for d in (drift or [])}
    covers_html = "".join(
        f'<li>{tc_link(t)} {badge(r["layer"]) if r else "<span class=\"b fail\">카탈로그에 없음</span>"} {e(r["title"]) if r else ""}'
        f'{(" <span class=\"b drift\">" + e(changed[t]["kind"]) + " " + kst(changed[t]["at"]) + "</span>") if t in changed else ""}</li>'
        for t, r in ((t, tc_records.get(t)) for t in c.covers)) or '<li class="mut">덮는 TC 없음 (manual 스위트만 허용)</li>'
    problems = "".join(f'<li style="color:var(--bad)">{e(x)}</li>' for x in c.audit.get("errors") or []) + \
        "".join(f'<li style="color:var(--warn)">{e(x)}</li>' for x in c.audit.get("warnings") or [])
    audit_html = (f'<div class="kv"><div>대조</div><div>{audit_badge(c, drift)}{("<ul style=\"margin:4px 0 0;padding-left:18px\">" + problems + "</ul>") if problems else ""}</div>'
                  f'<div>검토</div><div>{(e(c.reviewed.get("by") or "–") + " · " + e(c.reviewed.get("at"))) if c.reviewed else "<span class=\"mut\">기록 없음 — 케이스에 reviewed: {at, by} 를 적으면 그 이후 변경만 배지로 뜬다</span>"}</div></div>')
    hist = "".join(
        f'<tr><td><a href="/runs/{e(h["run_id"])}" class="mono">{e(h["run_id"])}</a></td><td>{badge(h["verdict"])}</td><td>{e(TRIGGER_KO.get(h["trigger"], h["trigger"]))}</td>'
        f'<td>{e(h["operator"])}</td><td class="mono small">{e((h.get("sha") or "")[:8])}</td><td class="small mut">{kst(h["created_at"])}</td>'
        f'<td class="small" style="color:var(--bad)">{e(h.get("error") or "")}</td></tr>' for h in history) or '<tr><td colspan="7" class="mut">실행 이력 없음</td></tr>'
    src = "".join(f'<li>{e(s)}</li>' for s in c.source) or '<li class="mut">근거 미기재</li>'
    return (f'<h1><span class="mono">{e(c.id)}</span> {badge(c.suite)}</h1><div class="card"><b>{e(c.title)}</b>'
            f'{("<p>" + e(c.description) + "</p>") if c.description else ""}'
            f'<div class="kv"><div>도메인</div><div>{e(", ".join(c.domains) or "–")}</div><div>operation</div><div class="mono">{e(", ".join(c.operations) or "–")}</div>'
            f'<div>테스트 계정</div><div>{e(c.actor or "비로그인")}</div><div>근거 메모</div><div><ul style="margin:0;padding-left:18px">{src}</ul></div><div>파일</div><div class="mono">{e(c.file)} · {e(c.hash)}</div></div></div>'
            f'<h2>덮는 TC (covers)</h2><div class="card"><ul style="margin:0;padding-left:18px">{covers_html}</ul><div style="margin-top:10px">{audit_html}</div></div>'
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


# ---- 기준 (TC 카탈로그) ---------------------------------------------------------------------------
LAYER_KO = {"policy": "정책", "contract": "계약", "manual": "서술"}


def catalog_list(catalog, coverage: dict, last: dict[str, dict], *, domain: str, layer: str, only: str,
                 changes: dict, wiki_available: bool, operators: list[str] | None = None, operator: str = "", hermes: bool = False) -> str:
    by_tc = coverage["by_tc"]
    tabs = "".join(f'<a href="/catalog?domain={e(d)}{("&layer=" + e(layer)) if layer else ""}{("&only=" + e(only)) if only else ""}" class="{"on" if d == domain else ""}">{e(d)}</a>'
                   for d in catalog.domains())
    ltabs = "".join(f'<a href="/catalog?domain={e(domain)}{("&layer=" + l) if l else ""}{("&only=" + e(only)) if only else ""}" class="{"on" if (layer or "") == l else ""}">{lab}</a>'
                    for l, lab in (("", "전체 층"), ("policy", "정책"), ("contract", "계약"), ("manual", "서술")))
    otabs = "".join(f'<a href="/catalog?domain={e(domain)}{("&layer=" + e(layer)) if layer else ""}{("&only=" + o) if o else ""}" class="{"on" if (only or "") == o else ""}">{lab}</a>'
                    for o, lab in (("", "모두"), ("uncovered", "미커버만"), ("covered", "커버만"), ("warn", "경고만")))
    rows = ""
    n = 0
    warn_ids = {w.split(":")[0] for w in catalog.warnings if ":" in w}
    for r in sorted(catalog.records.values(), key=lambda r: (r["layer"], r["id"])):
        if r["domain"] != domain or (layer and r["layer"] != layer):
            continue
        cov = by_tc.get(r["id"], [])
        state = "excluded" if r.get("excluded") else ("covered" if cov else "uncovered")
        if only == "uncovered" and state != "uncovered":
            continue
        if only == "covered" and state != "covered":
            continue
        if only == "warn" and r["id"] not in warn_ids:
            continue
        n += 1
        verdicts = ""
        for cid in cov[:3]:
            lv = last.get(cid)
            verdicts += f' <a href="/cases/{e(cid)}" class="mono small">{e(cid)}</a>' + (f' <a href="/runs/{e(lv["run_id"])}">{badge(lv["verdict"])}</a>' if lv else "")
        b = r.get("binding") or {}
        bind = ", ".join(b.get("operations") or b.get("commands") or []) + ((" · " + b["error_code"]) if b.get("error_code") else "")
        ch = changes.get(r["id"])
        chk = f'<input type="checkbox" name="tc_ids" value="{e(r["id"])}"> ' if state != "excluded" else ""
        rows += (f'<tr class="{"ex" if state == "excluded" else ""}"><td>{chk}{tc_link(r["id"])}</td><td>{badge(r["layer"])} {e(r["title"])}'
                 f'{(" <span class=\"b warn\" title=\"카탈로그 경고\">!</span>") if r["id"] in warn_ids else ""}'
                 f'{(" <span class=\"b drift\">" + e(ch["kind"]) + " " + kst(ch["at"]) + "</span>") if ch else ""}</td>'
                 f'<td class="small mono">{e(bind) or "<span class=\"mut\">API 없음</span>" if r["layer"] == "policy" else e(bind)}</td>'
                 f'<td>{badge({"covered": "덮음", "uncovered": "미커버", "excluded": "제외"}[state], state)}'
                 f'{(" <span class=\"small mut\" title=\"" + e(r["excluded"]) + "\">" + e(r["excluded"][:40]) + ("…" if len(r["excluded"]) > 40 else "") + "</span>") if state == "excluded" else verdicts}</td></tr>')
    if not rows:
        rows = '<tr><td colspan="4" class="mut">해당 없음</td></tr>'
    warns = "".join(f'<li class="small">{e(w)}</li>' for w in catalog.warnings)
    c = catalog.counts()
    v = catalog.versions
    return (f'<h1>기준 — TC 카탈로그 <span class="small mut">{c["total"]}건 (정책 {c["by_layer"].get("policy", 0)} · 계약 {c["by_layer"].get("contract", 0)} · 서술 {c["by_layer"].get("manual", 0)} · 제외 {c["excluded"]})</span></h1>'
            f'<div class="card"><p class="small mut" style="margin-top:0">정본은 llm-wiki 의 <span class="mono">상태-SSOT.yaml</span>(정책)과 백엔드 OpenAPI(계약), 사람이 적은 <span class="mono">catalog/manual-tc.yaml</span>(서술)이다. 플랫폼은 파생만 한다.'
            f' 기준 버전: SSOT <span class="mono">{e(v.get("ssot") or "–")}</span> · OpenAPI <span class="mono">{e(v.get("openapi") or "–")}</span> · 위키 HEAD <span class="mono">{e(v.get("wiki_head") or "–")}</span> · {kst(catalog.built_at)}'
            f'{"" if wiki_available else " · <b style=\"color:var(--warn)\">위키 체크아웃 없음 — 정책 TC 없음</b>"}</p>'
            f'<div class="tabs">{tabs}</div><div class="tabs">{ltabs}</div><div class="tabs">{otabs}</div></div>'
            f'{("<details class=\"card\"><summary>카탈로그 경고 " + str(len(catalog.warnings)) + " — 바인딩·스펙 구조 불일치 (§6.4)</summary><ul>" + warns + "</ul></details>") if catalog.warnings else ""}'
            f'<form method="post" action="/drafts/generate"><div class="card"><div class="actions" style="margin-top:0">'
            f'<select name="operator" required><option value="">— 운영자 —</option>{"".join(f"<option value=\"{e(o)}\" {"selected" if o == operator else ""}>{e(o)}</option>" for o in (operators or []))}</select>'
            f'<button class="primary" {"" if hermes else "disabled title=\"HERMES_API_KEY 없음\""}>고른 TC 로 케이스 초안 생성 (Hermes)</button>'
            f'<span class="small mut">같은 도메인 1~10건. 플랫폼이 TC·OpenAPI·PRD 절을 근거로 넣고, 검증을 통과한 것만 케이스 초안에 들어간다 (§7)</span></div>'
            f'<table><tr><th>TC</th><th>내용 ({n})</th><th>바인딩</th><th>커버 · 마지막 판정</th></tr>{rows}</table></div></form>')


def catalog_detail(rec: dict, covering: list, last: dict[str, dict], excerpts: list, change: dict | None) -> str:
    h = rec.get("expect_hint") or {}
    hint = "".join(f'<div>{e(k)}</div><div>{("<pre style=\"margin:0\">" + e(json.dumps(v, ensure_ascii=False, indent=1)) + "</pre>") if isinstance(v, (dict, list)) else e(v)}</div>'
                   for k, v in h.items() if v not in (None, "", [], {}))
    b = rec.get("binding") or {}
    bind = ("op " + ", ".join(b.get("operations") or [])) if b.get("operations") else (("command " + ", ".join(b.get("commands") or [])) if b.get("commands") else "없음")
    if b.get("error_code"):
        bind += f' · 코드 {b["error_code"]}'
    prd_refs = {f'PRD/{p["doc"]} §{p["section"]}' for p in rec.get("prd") or []}
    src = "".join(f'<li>{e(s)}</li>' for s in rec.get("source") or [] if s not in prd_refs) or '<li class="mut">–</li>'
    prd = "".join(f'<li><a href="{e(p["url"])}">{e(p["doc"])} §{e(p["section"])}</a></li>' for p in rec.get("prd") or [] if p.get("url"))
    ex_html = "".join(
        f'<details {"open" if i == 0 else ""}><summary>{e(ref["doc"])} §{e(ref["section"])}</summary><pre style="background:#fff;color:var(--ink);border:1px solid var(--line)">{e(text) if text else "(본문을 찾지 못했다 — 절 번호가 PRD 헤딩과 다르거나 위키 체크아웃이 없다)"}</pre></details>'
        for i, (ref, text) in enumerate(excerpts))
    cov = "".join(
        f'<tr><td><a href="/cases/{e(c.id)}" class="mono">{e(c.id)}</a></td><td>{e(c.title)}</td><td>{badge(c.suite)}</td>'
        f'<td>{(("<a href=\"/runs/" + e(last[c.id]["run_id"]) + "\">" + badge(last[c.id]["verdict"]) + "</a> <span class=\"small mut\">" + kst(last[c.id]["created_at"]) + "</span>") if c.id in last else "<span class=\"mut\">–</span>")}</td></tr>'
        for c in covering) or '<tr><td colspan="4" class="mut">덮는 케이스 없음</td></tr>'
    state = "제외" if rec.get("excluded") else ("덮음" if covering else "미커버")
    return (f'<h1><span class="mono">{e(rec["id"])}</span> {badge(rec["layer"])} {badge(state, "excluded" if rec.get("excluded") else ("covered" if covering else "uncovered"))}'
            f'{(" <span class=\"b drift\">" + e(change["kind"]) + " " + kst(change["at"]) + "</span>") if change else ""}</h1>'
            f'<div class="card"><b>{e(rec["title"])}</b>'
            f'{("<p class=\"small\" style=\"color:var(--mut)\">제외: " + e(rec["excluded"]) + "</p>") if rec.get("excluded") else ""}'
            f'<div class="kv"><div>도메인</div><div>{e(rec["domain"])}</div><div>종류</div><div>{e(rec.get("kind"))}{(" · actor " + e(rec["actor"])) if rec.get("actor") else ""}</div>'
            f'{("<div>게이트</div><div class=\"mono\">" + e(rec["gate"]) + " " + e(rec.get("gate_name") or "") + "</div>") if rec.get("gate") else ""}'
            f'{("<div>command</div><div class=\"mono\">" + e(rec["command"]) + "</div>") if rec.get("command") else ""}'
            f'<div>바인딩</div><div class="mono">{e(bind)}</div><div>근거</div><div><ul style="margin:0;padding-left:18px">{src}</ul></div>'
            f'{("<div>PRD</div><div><ul style=\"margin:0;padding-left:18px\">" + prd + "</ul></div>") if prd else ""}'
            f'<div>해시</div><div class="mono">{e(rec.get("hash"))}</div></div></div>'
            f'<h2>기대 힌트</h2><div class="card"><div class="kv">{hint or "<div class=\"mut\">–</div><div></div>"}</div></div>'
            f'{("<h2>PRD 본문</h2><div class=\"card\">" + ex_html + "</div>") if excerpts else ""}'
            f'<h2>덮는 케이스</h2><div class="card"><table><tr><th>케이스</th><th>제목</th><th>스위트</th><th>마지막 판정</th></tr>{cov}</table></div>')


# ---- 케이스 초안 --------------------------------------------------------------------------------------
def drafts_list(drafts: list[dict], counts: dict, status: str) -> str:
    tabs = "".join(f'<a href="/drafts{("?status=" + st) if st else ""}" class="{"on" if (status or "") == st else ""}">{lab} {counts.get(st, "") if st else sum(counts.values())}</a>'
                   for st, lab in (("", "전체"), ("draft", "검토 대기"), ("checked", "dev 확인됨"), ("approved", "승인"), ("rejected", "반려")))
    rows = "".join(
        f'<tr><td><a href="/drafts/{e(d["id"])}" class="mono">{e(d["id"])}</a></td><td>{badge(DRAFT_KO.get(d["status"], d["status"]), d["status"])}</td>'
        f'<td class="mono">{e(d.get("case_id") or "–")}</td><td class="small">{" ".join(tc_link(t) for t in d["tc_ids"][:4])}{" …" if len(d["tc_ids"]) > 4 else ""}</td>'
        f'<td class="small">{e((d.get("validation") or {}).get("status") or "–")}{(" · 경고 " + str(len((d.get("validation") or {}).get("warnings") or []))) if (d.get("validation") or {}).get("warnings") else ""}</td>'
        f'<td class="small">{e(d["source"])} · {e(d["operator"])}</td><td class="small mut">{kst(d["created_at"])}</td></tr>'
        for d in drafts) or '<tr><td colspan="7" class="mut">케이스 초안 없음 — 기준 화면에서 TC 를 골라 [케이스 초안 생성]</td></tr>'
    return (f'<h1>케이스 초안 <span class="small mut">아직 케이스가 아닌 것 — Hermes 나 탐색기가 만든 YAML 을 사람이 검토해 승인하면 PR 로 케이스가 된다</span></h1><div class="card"><div class="tabs">{tabs}</div>'
            f'<p class="small mut" style="margin-bottom:0">승인은 스위트 편입이 아니다. 승인된 YAML 을 <span class="mono">qa-platform/cases/</span> 에 붙여 PR 로 리뷰한다. 플랫폼은 git 에 쓰지 않는다.</p></div>'
            f'<div class="card"><table><tr><th>ID</th><th>상태</th><th>케이스 id</th><th>덮는 TC</th><th>검증</th><th>출처 · 만든 사람</th><th>시각</th></tr>{rows}</table></div>')


def draft_detail(d: dict, tc_records: dict, run: dict | None, *, operators: list[str], operator: str) -> str:
    v = d.get("validation") or {}
    problems = "".join(f'<li style="color:var(--bad)">{e(x)}</li>' for x in v.get("errors") or []) + \
        "".join(f'<li style="color:var(--warn)">{e(x)}</li>' for x in v.get("warnings") or [])
    tcs = "".join(f'<li>{tc_link(t)} {badge(r["layer"]) if r else "<span class=\"b fail\">카탈로그에 없음</span>"} {e(r["title"]) if r else ""}</li>'
                  for t, r in tc_records.items()) or '<li class="mut">–</li>'
    ops = "".join(f'<option value="{e(o)}" {"selected" if o == operator else ""}>{e(o)}</option>' for o in operators)
    decided = d["status"] in ("approved", "rejected")
    run_html = ""
    if run:
        run_html = f'<p>확인 실행: <a href="/runs/{e(run["id"])}" class="mono">{e(run["id"])}</a> {run_badge(run)} <span class="small mut">통과 {run["passed"]} 실패 {run["failed"]} 오류 {run["errored"]} skip {run["skipped"]}</span></p>'
    dis = "disabled" if not operator else ""
    forms = "" if decided else (
        f'<form method="post" action="/drafts/{e(d["id"])}/save"><input type="hidden" name="operator" value="{e(operator)}">'
        f'<textarea name="yaml" style="min-height:320px;font-family:ui-monospace,Menlo,monospace;font-size:12px">{e(d["yaml"])}</textarea>'
        f'<div class="actions"><button {dis}>저장하고 다시 검증</button></div></form>'
        f'<div class="actions">'
        f'<form class="inline" method="post" action="/drafts/{e(d["id"])}/check"><input type="hidden" name="operator" value="{e(operator)}"><button {dis} {"disabled" if v.get("errors") else ""}>한 번 실행해 보기 (dev)</button></form>'
        f'<form class="inline" method="post" action="/drafts/{e(d["id"])}/approve"><input type="hidden" name="operator" value="{e(operator)}"><input name="note" placeholder="메모 (선택)"> <button class="primary" {dis} {"disabled" if v.get("errors") else ""}>승인</button></form>'
        f'<form class="inline" method="post" action="/drafts/{e(d["id"])}/reject"><input type="hidden" name="operator" value="{e(operator)}"><input name="note" placeholder="반려 사유"> <button class="danger" {dis}>반려</button></form>'
        f'</div><p class="small mut">운영자: <select onchange="document.cookie=\'qa_operator=\'+this.value+\';path=/;max-age=31536000\';location.reload()"><option value="">— 선택 —</option>{ops}</select> (버튼은 운영자를 고른 뒤 활성화된다)</p>')
    approved_html = ""
    if d["status"] == "approved":
        approved_html = (f'<div class="card" style="background:#f0fdf4"><b>승인됨</b> · {e(d.get("decided_by"))} · {kst(d.get("decided_at"))}{(" · " + e(d.get("note"))) if d.get("note") else ""}'
                         f'<p class="small">아래 YAML 을 <span class="mono">qa-platform/cases/{e(d.get("domain") or "x")}.yaml</span> 의 <span class="mono">cases:</span> 목록에 붙여 PR 을 연다. 리뷰·머지되면 다음 배포에 실린다.</p>'
                         f'<pre id="y">{e(d["yaml"])}</pre><button onclick="navigator.clipboard.writeText(document.getElementById(\'y\').innerText)">복사</button></div>')
    elif d["status"] == "rejected":
        approved_html = f'<div class="card" style="background:#fef2f2"><b>반려</b> · {e(d.get("decided_by"))} · {kst(d.get("decided_at"))}{(" · " + e(d.get("note"))) if d.get("note") else ""}<pre>{e(d["yaml"])}</pre></div>'
    return (f'<h1>케이스 초안 <span class="mono">{e(d["id"])}</span> {badge(DRAFT_KO.get(d["status"], d["status"]), d["status"])}</h1>'
            f'<div class="card"><div class="kv"><div>케이스 id</div><div class="mono">{e(d.get("case_id") or "–")}</div><div>출처</div><div>{e(d["source"])} · {e(d["operator"])} · {kst(d["created_at"])}'
            f'{(" · 근거 해시 <span class=\"mono\">" + e(d.get("prompt_hash")) + "</span>") if d.get("prompt_hash") else ""}</div>'
            f'<div>덮는 TC</div><div><ul style="margin:0;padding-left:18px">{tcs}</ul></div>'
            f'<div>검증</div><div>{badge({"ok": "OK", "warn": "경고", "error": "오류"}.get(v.get("status"), v.get("status") or "–"), {"ok": "pass", "warn": "warn", "error": "fail"}.get(v.get("status"), ""))}'
            f'{("<ul style=\"margin:4px 0 0;padding-left:18px\">" + problems + "</ul>") if problems else ""}</div></div>{run_html}</div>'
            f'{approved_html}{forms}')


# ---- 탐색기 (Swagger 모드) ------------------------------------------------------------------------
def explorer(spec, op, run: dict | None, steps: list[dict], *, actors: list[str], operators: list[str], operator: str, q: str) -> str:
    ql = (q or "").lower()
    items = ""
    for o in sorted(spec.ops.values(), key=lambda o: (o.path, o.method)):
        if not o.path.startswith("/v1/"):
            continue
        if ql and ql not in (o.id + o.path + o.summary).lower():
            continue
        on = "font-weight:600" if op and o.id == op.id else ""
        items += (f'<div class="small" style="{on};padding:2px 0"><a href="/explorer?op={e(o.id)}{("&q=" + e(q)) if q else ""}">'
                  f'<span class="mono">{e(o.method)}</span> {e(o.path)}</a> <span class="mut">{e(o.summary)}</span></div>')
    left = (f'<div class="card"><form method="get"><input name="q" value="{e(q)}" placeholder="검색 (operationId · 경로 · 요약)" style="width:100%"></form>'
            f'<div style="max-height:70vh;overflow:auto;margin-top:8px">{items or "<span class=\"mut\">없음</span>"}</div></div>')
    head = '<h1>탐색기 <span class="small mut">OpenAPI 로 dev 에 한 번 보내 보기</span></h1>'
    if not op:
        right = '<div class="card"><p class="mut">왼쪽에서 op 를 고르면 스펙에서 폼을 만든다. 보내기는 런으로 기록된다 (감사 로그·마스킹·응답 절단 동일).</p></div>'
        return f'{head}<div class="grid" style="grid-template-columns:380px 1fr">{left}{right}</div>'
    pp = "".join(f'<p><label>path <b>{e(x["name"])}</b>{" *" if x["required"] else ""} <span class="small mut">{e(x["description"])}</span><br>'
                 f'<input name="p_{e(x["name"])}" style="width:100%" {"required" if x["required"] else ""}></label></p>'
                 for x in op.params if x["in"] == "path")
    qp = "".join(f'<p><label>query <b>{e(x["name"])}</b>{" *" if x["required"] else ""} <span class="small mut">{e(x["description"])}</span><br>'
                 f'<input name="q_{e(x["name"])}" style="width:100%"></label></p>'
                 for x in op.params if x["in"] == "query")
    body = ""
    if op.method in ("POST", "PUT", "PATCH"):
        ex = json.dumps(op.request_example, ensure_ascii=False, indent=1) if op.request_example is not None else ""
        body = (f'<p><label>본문 (JSON) <span class="small mut">스펙 예시로 채웠다. 만드는 데이터의 title 은 [QA] 로</span><br>'
                f'<textarea name="body" style="min-height:180px;font-family:ui-monospace,Menlo,monospace;font-size:12px">{e(ex)}</textarea></label></p>')
    acts = "".join(f'<option value="{e(a)}">{e(a)}</option>' for a in actors)
    ops = "".join(f'<option value="{e(o)}" {"selected" if o == operator else ""}>{e(o)}</option>' for o in operators)
    errs = "".join(f'<li><span class="mono">{e(code)}</span> {e(i.get("status"))} {e(i.get("message"))}</li>' for code, i in op.errors.items()) or "<li class='mut'>문서화된 에러 없음</li>"
    form = (f'<div class="card"><h3 style="margin-top:0"><span class="mono">{e(op.method)}</span> {e(op.path)} <span class="small mut">{e(op.id)} · {e(op.summary)}</span></h3>'
            f'<form method="post" action="/explorer/send"><input type="hidden" name="op" value="{e(op.id)}">{pp}{qp}{body}'
            f'<p><select name="actor"><option value="">비로그인</option>{acts}</select> <select name="operator" required><option value="">— 운영자 —</option>{ops}</select> '
            f'<button class="primary">보내기</button> <span class="small mut">dev 에 실제로 보낸다. 쓰기 op 도 허용 (테스트 계정 2개뿐)</span></p></form>'
            f'<details><summary class="small mut">문서화된 에러 코드</summary><ul class="small">{errs}</ul></details></div>')
    result = ""
    if run and steps:
        st = steps[0]
        resp = st.get("response") or {}
        rbody = resp.get("json") if resp.get("json") is not None else resp.get("text")
        req = st["request"]
        ok = str(resp.get("status") or "").startswith("2")
        result = (f'<div class="card"><h3 style="margin-top:0">응답 {badge(str(resp.get("status") or "–"), "ok" if ok else "warn")} '
                  f'<span class="small mut">{resp.get("elapsed_ms") or 0} ms · 런 <a href="/runs/{e(run["id"])}" class="mono">{e(run["id"])}</a></span></h3>'
                  f'{("<div class=\"small\" style=\"color:var(--bad)\">" + e(st.get("error")) + "</div>") if st.get("error") else ""}'
                  f'<details open><summary class="small mut">응답 본문</summary><pre>{e(json.dumps(rbody, ensure_ascii=False, indent=1) if not isinstance(rbody, str) else rbody)}</pre></details>'
                  f'<details><summary class="small mut">보낸 요청</summary><pre>{e(json.dumps({k: v for k, v in req.items() if k in ("url", "query", "body", "headers", "actor")}, ensure_ascii=False, indent=1))}</pre></details>'
                  f'<form method="post" action="/explorer/draft" class="actions"><input type="hidden" name="run" value="{e(run["id"])}"><input type="hidden" name="operator" value="{e(operator)}">'
                  f'<button {"" if operator else "disabled"}>케이스 단계로 담기 (케이스 초안)</button> <span class="small mut">관측한 status·error_code 를 기대로 채운 manual 초안. covers 는 사람이 채운다</span></form></div>')
    return f'{head}<div class="grid" style="grid-template-columns:380px 1fr">{left}<div>{form}{result}</div></div>'


# ---- 가이드 --------------------------------------------------------------------------------------
def _sec(title: str, body: str) -> str:
    return f'<h2>{title}</h2><div class="card">{body}</div>'


def guide(*, public_url: str, target: str, wiki_url: str, sprint_days: int) -> str:
    intro = ('<h1>가이드 — 이 플랫폼은 무엇을 하고, 어떻게 쓰는가</h1>'
             '<div class="card"><p style="margin:0"><b>한 줄.</b> 기획 문서(llm-wiki 의 PRD·상태-SSOT)와 백엔드 API 계약(OpenAPI)에서 <b>검증 기준(TC)</b> 을 뽑고 '
             '그 기준을 덮는 <b>케이스</b>(YAML)를 사람이 버튼을 눌러 dev 서버에 실행해 <b>누가 언제 무엇을 검증했는지</b> 남긴다. 자동으로 도는 것은 없다.</p></div>')

    s1 = f"""
<ol>
<li><b>사람이 버튼을 누른다.</b> 대시보드의 [검증](배포 1건) · [스프린트 smoke 실행] · [릴리스 검증] · [임의 실행]. 크론·webhook·자동 실행은 설계상 두지 않았다. 배포 목록은 GitHub Actions 를 <i>읽어서</i> 보여 줄 뿐이다.</li>
<li><b>확인 화면</b>에서는 플랫폼이 범위를 <i>제안</i>한다. 배포 검증이면 PR 변경 파일 → 도메인 → 그 도메인의 sanity 케이스, 스프린트면 smoke 전체다. 운영자(자기 신고)를 고르고 케이스를 조정한 뒤 [실행].</li>
<li><b>런이 만들어지면서</b> 그 시점의 케이스 본문(스냅샷)·기준 버전(SSOT·OpenAPI 해시)·대상(<span class="mono">{e(target)}</span>)이 런에 고정된다. 나중에 케이스나 기준이 바뀌어도 과거 런은 그대로다.</li>
<li><b>러너가 순서대로 보낸다.</b> 한 번에 런 하나, 케이스는 순차, 단계는 요청 → 응답 → 단언(expect 5종: status · result · error_code · json · exists). 테스트 계정이 필요하면 <span class="mono">POST /v1/auth/dev-sessions</span> 로 토큰을 받아 Bearer 로 보낸다(기록에는 마스킹).</li>
<li><b>판정.</b> 단언 불일치 = <b>fail</b>, 예외·네트워크 = <b>error</b>, 테스트 계정·픽스처 미설정 = <b>skipped</b>(설정 문제, 실패 아님). 런 판정은 케이스 판정의 합. Slack 에 시작·종료가 간다.</li>
<li><b>실패하면</b> 런 상세에서 단계별 요청·응답·단언을 본다. [Hermes 진단] 을 누르면 AI 가 <i>버그 / 케이스 노후 / 환경</i> 중 하나로 분류하고 다음 행동을 제안한다. 진단도 사람이 누를 때만 돈다.</li>
</ol>
<p class="small mut">모든 버튼은 활동 화면(감사 로그)에 운영자·세션 해시·IP 와 함께 남는다. 세션은 팀 공용이라 운영자는 자기 신고다.</p>"""

    s2 = f"""
<p>플랫폼은 TC 를 <b>만들지 않는다</b>. 정본에서 <b>파생</b>하고 같은 입력이면 같은 카탈로그가 나온다.</p>
<table><tr><th>층</th><th>정본</th><th>TC 예</th><th>답하는 질문</th></tr>
<tr><td>정책</td><td><a href="{e(wiki_url)}/policy/">상태-SSOT.yaml</a> (기획 SSOT) — team-wiki-v2 의 <span class="mono">render_tests.cases()</span> 를 그대로 가져와 쓴다</td><td><span class="mono">G.room.create#8</span> (게이트 8번째 검사에서 거절) · <span class="mono">C.room.create</span> (성공 전이)</td><td>기획이 정한 규칙이 지켜지는가</td></tr>
<tr><td>계약</td><td>백엔드 OpenAPI (dev 브랜치, REST Docs 산출물)</td><td><span class="mono">op.createRoom:200</span> · <span class="mono">op.createRoom:E1402</span></td><td>API 가 문서대로 응답하는가</td></tr>
<tr><td>서술</td><td>사람이 적는 <span class="mono">qa-platform/catalog/manual-tc.yaml</span> (PRD 절 · 운영 기준)</td><td><span class="mono">PRD.룸-탐색.4.1#1</span> · <span class="mono">OPS.platform.health#1</span></td><td>SSOT 로 형식화되지 않은 요구</td></tr></table>
<p><b>기획과 API 는 1:1 이 아니다.</b> 그래서 <span class="mono">catalog/bindings.yaml</span> 이 SSOT command ↔ operationId, 게이트 검사 ↔ 에러 코드를 잇는다(다대다 허용). 못 잇는 것은 "API 없음" 으로 남는다. 자동화할 수 없는 TC(시스템 전이·OAuth·운영자 전용)는 <span class="mono">catalog/exclusions.yaml</span> 에 <b>사유와 함께</b> 뺀다. 분모에서 빠지지만 화면에는 보인다.</p>
<p><b>케이스는 <span class="mono">covers:</span> 로 어떤 TC 를 덮는지 선언</b>하고 플랫폼이 그 선언을 검증한다 — TC id 가 실재하는지, 계약 TC 라면 단계의 method·path·기대 코드가 실제로 그 계약과 맞는지. 거짓 선언은 "대조 오류" 로 스위트에서 빠진다. 커버리지 분모는 전체 TC 다.</p>
<p><b>기준이 바뀌면.</b> 위키 SSOT 나 OpenAPI 가 바뀌면 카탈로그가 다시 계산되고(읽기라 자동), 덮는 TC 가 바뀐 케이스에 <span class="b drift">근거 변경</span> 배지가 붙는다. 케이스를 다시 본 뒤 <span class="mono">reviewed: {{at, by}}</span> 를 적으면 그 이후 변경만 배지로 뜬다. 케이스를 자동으로 고치거나 런을 자동으로 돌리지는 않는다.</p>"""

    s3 = """
<table><tr><th>화면</th><th>언제</th><th>무엇</th></tr>
<tr><td><a href="/">대시보드</a></td><td>매일</td><td>미검증 dev 배포, 이번 스프린트 smoke 여부, 기준 커버리지 매트릭스, 최근 런</td></tr>
<tr><td><a href="/runs">런</a></td><td>실행 후</td><td>런 목록·상세(단계별 요청·응답·단언), Hermes 진단, 릴리스 판단 기록</td></tr>
<tr><td><a href="/cases">케이스</a></td><td>케이스 관리</td><td>정본은 git <span class="mono">qa-platform/cases/*.yaml</span>. 대조 상태·근거 변경 배지·실행 이력. [파일에서 다시 읽기]</td></tr>
<tr><td><a href="/catalog">기준</a></td><td>커버리지 확인 · 초안 만들 때</td><td>도메인×층 TC 목록, 덮는 케이스, 바인딩, 제외 사유, 카탈로그 경고(스펙 누락 등). TC 를 골라 [케이스 초안 생성]</td></tr>
<tr><td><a href="/drafts">케이스 초안</a></td><td>케이스 늘릴 때</td><td>Hermes·탐색기가 만든 케이스 YAML 초안. 편집 → 재검증 → [한 번 실행해 보기] → 승인(YAML 복사 → PR) 또는 반려</td></tr>
<tr><td><a href="/explorer">탐색기</a></td><td>손으로 확인할 때</td><td>OpenAPI 에서 폼을 만들어 dev 에 한 번 보낸다. 전송도 런으로 기록. 응답을 [케이스 단계로 담기]</td></tr>
<tr><td><a href="/activity">활동</a></td><td>누가 뭘 했는지</td><td>감사 로그 전부</td></tr></table>"""

    s4 = """
<ol>
<li><b>PR 을 dev 에 머지한다.</b> 백엔드 CI 가 dev 에 배포하면 대시보드 "dev 배포" 에 <span class="b warn">미검증</span> 으로 뜬다 (GitHub Actions 조회, 1분 캐시).</li>
<li><b>[검증] 을 누른다.</b> 플랫폼이 PR 변경 파일에서 도메인을 읽어 그 도메인의 sanity 를 제안한다. 확인하고 실행. 통과하면 그 배포에 ✅ 가 붙는다.</li>
<li><b>실패하면 셋 중 하나다.</b> (a) 버그 → 고친다. (b) 케이스 노후 — 기획이 바뀌어 케이스가 틀렸다 → 케이스 YAML 을 고쳐 PR. (c) 환경 — 픽스처(공고 id 등)가 바뀜 → SSM <span class="mono">qa-fixtures</span> 를 고친다. Hermes 진단이 셋 중 무엇인지 제안한다.</li>
<li><b>새 기능이면 기준을 먼저 본다.</b> 기획이 SSOT 에 반영돼 있으면 기준 화면에 TC 가 이미 있다. 없으면 위키(SSOT/PRD)를 먼저 고친다. 플랫폼에서 TC 를 직접 만들지 않는다. API 가 새로 생겼으면 <span class="mono">catalog/bindings.yaml</span> 에 command ↔ operationId 를 잇는다.</li>
<li><b>케이스를 늘린다.</b> 기준 화면에서 미커버 TC 를 골라 [케이스 초안 생성] → 케이스 초안에서 [한 번 실행해 보기] → 승인 → YAML 을 <span class="mono">qa-platform/cases/&lt;도메인&gt;.yaml</span> 에 붙여 PR. 리뷰·머지되면 다음 배포에 실린다. 승인 없이 스위트에 들어가는 케이스는 없다.</li>
<li><b>쓰기 케이스 규칙.</b> 만든 데이터는 같은 케이스 안에서 닫고(취소·철회·삭제) 만드는 데이터의 title 은 <span class="mono">[QA]</span> 로 시작한다. 테스트 계정(qa-host · qa-guest)만 쓴다 — 목데이터 회원은 참여 슬롯이 차 있어 쓰기에 못 쓴다.</li>
</ol>"""

    s5 = f"""
<ul>
<li><b>스프린트마다 한 번</b> ({sprint_days}일 주기, Linear 사이클과 같은 번호) 대시보드에서 [스프린트 smoke 실행]. 배지가 "미실행" 이면 아직 안 한 것이다. 마감 하루 전까지 없으면 Slack 에 한 번 알린다 — 알림만 하고 실행은 하지 않는다.</li>
<li><b>실배포 전</b> [릴리스 검증] → smoke 전체 실행 → 런 상세의 릴리스 체크리스트(백엔드 <span class="mono">docs/knowledge/release-checklist.md</span> 에서 읽어 옴)를 확인하고 GO / NO-GO 를 <b>기록</b>한다. 기록만 하고 승격을 막지는 않는다.</li>
<li><b>보고서.</b> 스프린트·릴리스 런은 [위키에 발행] 로 llm-wiki <span class="mono">wiki/qa/</span> 에 남길 수 있다. 사람이 누를 때만, 개인 식별값은 마스킹.</li>
</ul>"""

    s6 = f"""
<p><b>왜 자동으로 안 도나?</b> 결정이다. 실행의 시작은 언제나 사람이어야 이력에 의미가 있고 dev 데이터 오염·런 폭주·알림 피로가 구조적으로 막힌다. 카탈로그 <i>계산</i>은 읽기라 자동이지만 실행·전송·케이스 초안 생성·발행은 전부 버튼이다.</p>
<p><b>skipped 는 실패인가?</b> 아니다. 테스트 계정(<span class="mono">qa-actors</span>)이나 픽스처(<span class="mono">qa-fixtures</span>)가 없어 못 보낸 것이다. 설정을 먼저 본다.</p>
<p><b>카탈로그 경고는?</b> 바인딩한 에러 코드가 OpenAPI 예시에 없다는 뜻이다(예: E1425·E1427 은 dev 에서 확인됐지만 스펙에 아직 없음). 백엔드 REST Docs 에 예시를 추가하면 사라진다.</p>
<p><b>정본은 어디?</b> 케이스 = git <span class="mono">qa-platform/cases/</span>. 기준 = llm-wiki SSOT·PRD + OpenAPI. 바인딩·제외·서술 TC = <span class="mono">qa-platform/catalog/</span>. DB 에는 런·감사 로그·케이스 초안만 있다.</p>
<p class="small mut">설계 문서: <span class="mono">docs/qa-platform.md</span>(P0·P1, 런북) · <span class="mono">docs/qa-platform-tc.md</span>(P2, 기준 관리). 이 화면은 <span class="mono">{e(public_url)}/guide</span>.</p>"""

    s_ai = """
<p><b>런타임에는 AI 가 없다.</b> 트리거를 누르면 도는 것은 결정론 러너다 — 케이스에 적힌 요청을 보내고 적힌 단언과 비교한다. 같은 케이스·같은 서버면 같은 판정이 나온다. 매 실행마다 LLM 이 판단하면 비용이 들고 결과가 흔들리고 이력을 믿을 수 없어서 설계에서 뺐다.</p>
<p><b>TC 도 AI 가 만들지 않고</b> SSOT·OpenAPI 에서 규칙으로 파생된다(§2). AI 가 "기준" 을 만들면 기준이 정본에서 떠난다.</p>
<p>AI(Hermes)가 개입하는 지점은 <b>둘뿐이고 둘 다 사람이 버튼을 누를 때만</b> 돈다.</p>
<table><tr><th>시점</th><th>버튼</th><th>AI 가 하는 것</th><th>AI 가 못 하는 것</th></tr>
<tr><td>케이스를 늘릴 때</td><td>기준 화면 [케이스 초안 생성]</td><td>고른 TC + OpenAPI 발췌 + PRD 절 본문을 근거로 케이스 YAML 초안을 쓴다</td><td>초안을 스위트에 넣지 못한다. 플랫폼의 결정론 검증(covers ⊆ 요청 TC, method·path·코드 일치, 테스트 계정 실재)을 통과한 것만 케이스 초안에 들어가고 사람이 승인해 PR 로 올려야 케이스가 된다</td></tr>
<tr><td>런이 실패한 뒤</td><td>런 상세 [Hermes 진단]</td><td>단계별 요청·응답·단언만 보고 <i>버그 / 케이스 노후 / 환경</i> 중 하나로 분류하고 다음 행동을 제안한다</td><td>판정을 바꾸지 못한다. 진단은 런 케이스에 메모로 붙을 뿐이다</td></tr></table>
<p class="small mut">위키 도구도 AI 에게 주지 않는다. 근거는 플랫폼이 프롬프트에 넣어 주므로 케이스 초안이 무엇을 근거로 했는지가 해시로 남고 검증이 그 근거와 대조할 수 있다. 런타임에 AI 가 탐색적으로 API 를 두드리는 "에이전트 런" 은 만들지 않았다. 필요하면 별도 결정이다.</p>"""
    return (intro + _sec("1. 트리거를 누르면 무슨 일이 일어나나", s1) + _sec("2. 검증 기준(TC)은 어디서 오나", s2)
            + _sec("3. AI 는 언제 개입하나", s_ai)
            + _sec("4. 화면별로 무엇을 하나", s3) + _sec("5. 기능을 개발하고 나면 — 개발자 워크플로우", s4)
            + _sec("6. QA 워크플로우 — 스프린트와 릴리스", s5) + _sec("7. 자주 묻는 것", s6))
