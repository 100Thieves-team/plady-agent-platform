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
nav{background:#111827;color:#fff;padding:0 20px;display:flex;align-items:center;gap:18px;height:48px;overflow-x:auto;white-space:nowrap}nav a{flex:none}
nav a{color:#d1d5db}nav a.on{color:#fff;font-weight:600}nav .brand{font-weight:700;color:#fff;margin-right:8px}nav .op{margin-left:auto;color:#9ca3af}
main{max-width:1180px;margin:0 auto;padding:20px}
h1{font-size:20px;margin:0 0 14px}h2{font-size:15px;margin:22px 0 8px;color:var(--gray)}h3{font-size:14px;margin:14px 0 6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mut);font-weight:600;font-size:12px}
tr:last-child td{border-bottom:0}.mut{color:var(--mut)}.small{font-size:12px}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.b{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;line-height:18px}
.b.pass,.b.finished-pass{color:var(--ok);background:var(--okbg)}.b.fail,.b.error,.b.finished-fail,.b.finished-error{color:var(--bad);background:var(--badbg)}
.b.skipped,.b.canceled,.b.queued,.b.finished-skipped,.b.finished-canceled{color:var(--gray);background:var(--graybg)}.b.running{color:var(--warn);background:var(--warnbg)}
.b.smoke{color:var(--info);background:var(--infobg)}.b.sanity{color:#6d28d9;background:#ede9fe}.b.manual{color:var(--gray);background:var(--graybg)}.b.setup{color:#0f766e;background:#ccfbf1}
.b.warn{color:var(--warn);background:var(--warnbg)}.b.ok{color:var(--ok);background:var(--okbg)}
button,.btn{display:inline-block;border:1px solid #d1d5db;background:#fff;color:var(--ink);border-radius:7px;padding:6px 12px;font:inherit;cursor:pointer}
button.primary,.btn.primary{background:var(--info);color:#fff;border-color:var(--info)}button.primary:hover{background:#1e40af}button.wide{display:block;width:100%;padding:11px 14px;font-weight:600;font-size:15px;border-radius:9px;margin-top:6px}button.danger{color:var(--bad);border-color:#fca5a5}
button:disabled{opacity:.5;cursor:default}form.inline{display:inline}
input,select,textarea{font:inherit;padding:7px 10px;border:1px solid #d1d5db;border-radius:8px;background:#fff}textarea{width:100%;min-height:60px}input:focus,select:focus,textarea:focus{outline:2px solid #bfdbfe;border-color:var(--info)}
pre{background:#0f172a;color:#e2e8f0;padding:10px 12px;border-radius:8px;overflow:auto;font-size:12px;margin:6px 0}
details{margin:6px 0}summary{cursor:pointer}.kv{display:grid;grid-template-columns:120px 1fr;gap:4px 10px}.kv div:nth-child(odd){color:var(--mut)}
.flash{padding:10px 14px;border-radius:8px;margin-bottom:14px}.flash.err{background:var(--badbg);color:var(--bad)}.flash.ok{background:var(--okbg);color:var(--ok)}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.chk{display:block;padding:3px 0}.right{text-align:right}
.b.policy{color:#0f766e;background:#ccfbf1}.b.contract{color:#9a3412;background:#ffedd5}.b.manual{color:var(--gray);background:var(--graybg)}
.b.covered{color:var(--ok);background:var(--okbg)}.b.uncovered{color:var(--bad);background:var(--badbg)}.b.excluded{color:var(--mut);background:var(--graybg)}
.b.drift{color:var(--warn);background:var(--warnbg)}.b.unchecked{color:var(--mut);background:var(--graybg)}
tr.ex td{color:var(--mut)}.tabs a{display:inline-block;padding:4px 10px;border-radius:6px;margin:0 4px 6px 0;border:1px solid var(--line);background:#fff}.tabs a.on{background:#111827;color:#fff;border-color:#111827}
a.btn{display:inline-block;padding:5px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;font-size:13px;font-weight:500;text-decoration:none;vertical-align:middle}
/* 도움말 '?' 와 모달 (qa/help.py) */
.help{display:inline-flex;align-items:center;justify-content:center;width:17px;height:17px;padding:0;margin:0 0 0 4px;border:1px solid #b6c2d0;border-radius:50%;background:#fff;color:#5b6b7c;font:600 11px/1 ui-monospace,Menlo,monospace;cursor:pointer;vertical-align:middle}
.help:hover{background:var(--infobg);color:var(--info);border-color:var(--info)}th .help,h1 .help,h2 .help,h3 .help{font-weight:600}
#help-modal{position:fixed;inset:0;z-index:60;background:rgba(17,24,39,.45);display:none;align-items:center;justify-content:center;padding:16px}#help-modal.open{display:flex}
.hm-box{background:var(--card);color:var(--ink);border-radius:14px;max-width:560px;width:100%;max-height:85vh;overflow:auto;box-shadow:0 20px 60px rgba(0,0,0,.3)}
.hm-head{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--line)}.hm-head b{flex:1;font-size:15px}.hm-x{border:0;background:transparent;font-size:16px;cursor:pointer;color:var(--mut)}
.hm-body{padding:14px 18px;font-size:14px;line-height:1.6}.hm-body p{margin:0 0 10px}.hm-body p:last-child{margin:0}.hm-foot{padding:10px 18px;border-top:1px solid var(--line);font-size:12px}
nav .op a{color:#9ca3af;margin-left:6px}nav .op .help{border-color:#4b5563;background:transparent;color:#9ca3af}
/* 폼 부품 (토스 카드식): 라벨 위 · 칸은 가로로 꽉 · 필수는 빨간 점 · 칸 아래 회색 힌트 */
.field{margin:0 0 12px}.field>label{display:block;font-weight:500;margin-bottom:4px}.field>input,.field>select,.field>textarea{width:100%}.field textarea{font-family:ui-monospace,Menlo,monospace;font-size:12px}
.req::after{content:'•';color:var(--bad);margin-left:3px;font-weight:700}.hint{color:var(--mut);font-size:12px;margin:4px 0 0}.hint.bad{color:var(--bad)}.field>label .hint{display:inline;margin-left:6px;font-weight:400}
.radio{display:inline-block;margin:4px 14px 0 0}.radio input{width:auto;margin-right:4px}
.seg{display:inline-flex;background:#eef0f3;border-radius:9px;padding:3px}.seg button{border:0;background:transparent;color:var(--mut);padding:4px 12px;border-radius:7px;font-weight:600;font-size:13px}.seg button.on{background:#fff;color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,.12)}
.m{display:inline-block;min-width:52px;text-align:center;padding:2px 8px;border-radius:6px;font:700 11px/16px ui-monospace,Menlo,monospace;color:#fff;background:var(--gray);vertical-align:middle}
.m.get{background:#2563eb}.m.post{background:#16a34a}.m.put,.m.patch{background:#d97706}.m.delete{background:#dc2626}
/* API 호출: 왼쪽 목록 + 오른쪽 입력 폼 (Normal | Swagger). 좁으면 1열 */
/* 실행 결과 요약 (Tossion 식): 요약 카드 · 도넛 · 도메인별 진행 막대 */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.stat .l{color:var(--mut);font-size:12px}.stat b{display:block;font-size:26px;line-height:1.2;margin:4px 0 2px}.stat .s{font-size:12px;color:var(--mut)}.stat.ok b{color:var(--ok)}.stat.bad b{color:var(--bad)}
.sumgrid{display:grid;grid-template-columns:200px 1fr;gap:20px;align-items:center}@media(max-width:700px){.sumgrid{grid-template-columns:1fr}}
.legend{list-style:none;padding:0;margin:0}.legend li{display:flex;align-items:center;gap:8px;padding:3px 0}.legend i{width:10px;height:10px;border-radius:50%;display:inline-block}
.bar{display:flex;height:10px;border-radius:5px;overflow:hidden;background:var(--graybg);min-width:120px}.bar i{display:block;height:100%}.bar .p{background:#16a34a}.bar .f{background:#dc2626}.bar .s{background:#9ca3af}.bar .r{background:#f59e0b}
.dom{display:grid;grid-template-columns:130px 1fr 90px;gap:10px;align-items:center;padding:5px 0;border-bottom:1px solid var(--line)}.dom:last-child{border-bottom:0}
.xgrid{display:grid;grid-template-columns:380px 1fr;gap:16px;align-items:start}.setup-grid{grid-template-columns:repeat(auto-fit,minmax(480px,1fr));align-items:start}@media(max-width:560px){.setup-grid{grid-template-columns:1fr}}@media(max-width:860px){.xgrid{grid-template-columns:1fr}}
.opl .oplist{max-height:70vh;overflow:auto;margin-top:8px}.opl details{margin:2px 0}.opl summary{font-weight:600;padding:4px 0}
.opi{display:flex;align-items:center;gap:6px;padding:3px 0 3px 4px;border-radius:6px}.opi.on{background:#eef2ff}.opi a{white-space:nowrap}.opi .small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.star{border:0;background:transparent;color:#cbd5e1;padding:0 2px;cursor:pointer;font-size:14px}.star.on{color:#f59e0b}
.call .callhead{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:6px}.call .qaline{margin:6px 0 14px}
.qab{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;background:var(--graybg);color:var(--gray)}.qab.ok{background:var(--okbg);color:var(--ok)}.qab.warn{background:var(--warnbg);color:var(--warn)}a.qab:hover{text-decoration:none;filter:brightness(.95)}
.call .view.bad [data-bk]{opacity:.5;pointer-events:none}.call [data-bk].bad,.call textarea.bad{border-color:var(--bad)}
.call .sline{margin:0 0 10px}.call h4{font-size:13px;margin:12px 0 6px;color:var(--gray)}.call .params td input{width:100%}.call .params td:first-child{white-space:nowrap}
.call .callfoot{border-top:1px solid var(--line);margin-top:14px;padding-top:12px}
/* Hermes 위젯 (채널톡처럼 어느 화면에서나) */
#hx-btn{position:fixed;right:22px;bottom:22px;z-index:50;border:0;border-radius:999px;background:#111827;color:#fff;font-weight:600;padding:12px 18px;box-shadow:0 6px 20px rgba(0,0,0,.25);cursor:pointer;font-size:14px}
#hx{position:fixed;right:22px;bottom:80px;z-index:51;width:400px;max-width:calc(100vw - 32px);height:600px;max-height:calc(100vh - 100px);background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.25);display:none;flex-direction:column;overflow:hidden}
#hx.open{display:flex}#hx.inline{position:static;width:100%;max-width:none;height:70vh;max-height:none;display:flex;box-shadow:none}
.hx-head{display:flex;align-items:center;gap:6px;padding:10px 12px;background:#111827;color:#fff;font-weight:600}.hx-head .t{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
.hx-head button{background:transparent;border:1px solid #374151;color:#d1d5db;border-radius:6px;padding:3px 8px;font-size:12px;cursor:pointer}.hx-head button:hover{color:#fff;border-color:#9ca3af}
.hx-body{flex:1;overflow:auto;padding:12px;background:var(--bg);display:flex;flex-direction:column}.hx-body .msg{max-width:94%}
.msg{padding:9px 12px;border-radius:10px;margin:6px 0;white-space:pre-wrap;word-break:break-word;font-size:13px;line-height:1.45}.msg.user{background:#eef2ff;align-self:flex-end}.msg.assistant{background:var(--card);border:1px solid var(--line);align-self:flex-start}.msg.err{background:var(--badbg);color:var(--bad)}
.msg .who{font-size:11px;color:var(--mut);margin-bottom:3px}.msg .cur::after{content:'▍';color:var(--mut);animation:hxb 1s infinite}@keyframes hxb{50%{opacity:0}}
.tc{display:inline-block;font:11px ui-monospace,Menlo,monospace;background:var(--graybg);color:var(--gray);border-radius:6px;padding:2px 7px;margin:4px 4px 0 0;cursor:pointer}.tc.run{background:var(--warnbg);color:var(--warn)}.tc pre{display:none;white-space:pre-wrap;max-height:200px;overflow:auto;margin:4px 0 0;font-size:11px;background:#fff;padding:6px;border-radius:4px;color:var(--ink)}.tc.on pre{display:block}
.hx-foot{border-top:1px solid var(--line);padding:8px 10px;background:var(--card)}.hx-foot textarea{width:100%;min-height:44px;max-height:140px;resize:vertical;font-size:13px}.hx-foot .row{display:flex;gap:6px;align-items:center;margin-top:6px;font-size:12px;color:var(--mut)}.hx-foot .row button{margin-left:auto}
.hx-list a{display:block;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);margin-bottom:6px;color:var(--ink)}.hx-list a small{display:block;color:var(--mut)}.hx-note{font-size:12px;color:var(--mut);padding:8px 0}
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


def h(key: str) -> str:
    """기능 옆 '?' 도움말 버튼 — 내용은 qa/help.py 의 HELP[key], 모달은 /static/help.js."""
    return f'<button type="button" class="help" data-help="{e(key)}" aria-label="도움말" title="이게 뭐지? 어떻게 쓰지?">?</button>'


def badge(v: str | None, extra: str = "") -> str:
    v = v or "–"
    return f'<span class="b {e(v)} {extra}">{e(v)}</span>'


def run_badge(r: dict) -> str:
    if r["status"] == "finished":
        return badge(r.get("verdict"))
    return badge(r["status"])


TRIGGER_KO = {"deploy-sanity": "배포 검증", "sprint-smoke": "스프린트 smoke", "release": "릴리스 QA", "manual": "수동 실행",
              "draft-check": "저장 전 실행", "explorer": "API 호출", "setup": "테스트 데이터 만들기"}
ACTION_KO = {"run.create": "테스트 실행 시작", "run.cancel": "테스트 실행 취소", "run.triage": "Hermes 실패 분석", "release.decide": "릴리스 판단",
             "chat.create": "대화 시작", "chat.send": "대화 메시지", "chat.close": "대화 닫기", "mcp.call": "Hermes 도구 호출", "mcp.denied": "MCP 인증 거부",
             "cases.reload": "스크립트 다시 읽기", "draft.generate": "스크립트 초안 생성 (예전)", "draft.rejected_by_validation": "스크립트 초안 검증 탈락 (예전)",
             "draft.save": "스크립트 초안 편집 (예전)", "draft.check": "스크립트 초안 시험 실행 (예전)", "draft.approve": "남은 초안 저장", "draft.reject": "남은 초안 버림",
             "case.save": "스크립트 저장", "case.delete": "스크립트 삭제", "case.try": "저장 전 실행", "manual_tc.save": "수동 작성 TC 저장", "manual_tc.delete": "수동 작성 TC 삭제",
             "hermes.generate": "Hermes 가 쓰기", "hermes.rejected_by_validation": "Hermes 결과 검증 탈락", "explorer.to_form": "API 호출을 스크립트 폼으로",
             "run.publish": "위키 보고서 게시", "explorer.send": "API 직접 호출", "operator.pick": "담당자 고르기", "hermes_job.start": "Hermes 작업 시작", "hermes_job.cancel": "Hermes 작업 그만두기", "draft.form_save": "폼으로 초안 저장 (예전)", "draft.delete_request": "삭제 요청 (예전)", "setup.run": "테스트 데이터 만들기 실행", "qa_data.delete_room": "QA 룸 삭제", "qa_data.delete_all": "QA 데이터 일괄 삭제", "qa_data.reset": "테스트 계정 초기화", "qa_data.delete_member": "QA 회원 삭제", "qa_data.create_member": "QA 테스트 회원 만들기", "spec.refresh": "API 문서 다시 읽기", "sprint.remind": "스프린트 smoke 리마인드(Slack)"}
DRAFT_KO = {"draft": "저장 안 됨", "checked": "저장 안 됨 · 실행해 봄", "approved": "저장됨", "rejected": "버림", "failed": "저장 실패"}


def page(title: str, body: str, *, active: str = "", operator: str = "", flash: tuple[str, str] | None = None,
         context: dict | None = None, hermes: bool = False, operators: list | tuple = (), autostart: dict | None = None,
         inline_chat: str | None = None) -> str:
    """모든 화면의 껍데기. Hermes 위젯(채널톡처럼 오른쪽 아래)이 어느 화면에나 붙는다 — context 는 그 화면의 객체(run·case·tc),
    autostart 는 위젯을 새 대화로 바로 열기, inline_chat 은 /chat/{id} 처럼 본문 안에 크게 그리기."""
    nav = "".join(
        f'<a href="{href}" class="{"on" if active == key else ""}">{label}</a>'
        for key, href, label in (("dash", "/", "대시보드"), ("runs", "/runs", "실행 기록"), ("features", "/features", "시나리오"), ("cases", "/cases", "테스트 스크립트"), ("catalog", "/catalog", "테스트 케이스 (TC)"), ("drafts", "/drafts", "변경 기록"), ("chat", "/chat", "Hermes"), ("apis", "/apis", "API"), ("explorer", "/explorer", "API 호출"), ("setup", "/setup", "테스트 데이터 만들기"), ("activity", "/activity", "감사 로그"), ("guide", "/guide", "가이드"))
    )
    fl = f'<div class="flash {e(flash[0])}">{e(flash[1])}</div>' if flash else ""
    qa = {"operator": operator, "operators": list(operators), "context": {k: v for k, v in (context or {}).items() if v}, "hermes": bool(hermes),
          "autostart": autostart, "inline": inline_chat}
    inline = f'<div id="hx-inline"></div>' if inline_chat else ""
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)} · QA</title><style>{CSS}</style></head><body>'
            f'<nav><span class="brand">Plady QA</span>{nav}<span class="op">{("담당자: <b style=\"color:#fff\">" + e(operator) + "</b>") if operator else "담당자 미선택"}'
            f'<a href="/whoami" onclick="this.href=\'/whoami?next=\'+encodeURIComponent(location.pathname+location.search)">{"바꾸기" if operator else "고르기"}</a>{h("whoami")}</span></nav>'
            f'<main>{fl}{body}{inline}</main>'
            f'<script>window.QA={json.dumps(qa, ensure_ascii=False).replace("</", "<\\/")}</script><script src="/static/hermes.js?v={HERMES_JS_VERSION}" defer></script><script src="/static/help.js?v={HELP_JS_VERSION}" defer></script><script src="/static/jobs.js?v={JOBS_JS_VERSION}" defer></script></body></html>')


# ---- 대시보드 ------------------------------------------------------------------------------
def tc_link(tid: str, label: str | None = None) -> str:
    from urllib.parse import quote
    return f'<a href="/catalog/tc?id={quote(tid, safe="")}" class="mono">{e(label or tid)}</a>'


def coverage_card(catalog, coverage: dict | None, error: str | None) -> str:
    if catalog is None or coverage is None:
        return f'<div class="card"><h3 style="margin-top:0">TC 커버리지</h3><p class="mut small">TC 목록 없음{(": " + e(error)) if error else ""}</p></div>'
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
                      f'{(" <span class=\"mut\">(자동화 제외 " + str(c["excluded"]) + ")</span>") if c["excluded"] else ""}</td>')
            for k in tot:
                tot[k] += c[k]
        rows += f'<tr><td><a href="/catalog?domain={e(d)}">{e(d)}</a></td>{cells}</tr>'
    v = catalog.versions
    return (f'<div class="card"><h3 style="margin-top:0">TC 커버리지{h("dash.coverage")} <span class="small mut">자동화됨 {tot["covered"]} / {tot["total"] - tot["excluded"]} (자동화 제외 {tot["excluded"]})</span></h3>'
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
               f'{"&pr=" + str(pr["number"]) if pr.get("number") else ""}">검증</a>{h("dash.verify")}')
        rows += (f'<tr><td class="mono"><a href="{e(d["url"])}">{e((d["sha"] or "")[:8])}</a></td>'
                 f'<td>{("<a href=\"" + e(pr["url"]) + "\">#" + str(pr["number"]) + "</a> ") if pr.get("number") else ""}{e(pr.get("title") or d.get("title"))}</td>'
                 f'<td class="small mut">{kst(d["at"])}</td><td>{state}</td><td class="right">{btn}</td></tr>')
    if not rows:
        rows = f'<tr><td colspan="5" class="mut">{"조회 실패: " + e(gh_error) if gh_error else "성공한 dev 배포가 없다"}</td></tr>'
    unverified = sum(1 for d in deploys if not d.get("runs"))

    s_state = ("이번 스프린트 smoke: " + " ".join(f'<a href="/runs/{e(r["id"])}">{run_badge(r)}</a>' for r in sprint_runs[:3])) if sprint_runs \
        else badge("이번 스프린트 smoke 미실행", "warn")
    sprint_card = (f'<div class="card"><h3 style="margin-top:0">스프린트 Cycle {sprint["number"]}{h("dash.sprint")} '
                   f'<span class="small mut">{sprint["starts_at"].astimezone(KST).strftime("%m-%d")} ~ {(sprint["ends_at"] - timedelta(days=1)).astimezone(KST).strftime("%m-%d")}</span></h3>'
                   f'<p>{s_state}</p><div class="actions"><a class="btn primary" href="/runs/new?trigger=sprint-smoke">스프린트 smoke 실행</a>{h("dash.sprint")}'
                   f'<a class="btn" href="/runs/new?trigger=release">릴리스 QA</a>{h("dash.release")}<a class="btn" href="/runs/new?trigger=manual">수동 실행</a>{h("dash.manual")}</div></div>')

    cfg_lines = (f'대상 <span class="mono">{e(cfg_summary["target"])}</span> · 스크립트 {case_count}개 · 테스트 계정 {", ".join(cfg_summary["actors"]) or "<b style=\"color:var(--warn)\">없음</b>"}'
                 f' · Hermes {"on" if cfg_summary["hermes"] else "off"} · Slack {"on" if cfg_summary["slack"] else "off"}'
                 f' · 러너 {("실행 중 " + e(runner_current)) if runner_current else "대기"}')
    errs = "".join(f'<li class="small" style="color:var(--bad)">{e(x)}</li>' for x in case_errors)
    status_card = f'<div class="card"><h3 style="margin-top:0">상태</h3><p class="small">{cfg_lines}</p>{("<ul>" + errs + "</ul>") if errs else ""}</div>'

    rec = "".join(
        f'<tr><td><a href="/runs/{e(r["id"])}" class="mono">{e(r["id"])}</a></td><td>{e(TRIGGER_KO.get(r["trigger"], r["trigger"]))}</td>'
        f'<td>{e(r["operator"])}</td><td class="mono small">{e((r.get("sha") or "")[:8])}{(" #" + str(r["pr_number"])) if r.get("pr_number") else ""}</td>'
        f'<td>{run_badge(r)} <span class="small mut">{r["passed"]}/{r["total"]}</span></td><td class="small mut">{kst(r["created_at"])}</td></tr>'
        for r in recent) or '<tr><td colspan="6" class="mut">아직 실행 기록이 없다</td></tr>'

    return (f'<h1>대시보드</h1><div class="grid">{sprint_card}{status_card}</div>{coverage_card(catalog, coverage, catalog_error)}'
            f'<h2>dev 배포 {badge(f"미검증 {unverified}", "warn" if unverified else "ok")}{h("dash.deploys")}</h2><div class="card">'
            f'<table><tr><th>SHA</th><th>PR</th><th>배포</th><th>검증</th><th></th></tr>{rows}</table>'
            f'<p class="small mut">GitHub Actions 의 성공한 dev 배포를 읽어 표시한다. 검증은 사람이 [검증] 을 눌러야 시작된다.</p></div>'
            f'<h2>최근 테스트 실행{h("runs.list")}</h2><div class="card"><table><tr><th>ID</th><th>실행 종류{h("runs.trigger")}</th><th>담당자</th><th>대상</th><th>결과{h("run.verdict")}</th><th>시각</th></tr>{rec}</table></div>')


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
            f'<p class="small mut" style="margin-bottom:0">선택 이유: {e(basis)}</p></div>'
            f'<div class="card"><h3 style="margin-top:0">담당자</h3><p><select name="operator" required><option value="">— 선택 —</option>{ops}</select>'
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
        f'<td class="small mut">{kst(r["created_at"])}</td></tr>' for r in runs) or '<tr><td colspan="7" class="mut">실행 기록이 없다</td></tr>'
    toggle = '<a href="/runs">API 직접 호출 숨기기</a>' if show_all else '<a href="/runs?all=1">API 직접 호출도 보기</a>'
    return f'<h1>테스트 실행{h("runs.list")} <span class="small mut">{toggle}</span></h1><div class="card"><table><tr><th>ID</th><th>실행 종류{h("runs.trigger")}</th><th>담당자</th><th>대상</th><th>결과</th><th>통과/실패/오류/skip</th><th>시각</th></tr>{rows}</table></div>'


def _checks_html(checks: list[dict]) -> str:
    if not checks:
        return ""
    return f'<div class="small mut">검증 항목{h("run.checks")}</div>' + "".join(
        f'<div class="small">{"✅" if c["ok"] else "❌"} {e(c["check"])}{(" <span class=\"mono\">" + e(c["path"]) + "</span>") if c.get("path") else ""}'
        f' 기대 <span class="mono">{e(json.dumps(c["expected"], ensure_ascii=False))}</span> 실제 <span class="mono">{e(json.dumps(c["actual"], ensure_ascii=False))}</span></div>'
        for c in checks)


def _donut(pct: float, label: str, size: int = 150) -> str:
    """통과율 도넛 — SVG 하나, JS 없음. stroke-dasharray 로 채운다."""
    r = 42
    circ = 2 * 3.14159265 * r
    filled = circ * max(0.0, min(1.0, pct / 100.0))
    color = "var(--ok)" if pct >= 80 else ("var(--warn)" if pct >= 50 else "var(--bad)")
    return (f'<svg viewBox="0 0 120 120" width="{size}" height="{size}" role="img" aria-label="통과율 {pct:.0f}%">'
            f'<circle cx="60" cy="60" r="{r}" fill="none" stroke="var(--graybg)" stroke-width="14"/>'
            f'<circle cx="60" cy="60" r="{r}" fill="none" stroke="{color}" stroke-width="14" stroke-dasharray="{filled:.2f} {circ:.2f}" stroke-linecap="butt" transform="rotate(-90 60 60)"/>'
            f'<text x="60" y="58" text-anchor="middle" font-size="22" font-weight="700" fill="var(--ink)">{pct:.0f}%</text>'
            f'<text x="60" y="76" text-anchor="middle" font-size="10" fill="var(--mut)">{e(label)}</text></svg>')


def run_summary(run: dict, cases: list[dict], domains_by_rc: dict[int, list[str]], *, f_verdict: str = "") -> str:
    """실행 결과 요약 (docs/qa-platform-api.md §5.7, Tossion 캡처): 요약 카드 4 · 통과율 도넛 · 도메인별 진행 막대 · 판정 필터."""
    total = len(cases)
    n = {k: sum(1 for c in cases if c["verdict"] == k) for k in ("pass", "fail", "error", "skipped", "queued", "running", "canceled")}
    done = total - n["queued"] - n["running"]
    bad = n["fail"] + n["error"]
    pct = (n["pass"] / total * 100) if total else 0.0
    live = run["status"] in ("queued", "running")
    stats = (f'<div class="stats"><div class="stat"><div class="l">전체 스크립트{h("run.summary")}</div><b>{total}</b><div class="s">{e(TRIGGER_KO.get(run["trigger"], run["trigger"]))}</div></div>'
             f'<div class="stat"><div class="l">실행 완료</div><b>{done}</b><div class="s">{(done * 100 // total) if total else 0}% 완료{" · 진행 중" if live else ""}</div></div>'
             f'<div class="stat ok"><div class="l">통과</div><b>{n["pass"]}</b><div class="s">{pct:.0f}% 통과율</div></div>'
             f'<div class="stat {"bad" if bad else ""}"><div class="l">실패 · 오류</div><b>{bad}</b><div class="s">skip {n["skipped"]}{(" · 취소 " + str(n["canceled"])) if n["canceled"] else ""}</div></div></div>')
    legend = "".join(f'<li><i style="background:{col}"></i> {lab} <span class="mut">{cnt}건 ({(cnt * 100 // total) if total else 0}%)</span></li>'
                     for lab, cnt, col in (("통과", n["pass"], "#16a34a"), ("실패 · 오류", bad, "#dc2626"), ("skip", n["skipped"], "#9ca3af"), ("대기 · 진행 중", n["queued"] + n["running"], "#f59e0b")) if cnt or lab == "통과")
    # 도메인별: 스크립트가 여러 도메인이면 각 도메인에 센다
    dom: dict[str, dict] = {}
    for c in cases:
        for d in (domains_by_rc.get(c["id"]) or ["(도메인 없음)"]):
            cell = dom.setdefault(d, {"p": 0, "f": 0, "s": 0, "r": 0, "t": 0})
            cell["t"] += 1
            cell["p" if c["verdict"] == "pass" else ("f" if c["verdict"] in ("fail", "error") else ("s" if c["verdict"] in ("skipped", "canceled") else "r"))] += 1
    def bar(cell):
        t = cell["t"] or 1
        return '<div class="bar">' + "".join(f'<i class="{k}" style="width:{cell[k] * 100 / t:.1f}%" title="{lab} {cell[k]}"></i>' for k, lab in (("p", "통과"), ("f", "실패·오류"), ("s", "skip"), ("r", "대기")) if cell[k]) + '</div>'
    doms = "".join(f'<div class="dom"><span>{e(d)} <span class="mut small">{cell["t"]}</span></span>{bar(cell)}<span class="small right">{cell["p"]}/{cell["t"]} 통과</span></div>'
                   for d, cell in sorted(dom.items(), key=lambda kv: (-kv[1]["t"], kv[0])))
    tabs = "".join(f'<a href="/runs/{e(run["id"])}{("?verdict=" + v) if v else ""}" class="{"on" if (f_verdict or "") == v else ""}">{lab} {cnt}</a>'
                   for v, lab, cnt in (("", "모두", total), ("pass", "통과", n["pass"]), ("fail", "실패 · 오류", bad), ("skipped", "skip", n["skipped"])))
    return (f'{stats}<div class="card"><div class="sumgrid"><div style="text-align:center">{_donut(pct, "통과율")}</div>'
            f'<div><ul class="legend">{legend}</ul><h4 style="margin:12px 0 4px">도메인별{h("run.domains")}</h4>{doms or "<p class=\"hint\">도메인 정보 없음</p>"}</div></div></div>'
            f'<h2>스크립트별 결과{h("run.steps")} <span class="small mut">판정으로 거르기{h("run.filter")}</span></h2><div class="tabs">{tabs}</div>')


def run_detail(run: dict, cases: list[dict], steps_by_case: dict[int, list[dict]], *, operators: list[str], operator: str,
               checklist: list[str], public_url: str, can_publish: bool = False, domains_by_rc: dict | None = None, f_verdict: str = "") -> str:
    live = run["status"] in ("queued", "running")
    refresh = '<meta http-equiv="refresh" content="4">' if live else ""
    meta = run.get("meta") or {}
    kv = {
        "실행 종류": e(TRIGGER_KO.get(run["trigger"], run["trigger"])), "담당자": e(run["operator"]),
        "대상": f'<span class="mono">{e(run["base_url"])}</span>',
        "SHA / PR": f'<span class="mono">{e(run.get("sha") or "–")}</span>' + (f' · <a href="{e(meta.get("pr_url"))}">#{run["pr_number"]}</a> {e(meta.get("pr_title") or "")}' if run.get("pr_number") else ""),
        "선택 이유": e(meta.get("basis") or "–"), "사유": e(meta.get("reason") or "–"),
        "TC 소스 버전": (f'SSOT <span class="mono">{e((meta.get("catalog") or {}).get("ssot") or "–")}</span> · OpenAPI <span class="mono">{e((meta.get("catalog") or {}).get("openapi") or "–")}</span>'
                   f' · 검증하는 TC {len(meta.get("covers") or [])}') if meta.get("catalog") else "–",
        "시각": f'{kst(run["created_at"])} 생성 · {kst(run.get("started_at"))} 시작 · {kst(run.get("finished_at"))} 종료',
        "결과": f'{run_badge(run)}{h("run.verdict")} 통과 {run["passed"]} · 실패 {run["failed"]} · 오류 {run["errored"]} · skip {run["skipped"]} / {run["total"]}',
    }
    kvh = "".join(f'<div>{k}</div><div>{v}</div>' for k, v in kv.items())
    cancel = (f'<form class="inline" method="post" action="/runs/{e(run["id"])}/cancel"><input type="hidden" name="operator" value="{e(operator)}">'
              f'<button class="danger" {"" if operator else "disabled title=\"담당자를 먼저 고르세요\""}>취소</button>{h("run.cancel")}</form>') if live else ""
    publish = ""
    if not live and run["trigger"] in ("sprint-smoke", "release", "deploy-sanity"):
        pub = meta.get("published")
        if pub:
            publish = f'<span class="small">위키에 게시됨 · <a href="{e(pub.get("url"))}" class="mono">{e(pub.get("slug"))}</a> · {e(pub.get("by"))} {kst(pub.get("at"))}</span> '
        dis = "" if (operator and can_publish) else ("disabled title=\"담당자를 먼저 고르세요\"" if can_publish else "disabled title=\"LLM_WIKI_MCP_* 미설정\"")
        publish += (f'<form class="inline" method="post" action="/runs/{e(run["id"])}/publish"><input type="hidden" name="operator" value="{e(operator)}">'
                    f'<button {dis}>{"다시 " if pub else ""}위키에 보고서 게시</button> <button name="dry" value="1" {dis}>dry-run</button>{h("run.publish")}</form>'
                    f'<span class="small mut">wiki/qa/ 에 generated 페이지로. 사람이 누를 때만 · UUID 마스킹</span>')

    body_cases = ""
    shown = [rc for rc in cases if not f_verdict or (rc["verdict"] in ("fail", "error") if f_verdict == "fail" else rc["verdict"] == f_verdict)]
    if not shown:
        body_cases = '<div class="card"><p class="mut" style="margin:0">해당 판정의 스크립트가 없다</p></div>'
    for rc in shown:
        steps = steps_by_case.get(rc["id"], [])
        st, given = "", ""
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
            if req.get("given"):         # 전제 카드(uses) 단계는 한데 접는다 (docs/qa-platform-scenarios.md §8.3)
                given, st = given + st, ""
        if given:
            gs = [s for s in steps if s["request"].get("given")]
            ok = all(s["verdict"] == "pass" for s in gs)
            st = (f'<details class="given" {"" if ok else "open"}><summary>{badge("pass" if ok else "error")} 전제 카드 '
                  f'<a href="/cases/{e(gs[0]["request"]["given"])}" class="mono">{e(gs[0]["request"]["given"])}</a> <span class="small mut">단계 {len(gs)}개{h("editor.uses")}</span></summary>'
                  f'<div style="padding-left:14px">{given}</div></details>') + st
        tri = ""
        if rc["verdict"] in ("fail", "error"):
            tri = (f'<form class="inline" method="post" action="/runs/{e(run["id"])}/triage" data-job-form><input type="hidden" name="run_case_id" value="{rc["id"]}">'
                   f'<input type="hidden" name="operator" value="{e(operator)}"><button {"" if operator else "disabled title=\"담당자를 먼저 고르세요\""}>Hermes 실패 분석</button>{h("run.triage")}</form>')
            if rc.get("triage"):
                tri += f'<div class="card" style="margin-top:8px;background:#f8fafc"><div class="small mut">Hermes 실패 분석 · {kst(rc.get("triaged_at"))}</div><pre style="background:#fff;color:var(--ink);border:1px solid var(--line)">{e(rc["triage"])}</pre></div>'
        body_cases += (f'<div class="card"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">{badge(rc["verdict"])} {badge(rc["case_suite"])} '
                       f'<a href="/cases/{e(rc["case_id"])}" class="mono">{e(rc["case_id"])}</a> <b>{e(rc["case_title"])}</b>'
                       f'<span class="small mut">{rc.get("duration_ms") or 0} ms · 스크립트 버전 {e(rc["case_hash"])}</span><span style="margin-left:auto">{tri}</span></div>'
                       f'{("<div class=\"small\" style=\"color:var(--bad);margin-top:4px\">" + e(rc.get("error")) + "</div>") if rc.get("error") and rc["verdict"] == "skipped" else ""}{st}</div>')

    release = ""
    if run["trigger"] == "release":
        dec = meta.get("release")
        if dec:
            done = "".join(f'<li>{"☑" if i in dec.get("checked", []) else "☐"} {e(i)}</li>' for i in dec.get("items", []))
            release = (f'<h2>릴리스 판단{h("run.release")}</h2><div class="card">{badge("GO" if dec["decision"] == "go" else "NO-GO", "ok" if dec["decision"] == "go" else "warn")} '
                       f'{e(dec["operator"])} · {kst(dec["at"])}<p>{e(dec.get("reason") or "")}</p><ul>{done}</ul></div>')
        else:
            items = "".join(f'<label class="chk"><input type="checkbox" name="checked" value="{e(i)}"> {e(i)}</label>' for i in checklist) or '<p class="mut">체크리스트를 가져오지 못했다 (backend docs/knowledge/release-checklist.md)</p>'
            ops = "".join(f'<option value="{e(o)}" {"selected" if o == operator else ""}>{e(o)}</option>' for o in operators)
            release = (f'<h2>릴리스 판단{h("run.release")}</h2><div class="card"><form method="post" action="/runs/{e(run["id"])}/decide">'
                       f'<p class="small mut">항목은 백엔드 <span class="mono">docs/knowledge/release-checklist.md</span> 에서 읽어 온다. 판단은 기록만 하고 승격을 막지 않는다 (설계 §13-5).</p>'
                       f'{items}<p><select name="decision"><option value="go">GO — 승격해도 된다</option><option value="no-go">NO-GO — 보류</option></select> '
                       f'<select name="operator" required><option value="">— 담당자 —</option>{ops}</select></p><p><textarea name="reason" placeholder="판단 사유"></textarea></p>'
                       f'<button class="primary" {"disabled" if live else ""}>판단 기록</button></form></div>')

    return (f'{refresh}<h1>테스트 실행 <span class="mono">{e(run["id"])}</span> {run_badge(run)} <a class="btn" href="/chat/new?run={e(run["id"])}">Hermes 와 이야기</a></h1>'
            f'<div class="card"><div class="kv">{kvh}</div><div class="actions">{cancel}{publish}<a class="btn" href="/api/runs/{e(run["id"])}">JSON</a>{h("run.json")}</div></div>'
            f'{release}{run_summary(run, cases, domains_by_rc or {}, f_verdict=f_verdict)}{body_cases}')


# ---- 통계 배지 (docs/qa-platform-api.md §5.5): 최근 N회 통과율 · 평균 소요 · 불안정(flaky) --------------------
FLAKY_WINDOW = 10      # 최근 몇 회 안에서
FLAKY_FLIPS = 2        # 통과↔실패가 몇 번 뒤집히면 불안정으로 보나


def stats_of(rows: list[dict], *, same_hash: bool = True) -> dict | None:
    """최신순 결과 목록 → {n, passed, failed, skipped, pass_rate(%|None), avg_ms|None, flaky(bool), flips}.
    통과율·평균은 pass·fail·error 만(skip 은 뺀다). 불안정은 최근 FLAKY_WINDOW 회 안에서 통과↔실패·오류가 FLAKY_FLIPS 번 이상 뒤집힐 때 —
    same_hash 면 가장 최근 것과 스크립트 해시가 같은 회차만 본다(스크립트를 고친 뒤 결과가 달라진 것은 불안정이 아니다)."""
    if not rows:
        return None
    judged = [r for r in rows if r["verdict"] in ("pass", "fail", "error")]
    passed = sum(1 for r in judged if r["verdict"] == "pass")
    durs = [r["duration_ms"] for r in judged if r.get("duration_ms") is not None]
    window = rows[:FLAKY_WINDOW]
    if same_hash and rows and rows[0].get("case_hash"):
        window = [r for r in window if r.get("case_hash") == rows[0]["case_hash"]]
    seq = ["p" if r["verdict"] == "pass" else "f" for r in window if r["verdict"] in ("pass", "fail", "error")]
    flips = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    return {"n": len(rows), "passed": passed, "failed": len(judged) - passed, "skipped": len(rows) - len(judged),
            "pass_rate": (round(passed * 100 / len(judged)) if judged else None),
            "avg_ms": (round(sum(durs) / len(durs)) if durs else None), "flaky": flips >= FLAKY_FLIPS, "flips": flips}


def stats_badge(st: dict | None, *, what: str = "실행") -> str:
    """한 줄 배지. 예: "최근 5회 통과율 80% · 평균 312 ms · 불안정"."""
    if not st:
        return '<span class="small mut">기록 없음</span>'
    rate = f'{st["pass_rate"]}%' if st["pass_rate"] is not None else "–"
    cls = "ok" if (st["pass_rate"] or 0) >= 80 else ("warn" if (st["pass_rate"] or 0) >= 50 else "none")
    out = (f'<span class="qab {cls}" title="최근 {st["n"]}회 중 통과 {st["passed"]} · 실패·오류 {st["failed"]} · skip {st["skipped"]} (skip 은 통과율에서 뺀다)">'
           f'최근 {st["n"]}회 통과율 {rate}</span>')
    if st["avg_ms"] is not None:
        out += f' <span class="small mut">평균 {st["avg_ms"]} ms</span>'
    if st["flaky"]:
        out += (f' <span class="b warn" title="결과가 오락가락한다: 스크립트를 안 고쳤는데 최근 {FLAKY_WINDOW}회 안에서 통과↔실패가 {st["flips"]}번 뒤집혔다. '
                f'dev 데이터·타이밍 문제일 수 있다">불안정 (flaky)</span>')
    return out


# ---- 케이스 --------------------------------------------------------------------------------------
def audit_badge(c, drift: list | None = None) -> str:
    st = c.audit.get("status", "unchecked")
    label = {"ok": "정합", "warn": "경고", "error": "불일치", "unchecked": "미검사"}[st]
    n = len(c.audit.get("errors") or []) + len(c.audit.get("warnings") or [])
    out = f'<span class="b {"pass" if st == "ok" else ("warn" if st == "warn" else ("fail" if st == "error" else "unchecked"))}" title="{e("; ".join((c.audit.get("errors") or []) + (c.audit.get("warnings") or [])))}">{label}{(" " + str(n)) if n and st != "ok" else ""}</span>'
    if drift:
        out += f' <span class="b drift" title="{e("; ".join(d["id"] + " " + d["kind"] + " " + d["at"] for d in drift))}">TC 변경 {len(drift)}</span>'
    return out


def cases_list(cases: list, last: dict[str, dict], errors: list[str], drift: dict | None = None, stats: dict | None = None,
               variants: dict | None = None, variant_errors: dict | None = None) -> str:
    """variants: 변형 id → 제목. 변형을 구현한 스크립트를 변형 순서로 먼저, variant: 없는 것은 "시나리오 밖" 으로 뒤에 모은다."""
    drift = drift or {}
    stats = stats or {}
    variants = variants or {}
    variant_errors = variant_errors or {}

    def vcell(c) -> str:
        if not c.variant:
            return ""
        bad = variant_errors.get(c.id)
        link = (f'<a href="{variant_url(c.variant)}" class="mono small">{e(c.variant)}</a>' if c.variant in variants else f'<span class="mono small">{e(c.variant)}</span>')
        return f'<div>{link}{(" <span class=\"b fail\" title=\"" + e("; ".join(bad)) + "\">없는 변형</span>") if bad else ""}</div>'

    def row(c) -> str:
        return (f'<tr><td><a href="/cases/{e(c.id)}" class="mono">{e(c.id)}</a>{vcell(c)}</td><td>{e(c.title)}</td><td>{badge(c.suite)}</td>'
                f'<td class="small">{e(", ".join(c.domains))}</td><td class="small">{e(c.actor or "–")}</td>'
                f'<td class="small">{len(c.covers)} {audit_badge(c, drift.get(c.id))}</td>'
                f'<td>{(("<a href=\"/runs/" + e(last[c.id]["run_id"]) + "\">" + badge(last[c.id]["verdict"]) + "</a> <span class=\"small mut\">" + kst(last[c.id]["created_at"]) + "</span>") if c.id in last else "<span class=\"mut small\">–</span>")}'
                f'<br>{stats_badge(stats.get(c.id)) if c.id in stats else ""}</td></tr>')
    order = {vid: i for i, vid in enumerate(variants)}          # 시나리오 파일 순서
    inside = sorted((c for c in cases if c.variant), key=lambda c: (order.get(c.variant, len(order)), c.variant, c.id))
    outside = [c for c in cases if not c.variant]
    rows = "".join(row(c) for c in inside)
    if inside and outside:
        rows += f'<tr><th colspan="7" style="padding-top:14px">시나리오 밖 {len(outside)}개{h("cases.variant")}</th></tr>'
    rows += "".join(row(c) for c in outside)
    errs = "".join(f'<li style="color:var(--bad)">{e(x)}</li>' for x in errors)
    blocked = [c.id for c in cases if c.blocked]
    return (f'<h1>테스트 스크립트{h("cases.list")} <span class="small mut">{len(cases)}개 · 원본은 git <span class="mono">qa-platform/cases/</span></span></h1>'
            f'{("<div class=\"flash err\"><b>로드 오류</b><ul>" + errs + "</ul></div>") if errs else ""}'
            f'{("<div class=\"flash err\"><b>TC 정합성 불일치</b> — covers 선언이 TC 목록와 맞지 않아 스위트에서 빠진 스크립트: " + e(", ".join(blocked)) + "</div>") if blocked else ""}'
            f'<div class="card"><table><tr><th>ID</th><th>제목</th><th>스위트{h("cases.suite")}</th><th>도메인</th><th>테스트 계정{h("x.actor")}</th><th>검증하는 TC{h("cases.covers")} · 정합성{h("cases.audit")}</th><th>마지막 결과 · 최근 통계{h("cases.last")}</th></tr>{rows}</table>'
            f'<p class="small mut">정합성 = covers 의 TC 가 TC 목록에 있고 단계의 method·path·기대 코드가 계약과 맞는지. TC 변경 = 검증하는 TC 가 마지막 검토(reviewed) 이후 바뀜. '
            f'최근 통계 = 최근 20회 통과율(skip 제외)·평균 소요. 불안정(flaky) = 스크립트를 안 고쳤는데 최근 {FLAKY_WINDOW}회 안에서 통과↔실패가 {FLAKY_FLIPS}번 이상 뒤집힘.</p>'
            f'<form method="post" action="/cases/reload" class="actions"><a class="btn primary" href="/cases/new">+ 새 스크립트 (폼)</a>{h("cases.new")} <a class="btn" href="/cases/new?suite=setup">+ 테스트 데이터 만들기 카드</a> <button>main 에서 다시 읽기</button>{h("cases.reload")}</form></div>')


def changes_card(changes: list[dict] | None) -> str:
    """스크립트·TC 화면의 최근 변경 — 누가 언제 무엇으로 저장했나, 커밋 링크. 되돌리기는 그 판을 보고 폼으로 다시 저장한다."""
    if not changes:
        return ""
    src = {"form": "폼", "form-edit": "폼", "form-delete": "삭제", "hermes": "Hermes", "hermes-revise": "Hermes 고침", "hermes-propose": "Hermes", "hermes-chat": "Hermes 대화", "explorer": "API 호출"}
    rows = "".join(
        f'<tr><td><a href="/drafts/{e(d["id"])}" class="mono">{e(d["id"])}</a></td><td>{e(src.get(d.get("source"), d.get("source") or ""))}</td><td>{e(d.get("decided_by") or d["operator"])}</td>'
        f'<td class="small mut">{kst(d.get("decided_at") or d["created_at"])}</td>'
        f'<td>{("<a class=\"mono\" href=\"" + e(d["commit_url"]) + "\" target=\"_blank\">" + e(d["commit_sha"][:8]) + "</a>") if d.get("commit_url") else "<span class=\"mut\">커밋 없음</span>"}</td>'
        f'<td class="small">{e(d.get("note") or "")}</td></tr>' for d in changes)
    return (f'<h2>최근 변경{h("case.changes")}</h2><div class="card"><table><tr><th>변경</th><th>어떻게</th><th>누가</th><th>언제</th><th>커밋</th><th>메모</th></tr>{rows}</table></div>')


def hermes_badge(raw: dict | None) -> str:
    return ' <span class="b warn" title="Hermes 가 쓰고 사람이 폼으로 아직 저장하지 않았다">Hermes 작성</span>' if (raw or {}).get("written_by") == "hermes" else ""


def case_detail(c, history: list[dict], tc_records: dict | None = None, drift: list | None = None, revise: dict | None = None, stats: dict | None = None,
                changes: list | None = None) -> str:
    tc_records = tc_records or {}
    revise_html = ""
    if drift and revise is not None:
        op = revise.get("operator") or ""
        ops = "".join(f'<option value="{e(o)}" {"selected" if o == op else ""}>{e(o)}</option>' for o in revise.get("operators") or [])
        dis = "" if (op and revise.get("hermes")) else ("disabled title=\"담당자를 먼저 고르세요\"" if revise.get("hermes") else "disabled title=\"HERMES_API_KEY 없음\"")
        revise_html = (f'<form method="post" action="/cases/{e(c.id)}/revise" class="actions" style="margin-top:10px" onsubmit="this.querySelector(\'button\').disabled=true">'
                       f'<input type="hidden" name="operator" value="{e(op)}"><button class="primary" {dis}>바뀐 TC 에 맞게 Hermes 가 고치기</button>{h("case.revise")}'
                       f'<select onchange="document.cookie=\'qa_operator=\'+this.value+\';path=/;max-age=31536000\';location.reload()"><option value="">— 담당자 —</option>{ops}</select>'
                       f'<span class="small mut">현재 YAML 과 바뀐 TC 의 전/후·새 PRD 절을 Hermes 에게 주고 바뀐 부분만 고치게 한다. 검증을 통과하면 같은 id 로 바로 저장되고 "Hermes 작성" 표시가 붙는다. 진행은 Hermes 작업 화면에서 실시간으로 보인다.</span></form>')
    changed = {d["id"]: d for d in (drift or [])}
    covers_html = "".join(
        f'<li>{tc_link(t)} {badge(r["layer"]) if r else "<span class=\"b fail\">TC 목록에 없음</span>"} {e(r["title"]) if r else ""}'
        f'{(" <span class=\"b drift\">" + e(changed[t]["kind"]) + " " + kst(changed[t]["at"]) + "</span>") if t in changed else ""}</li>'
        for t, r in ((t, tc_records.get(t)) for t in c.covers)) or '<li class="mut">검증하는 TC 없음 (manual 스위트만 허용)</li>'
    problems = "".join(f'<li style="color:var(--bad)">{e(x)}</li>' for x in c.audit.get("errors") or []) + \
        "".join(f'<li style="color:var(--warn)">{e(x)}</li>' for x in c.audit.get("warnings") or [])
    audit_html = (f'<div class="kv"><div>정합성</div><div>{audit_badge(c, drift)}{("<ul style=\"margin:4px 0 0;padding-left:18px\">" + problems + "</ul>") if problems else ""}</div>'
                  f'<div>검토</div><div>{(e(c.reviewed.get("by") or "–") + " · " + e(c.reviewed.get("at"))) if c.reviewed else "<span class=\"mut\">기록 없음 — 스크립트에 reviewed: {at, by} 를 적으면 그 이후 변경만 배지로 뜬다</span>"}</div></div>')
    hist = "".join(
        f'<tr><td><a href="/runs/{e(hr["run_id"])}" class="mono">{e(hr["run_id"])}</a></td><td>{badge(hr["verdict"])}</td><td>{e(TRIGGER_KO.get(hr["trigger"], hr["trigger"]))}</td>'
        f'<td>{e(hr["operator"])}</td><td class="mono small">{e((hr.get("sha") or "")[:8])}</td><td class="small mut">{kst(hr["created_at"])}</td>'
        f'<td class="small" style="color:var(--bad)">{e(hr.get("error") or "")}</td></tr>' for hr in history) or '<tr><td colspan="7" class="mut">실행 이력 없음</td></tr>'
    src = "".join(f'<li>{e(s)}</li>' for s in c.source) or '<li class="mut">출처 미기재</li>'
    op_ = (revise or {}).get("operator") or ""
    del_form = (f'<details class="card"><summary>이 스크립트 지우기{h("case.delete")}</summary><form method="post" action="/cases/{e(c.id)}/delete" class="actions" '
                f'onsubmit="return confirm(\'{e(c.id)} 를 지운다. main 의 {e(c.file)} 에서 바로 빠진다.\')">'
                f'<input type="hidden" name="operator" value="{e(op_)}"><input name="reason" placeholder="사유 (선택, 커밋 메시지에 남는다)" style="flex:1">'
                f'<button class="danger" {"" if op_ else "disabled title=\"담당자를 먼저 고르세요\""}>지우기</button></form>'
                f'<p class="small mut" style="margin:0">누르면 main 의 {e(c.file)} 에서 바로 빠진다. 이 스크립트만 검증하던 TC 는 미자동화가 된다. 되돌리려면 최근 변경의 커밋에서 그 판을 보고 새 스크립트로 저장한다.</p></details>')
    return (f'<h1><span class="mono">{e(c.id)}</span> {badge(c.suite)}{hermes_badge(c.raw)} <a class="btn" href="/chat/new?case={e(c.id)}">Hermes 와 이야기</a> <a class="btn" href="/cases/{e(c.id)}/edit">폼으로 고치기</a>{h("case.edit")}</h1><div class="card"><b>{e(c.title)}</b>'
            f'{("<p>" + e(c.description) + "</p>") if c.description else ""}'
            f'<div class="kv"><div>도메인</div><div>{e(", ".join(c.domains) or "–")}</div><div>operation</div><div class="mono">{e(", ".join(c.operations) or "–")}</div>'
            f'{("<div>변형</div><div><a class=\"mono\" href=\"" + variant_url(c.variant) + "\">" + e(c.variant) + "</a>" + h("cases.variant") + "</div>") if c.variant else ""}'
            f'<div>테스트 계정</div><div>{e(c.actor or "비로그인")}</div>'
            f'{("<div>전제 카드</div><div><a class=\"mono\" href=\"/cases/" + e(c.uses["setup"]) + "\">" + e(c.uses["setup"]) + "</a> <span class=\"small mut\">단계 " + str(len(c.steps) - len(c.own_steps)) + "개를 먼저 돈다</span>" + h("editor.uses") + "</div>") if c.uses else ""}'
            f'<div>출처 (PRD)</div><div><ul style="margin:0;padding-left:18px">{src}</ul></div><div>파일</div><div class="mono">{e(c.file)} · {e(c.hash)}</div></div></div>'
            f'<h2>검증하는 TC (covers){h("cases.covers")}{h("case.drift")}</h2><div class="card"><ul style="margin:0;padding-left:18px">{covers_html}</ul><div style="margin-top:10px">{audit_html}</div>{revise_html}</div>'
            f'<h2>정의{h("case.yaml")}</h2><pre>{e(c.to_yaml())}</pre>'
            f'<h2>실행 이력{h("case.history")} <span class="small mut">최근 통계: {stats_badge(stats) if stats else "기록 없음"}{h("cases.last")}</span></h2>'
            f'<div class="card"><table><tr><th>실행</th><th>결과</th><th>실행 종류</th><th>담당자</th><th>SHA</th><th>시각</th><th>오류</th></tr>{hist}</table></div>{changes_card(changes)}{del_form}')


# ---- 활동(감사 로그) ----------------------------------------------------------------------------
def activity(events: list[dict], operators: list[str], actions: list[str], f_op: str, f_act: str) -> str:
    rows = "".join(
        f'<tr><td class="small mut">{kst(ev["at"])}</td><td>{e(ev["operator"])}</td><td>{e(ACTION_KO.get(ev["action"], ev["action"]))}</td>'
        f'<td>{("<a href=\"/runs/" + e(ev["target"]) + "\" class=\"mono\">" + e(ev["target"]) + "</a>") if (ev.get("target") or "").startswith("r-") else e(ev.get("target") or "")}</td>'
        f'<td class="small mono">{e(json.dumps(ev["detail"], ensure_ascii=False)[:300])}</td><td class="small mut mono">{e(ev.get("session_hash") or "")} {e(ev.get("ip") or "")}</td></tr>'
        for ev in events) or '<tr><td colspan="6" class="mut">기록 없음</td></tr>'
    ops = "".join(f'<option value="{e(o)}" {"selected" if o == f_op else ""}>{e(o)}</option>' for o in operators)
    acts = "".join(f'<option value="{e(a)}" {"selected" if a == f_act else ""}>{e(ACTION_KO.get(a, a))}</option>' for a in actions)
    return (f'<h1>감사 로그{h("activity.filter")}</h1><form class="card" method="get"><select name="operator"><option value="">담당자 전체</option>{ops}</select> '
            f'<select name="action"><option value="">행위 전체</option>{acts}</select> <button>필터</button>'
            f' <span class="small mut">모든 사람 행위의 감사 로그. 담당자는 자기 신고, 세션 해시·IP 는 확인용.</span></form>'
            f'<div class="card"><table><tr><th>시각</th><th>담당자</th><th>행위</th><th>대상</th><th>상세</th><th>세션/IP</th></tr>{rows}</table></div>')


# ---- 기준 (TC 카탈로그) ---------------------------------------------------------------------------
LAYER_KO = {"policy": "비즈니스 규칙", "contract": "API 계약", "manual": "수동 작성"}


def catalog_list(catalog, coverage: dict, last: dict[str, dict], *, domain: str, layer: str, only: str,
                 changes: dict, wiki_available: bool, operators: list[str] | None = None, operator: str = "", hermes: bool = False,
                 op: str = "", op_ids: list[str] | None = None) -> str:
    by_tc = coverage["by_tc"]
    op_set = set(op_ids or []) if op else None
    tabs = "".join(f'<a href="/catalog?domain={e(d)}{("&layer=" + e(layer)) if layer else ""}{("&only=" + e(only)) if only else ""}" class="{"on" if d == domain else ""}">{e(d)}</a>'
                   for d in catalog.domains())
    ltabs = "".join(f'<a href="/catalog?domain={e(domain)}{("&layer=" + l) if l else ""}{("&only=" + e(only)) if only else ""}" class="{"on" if (layer or "") == l else ""}">{lab}</a>'
                    for l, lab in (("", "전체"), ("policy", "비즈니스 규칙(SSOT)"), ("contract", "API 계약(OpenAPI)"), ("manual", "수동 작성")))
    otabs = "".join(f'<a href="/catalog?domain={e(domain)}{("&layer=" + e(layer)) if layer else ""}{("&only=" + o) if o else ""}" class="{"on" if (only or "") == o else ""}">{lab}</a>'
                    for o, lab in (("", "모두"), ("uncovered", "미자동화만"), ("covered", "자동화만"), ("warn", "경고만")))
    rows = ""
    n = 0
    warn_ids = {w.split(":")[0] for w in catalog.warnings if ":" in w}
    for r in sorted(catalog.records.values(), key=lambda r: (r["layer"], r["id"])):
        if op_set is not None:
            if r["id"] not in op_set or (layer and r["layer"] != layer):
                continue
        elif r["domain"] != domain or (layer and r["layer"] != layer):
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
                 f'{(" <span class=\"b warn\" title=\"스펙 불일치 경고\">!</span>") if r["id"] in warn_ids else ""}'
                 f'{(" <span class=\"b drift\">" + e(ch["kind"]) + " " + kst(ch["at"]) + "</span>") if ch else ""}</td>'
                 f'<td class="small mono">{e(bind) or "<span class=\"mut\">API 없음</span>" if r["layer"] == "policy" else e(bind)}</td>'
                 f'<td>{badge({"covered": "자동화됨", "uncovered": "미자동화", "excluded": "자동화 제외"}[state], state)}'
                 f'{(" <span class=\"small mut\" title=\"" + e(r["excluded"]) + "\">" + e(r["excluded"][:40]) + ("…" if len(r["excluded"]) > 40 else "") + "</span>") if state == "excluded" else verdicts}</td></tr>')
    if not rows:
        rows = '<tr><td colspan="4" class="mut">해당 없음</td></tr>'
    warns = "".join(f'<li class="small">{e(w)}</li>' for w in catalog.warnings)
    c = catalog.counts()
    v = catalog.versions
    return (f'<h1>테스트 케이스 (TC) 목록{h("tc.layers")} <span class="small mut">{c["total"]}건 (비즈니스 규칙 {c["by_layer"].get("policy", 0)} · API 계약 {c["by_layer"].get("contract", 0)} · 수동 작성 {c["by_layer"].get("manual", 0)} · 자동화 제외 {c["excluded"]})</span></h1>'
            f'<div class="card"><p class="small mut" style="margin-top:0">원본은 llm-wiki 의 <span class="mono">상태-SSOT.yaml</span>(비즈니스 규칙)과 백엔드 OpenAPI(API 계약), 사람이 적은 <span class="mono">catalog/manual-tc.yaml</span>(수동 작성)이다. 플랫폼은 파생만 한다.'
            f' TC 소스 버전{h("tc.versions")}: SSOT <span class="mono">{e(v.get("ssot") or "–")}</span> · OpenAPI <span class="mono">{e(v.get("openapi") or "–")}</span> · 위키 HEAD <span class="mono">{e(v.get("wiki_head") or "–")}</span> · {kst(catalog.built_at)}'
            f'{"" if wiki_available else " · <b style=\"color:var(--warn)\">위키 체크아웃 없음 — 비즈니스 규칙 TC 없음</b>"} &nbsp; {refresh_form(operator=operator, next_url="/catalog?domain=" + domain, spec_hash=v.get("openapi"), fetched_ago=None)}</p>'
            f'{("<div class=\"flash ok\">API <span class=\"mono\">" + e(op) + "</span> 의 TC 만 보인다 (모든 도메인). <a href=\"/catalog\">전체 보기</a> · <a href=\"/explorer?op=" + e(op) + "\">호출해 보기</a></div>") if op_set is not None else ""}'
            f'<div class="tabs">{h("tc.filter")} {tabs}</div><div class="tabs">{ltabs}</div><div class="tabs">{otabs}</div></div>'
            f'{("<details class=\"card\"><summary>스펙 불일치 경고 " + str(len(catalog.warnings)) + " — API 매핑·OpenAPI 스펙이 서로 맞지 않는 항목" + h("tc.warnings") + "</summary><ul>" + warns + "</ul></details>") if catalog.warnings else ""}'
            f'<form method="post" action="/drafts/generate"><div class="card"><div class="actions" style="margin-top:0">'
            f'<select name="operator" required><option value="">— 담당자 —</option>{"".join(f"<option value=\"{e(o)}\" {"selected" if o == operator else ""}>{e(o)}</option>" for o in (operators or []))}</select>'
            f'<button class="primary" {"" if hermes else "disabled title=\"HERMES_API_KEY 없음\""}>고른 TC 로 Hermes 가 스크립트 쓰기</button>{h("tc.draft")}'
            f'<button formaction="/cases/new" formmethod="get">고른 TC 로 직접 쓰기 (폼)</button>{h("cases.new")}'
            f'<span class="small mut">같은 도메인 1~10건. 플랫폼이 TC·OpenAPI·PRD 절을 근거로 넣고, 검증을 통과한 것만 바로 저장되고 "Hermes 작성" 표시가 붙는다</span></div>'
            f'<table><tr><th>TC</th><th>내용 ({n})</th><th>API 매핑{h("tc.mapping")}</th><th>자동화 · 스크립트 · 마지막 결과{h("tc.state")}</th></tr>{rows}</table></div></form>'
            f'<form method="post" action="/catalog/propose-tc" class="card" onsubmit="this.querySelector(\'button\').disabled=true">'
            f'<h3 style="margin-top:0">PRD 절에서 수동 작성 TC 제안 (Hermes){h("tc.propose")}</h3>'
            f'<p class="small mut">SSOT 로 형식화되지 않아 자동으로 안 뽑힌 확인 항목을 PRD 절 본문에서 Hermes 가 골라낸다. 결과는 형식 검사를 거쳐 <span class="mono">catalog/manual-tc.yaml</span> 에 바로 저장되고 "Hermes 작성" 표시가 붙는다. 직접 적으려면 <a href="/catalog/manual/new">수동 작성 TC 추가 (폼)</a>{h("tc.manual_form")}.</p>'
            f'<p><input name="doc" placeholder="PRD 문서 이름 (예: 룸 탐색)" required style="width:220px"> <input name="section" placeholder="절 번호 (예: 4.2)" required style="width:120px"> '
            f'<input name="domain" placeholder="도메인 (선택, 예: room)" style="width:160px"> <input type="hidden" name="operator" value="{e(operator)}">'
            f'<button class="primary" {"" if (hermes and operator) else ("disabled title=\"담당자를 먼저 고르세요\"" if hermes else "disabled title=\"HERMES_API_KEY 없음\"")}>제안 받기</button></p></form>')


def catalog_detail(rec: dict, covering: list, last: dict[str, dict], excerpts: list, change: dict | None, *, source_link: str | None = None) -> str:
    expect = rec.get("expect_hint") or {}
    hint = "".join(f'<div>{e(k)}</div><div>{("<pre style=\"margin:0\">" + e(json.dumps(v, ensure_ascii=False, indent=1)) + "</pre>") if isinstance(v, (dict, list)) else e(v)}</div>'
                   for k, v in expect.items() if v not in (None, "", [], {}))
    b = rec.get("binding") or {}
    bind = ("op " + ", ".join(b.get("operations") or [])) if b.get("operations") else (("command " + ", ".join(b.get("commands") or [])) if b.get("commands") else "없음")
    if b.get("error_code"):
        bind += f' · 코드 {b["error_code"]}'
    prd_refs = {f'PRD/{p["doc"]} §{p["section"]}' for p in rec.get("prd") or []} | {f'PRD/{p["doc"]} {p["req"]}' for p in rec.get("prd") or [] if p.get("req")}
    src = "".join(f'<li>{e(s)}</li>' for s in rec.get("source") or [] if s not in prd_refs) or '<li class="mut">–</li>'
    # 요구 인용(R22)은 요구 id·절·문장까지 — PRD 의 그 줄이 바뀌면 SSOT 드리프트 검사가 이 TC 의 근거로 짚는다 (docs/policy-ssot-split.md §5.3)
    prd = "".join(
        (f'<li><a href="{e(p["url"])}">{e(p["doc"])} {e(p["req"])}</a> <span class="small mut">§{e(p.get("section") or "?")}</span>'
         f'{(" — " + e(p["text"])) if p.get("text") else " <span class=\"b fail\">PRD 에 없는 요구 id</span>"}</li>') if p.get("req") else
        f'<li><a href="{e(p["url"])}">{e(p["doc"])} §{e(p["section"])}</a></li>'
        for p in rec.get("prd") or [] if p.get("url"))
    ex_html = "".join(
        f'<details {"open" if i == 0 else ""}><summary>{e(ref["doc"])} §{e(ref["section"])}</summary><pre style="background:#fff;color:var(--ink);border:1px solid var(--line)">{e(text) if text else "(본문을 찾지 못했다 — 절 번호가 PRD 헤딩과 다르거나 위키 체크아웃이 없다)"}</pre></details>'
        for i, (ref, text) in enumerate(excerpts))
    cov = "".join(
        f'<tr><td><a href="/cases/{e(c.id)}" class="mono">{e(c.id)}</a></td><td>{e(c.title)}</td><td>{badge(c.suite)}</td>'
        f'<td>{(("<a href=\"/runs/" + e(last[c.id]["run_id"]) + "\">" + badge(last[c.id]["verdict"]) + "</a> <span class=\"small mut\">" + kst(last[c.id]["created_at"]) + "</span>") if c.id in last else "<span class=\"mut\">–</span>")}</td></tr>'
        for c in covering) or '<tr><td colspan="4" class="mut">이 TC 를 검증하는 스크립트 없음</td></tr>'
    state = "자동화 제외" if rec.get("excluded") else ("자동화됨" if covering else "미자동화")
    from urllib.parse import quote
    if rec["layer"] == "manual":
        edit_html = (f' <a class="btn" href="/catalog/tc/edit?id={quote(rec["id"], safe="")}">폼으로 고치기</a>{h("tc.manual_form")}')
        origin_html = ""
    else:
        edit_html = ""
        where = ("llm-wiki 의 <span class=\"mono\">wiki/policy/_src/상태-SSOT.yaml</span> (PRD 를 고치면 같은 작업에서 같이 고친다)" if rec["layer"] == "policy"
                 else "백엔드 OpenAPI (REST Docs 테스트가 만든다 — 백엔드 코드의 문서화 테스트를 고친다)")
        origin_html = (f'<div class="card small" style="background:#f8fafc">이 TC 는 {where} 에서 파생된다. 플랫폼에서 고치거나 지우지 않는다{h("tc.source_edit")}'
                       f'{(" · <a href=\"" + e(source_link) + "\">원본 보기</a>") if source_link else ""}. 자동화하지 않을 것이면 <span class="mono">catalog/exclusions.yaml</span> 에 사유와 함께 넣는다.</div>')
    new_script = f' <a class="btn" href="/cases/new?tc={quote(rec["id"], safe="")}">이 TC 로 스크립트 쓰기 (폼)</a>' if not rec.get("excluded") else ""
    return (f'<h1><span class="mono">{e(rec["id"])}</span> {badge(rec["layer"])} {badge(state, "excluded" if rec.get("excluded") else ("covered" if covering else "uncovered"))} <a class="btn" href="/chat/new?tc={e(rec["id"])}">Hermes 와 이야기</a>{edit_html}{new_script}{h("tc.detail")}{h("tc.state")}'
            f'{(" <span class=\"b drift\">" + e(change["kind"]) + " " + kst(change["at"]) + "</span>") if change else ""}</h1>'
            f'<div class="card"><b>{e(rec["title"])}</b>'
            f'{("<p class=\"small\" style=\"color:var(--mut)\">자동화 제외: " + e(rec["excluded"]) + "</p>") if rec.get("excluded") else ""}'
            f'<div class="kv"><div>도메인</div><div>{e(rec["domain"])}</div><div>종류</div><div>{e(rec.get("kind"))}{(" · actor " + e(rec["actor"])) if rec.get("actor") else ""}</div>'
            f'{("<div>게이트 (SSOT 검사 순서)</div><div class=\"mono\">" + e(rec["gate"]) + " " + e(rec.get("gate_name") or "") + "</div>") if rec.get("gate") else ""}'
            f'{("<div>command</div><div class=\"mono\">" + e(rec["command"]) + "</div>") if rec.get("command") else ""}'
            f'<div>API 매핑</div><div class="mono">{e(bind)}</div><div>출처</div><div><ul style="margin:0;padding-left:18px">{src}</ul></div>'
            f'{("<div>근거 PRD" + h("tc.req") + "</div><div><ul style=\"margin:0;padding-left:18px\">" + prd + "</ul></div>") if prd else ""}'
            f'<div>해시</div><div class="mono">{e(rec.get("hash"))}</div></div></div>'
            f'{origin_html}<h2>기대 결과</h2><div class="card"><div class="kv">{hint or "<div class=\"mut\">–</div><div></div>"}</div></div>'
            f'{("<h2>PRD 본문</h2><div class=\"card\">" + ex_html + "</div>") if excerpts else ""}'
            f'<h2>검증하는 스크립트</h2><div class="card"><table><tr><th>스크립트</th><th>제목</th><th>스위트</th><th>마지막 결과</th></tr>{cov}</table></div>')


# ---- 변경 기록 (예전 스크립트 초안) --------------------------------------------------------------------------------------
KIND_BADGE = {"tc": ("수동 TC 제안", "warn"), "case-delete": ("스크립트 삭제 요청", "fail"), "tc-delete": ("TC 삭제 요청", "fail")}


def drafts_list(drafts: list[dict], counts: dict, status: str, active_jobs: list | None = None) -> str:
    tabs = "".join(f'<a href="/drafts{("?status=" + st) if st else ""}" class="{"on" if (status or "") == st else ""}">{lab} {counts.get(st, "") if st else sum(counts.values())}</a>'
                   for st, lab in (("", "전체"), ("approved", "저장됨"), ("failed", "저장 실패"), ("draft", "저장 안 됨"), ("checked", "저장 안 됨 · 실행해 봄"), ("rejected", "버림")))
    rows = "".join(
        f'<tr><td><a href="/drafts/{e(d["id"])}" class="mono">{e(d["id"])}</a>{(" " + badge(*KIND_BADGE[d.get("kind")])) if d.get("kind") in KIND_BADGE else ""}</td><td>{badge(DRAFT_KO.get(d["status"], d["status"]), d["status"])}</td>'
        f'<td class="mono">{e(d.get("case_id") or "–")}</td><td class="small">{" ".join(tc_link(t) for t in d["tc_ids"][:4])}{" …" if len(d["tc_ids"]) > 4 else ""}</td>'
        f'<td class="small">{e((d.get("validation") or {}).get("status") or "–")}{(" · 경고 " + str(len((d.get("validation") or {}).get("warnings") or []))) if (d.get("validation") or {}).get("warnings") else ""}</td>'
        f'<td class="small">{e(d["source"])} · {e(d["operator"])}</td><td class="small mut">{kst(d["created_at"])}</td></tr>'
        for d in drafts) or '<tr><td colspan="7" class="mut">변경 없음 — 폼이나 Hermes 로 스크립트·수동 작성 TC 를 저장하면 여기에 쌓인다</td></tr>'
    return (f'<h1>변경 기록{h("drafts.status")} <span class="small mut">폼·Hermes 가 저장한 스크립트·수동 작성 TC 변경 — 누가 언제 무엇을 main 에 넣었나</span></h1>{active_jobs_line(active_jobs or [])}<div class="card"><div class="tabs">{tabs}</div>'
            f'<p class="small mut" style="margin-bottom:0">저장하면 검증을 거쳐 이 레포의 main 에 바로 커밋되고(<span class="mono">[skip ci]</span>, 재배포 없음) 플랫폼에 바로 반영된다. 초안·승인 단계는 없다. '
            f'"저장 안 됨" 은 예전 방식으로 남은 초안과 API 호출 화면에서 폼으로 담다 만 것이다. <a href="/jobs">Hermes 작업 목록</a></p></div>'
            f'<div class="card"><table><tr><th>ID</th><th>상태{h("drafts.status")}</th><th>스크립트 id</th><th>TC{h("cases.covers")}</th><th>검증</th><th>어떻게 · 누가</th><th>시각</th></tr>{rows}</table></div>')


def draft_detail(d: dict, tc_records: dict, run: dict | None, *, operators: list[str], operator: str, original_yaml: str | None = None,
                 repo_write: bool = False) -> str:
    v = d.get("validation") or {}
    diff_html = ""
    if original_yaml is not None:
        import difflib
        lines = list(difflib.unified_diff(original_yaml.splitlines(), (d["yaml"] or "").splitlines(), fromfile=f"cases/{d.get('case_id')} (현재)", tofile="저장할 판", lineterm="", n=2))
        body = "".join(f'<div style="color:{("var(--ok)" if l.startswith("+") and not l.startswith("+++") else ("var(--bad)" if l.startswith("-") and not l.startswith("---") else "var(--mut)"))}">{e(l)}</div>' for l in lines)
        diff_html = (f'<h2>원본 스크립트와의 차이{h("draft.diff")}</h2><div class="card"><p class="small mut" style="margin-top:0">{e(d.get("note") or "")}</p>'
                     f'<pre style="background:#fff;color:var(--ink);border:1px solid var(--line)">{body or "(차이 없음)"}</pre>'
                     f'<p class="small mut">저장하면 main 의 원본 항목이 이 YAML 로 바뀐다. reviewed 는 오늘 날짜·저장한 사람으로 올라간다.</p></div>')
    problems = "".join(f'<li style="color:var(--bad)">{e(x)}</li>' for x in v.get("errors") or []) + \
        "".join(f'<li style="color:var(--warn)">{e(x)}</li>' for x in v.get("warnings") or [])
    tcs = "".join(f'<li>{tc_link(t)} {badge(r["layer"]) if r else "<span class=\"b fail\">TC 목록에 없음</span>"} {e(r["title"]) if r else ""}</li>'
                  for t, r in tc_records.items()) or '<li class="mut">–</li>'
    ops = "".join(f'<option value="{e(o)}" {"selected" if o == operator else ""}>{e(o)}</option>' for o in operators)
    decided = d["status"] in ("approved", "rejected")
    run_html = ""
    if run:
        run_html = f'<p>시험 실행: <a href="/runs/{e(run["id"])}" class="mono">{e(run["id"])}</a> {run_badge(run)} <span class="small mut">통과 {run["passed"]} 실패 {run["failed"]} 오류 {run["errored"]} skip {run["skipped"]}</span></p>'
    dis = "disabled" if not operator else ""
    kind = d.get("kind") or "case"
    is_tc = kind == "tc"
    is_delete = kind.endswith("-delete")
    commit_hint = ("예전 방식으로 남은 초안이다. 저장하면 main 에 바로 커밋되고 실행 스위트에 바로 들어간다" if repo_write else "쓰기 토큰(QA_REPO_TOKEN)이 없어 저장 뒤 파일을 받아 직접 커밋한다")
    check_form = "" if (is_tc or is_delete) else (
        f'<form class="inline" method="post" action="/drafts/{e(d["id"])}/check"><input type="hidden" name="operator" value="{e(operator)}"><button {dis} {"disabled" if v.get("errors") else ""}>한 번 실행해 보기 (dev)</button>{h("draft.check")}</form>')
    edit_form = "" if is_delete else (
        (f'<div class="actions"><a class="btn primary" href="/drafts/{e(d["id"])}/edit">폼으로 고치기</a>{h("draft.form")} <span class="small mut">또는 아래 YAML 을 직접 고친다</span></div>' if kind == "case" else "")
        + f'<form method="post" action="/drafts/{e(d["id"])}/save"><input type="hidden" name="operator" value="{e(operator)}">'
        f'<div class="small mut">YAML 편집{h("draft.edit")}</div><textarea name="yaml" style="min-height:320px;font-family:ui-monospace,Menlo,monospace;font-size:12px">{e(d["yaml"])}</textarea>'
        f'<div class="actions"><button {dis}>저장하고 다시 검증</button></div></form>')
    forms = "" if decided else (
        f'{edit_form}<p class="small mut" style="margin-bottom:0">{e(commit_hint)}</p>'
        f'<div class="actions">'
        f'{check_form}'
        f'<form class="inline" method="post" action="/drafts/{e(d["id"])}/approve"><input type="hidden" name="operator" value="{e(operator)}"><input name="note" placeholder="메모 (선택)"> <button class="primary" {dis} {"disabled" if v.get("errors") else ""}>저장</button>{h("draft.approve")}</form>'
        f'<form class="inline" method="post" action="/drafts/{e(d["id"])}/reject"><input type="hidden" name="operator" value="{e(operator)}"><input name="note" placeholder="버리는 이유"> <button class="danger" {dis}>버리기</button></form>'
        f'</div><p class="small mut">담당자: <select onchange="document.cookie=\'qa_operator=\'+this.value+\';path=/;max-age=31536000\';location.reload()"><option value="">— 선택 —</option>{ops}</select> (버튼은 담당자를 고른 뒤 활성화된다)</p>')
    approved_html = ""
    if d["status"] == "approved":
        if d.get("commit_sha"):
            done = (f'<p class="small">main 에 커밋됨: <a href="{e(d.get("commit_url") or "")}" class="mono">{e((d["commit_sha"] or "")[:10])}</a> · '
                    f'<span class="mono">qa-platform/{e(d.get("file") or "")}</span> · 플랫폼에 바로 반영됨</p>')
        else:
            done = (f'<p class="small">쓰기 토큰이 없어 커밋하지 않았다. <a class="btn" href="/drafts/{e(d["id"])}/file">반영된 파일 받기</a> 로 받은 파일을 '
                    f'<span class="mono">qa-platform/</span> 아래 같은 경로에 덮어써 커밋한다{h("draft.approve")}</p>')
        approved_html = (f'<div class="card" style="background:#f0fdf4"><b>저장됨</b> · {e(d.get("decided_by"))} · {kst(d.get("decided_at"))}{(" · " + e(d.get("note"))) if d.get("note") and not is_delete else ""}'
                         + done + f'<pre id="y">{e(d["yaml"])}</pre><button onclick="navigator.clipboard.writeText(document.getElementById(\'y\').innerText)">복사</button></div>')
    elif d["status"] == "rejected":
        approved_html = f'<div class="card" style="background:#fef2f2"><b>버림</b> · {e(d.get("decided_by"))} · {kst(d.get("decided_at"))}{(" · " + e(d.get("note"))) if d.get("note") else ""}<pre>{e(d["yaml"])}</pre></div>'
    kind_html = (' <span class="b warn">수동 작성 TC</span> <span class="small mut">TC 목록(manual-tc.yaml)의 항목 — 스크립트가 아니라 실행하지 않는다</span>' if is_tc else
                 (f' <span class="b fail">{"스크립트" if kind == "case-delete" else "TC"} 삭제</span>{h("draft.delete")}' if is_delete else ""))
    if is_delete:
        kind_html += f'<div class="card" style="margin-top:10px;background:#fef2f2"><b>사유</b> {e(d.get("note") or "–")}<p class="small mut" style="margin:4px 0 0">아래 항목을 main 의 파일에서 뺐다.</p></div>'
    if d["status"] == "failed":
        kind_html += f'<div class="card" style="margin-top:10px;background:#fef2f2"><b>저장 실패</b> {e(d.get("note") or "")}<p class="small mut" style="margin:4px 0 0">[스크립트 다시 읽기] 로 main 을 받은 뒤 다시 저장한다.</p></div>'
    return (f'<h1>변경 <span class="mono">{e(d["id"])}</span> {badge(DRAFT_KO.get(d["status"], d["status"]), d["status"])}{kind_html}</h1>'
            f'<div class="card"><div class="kv"><div>스크립트 id</div><div class="mono">{e(d.get("case_id") or "–")}</div><div>출처</div><div>{e(d["source"])} · {e(d["operator"])} · {kst(d["created_at"])}'
            f'{(" · 프롬프트 해시 <span class=\"mono\">" + e(d.get("prompt_hash")) + "</span>") if d.get("prompt_hash") else ""}</div>'
            f'<div>검증하는 TC</div><div><ul style="margin:0;padding-left:18px">{tcs}</ul></div>'
            f'<div>검증</div><div>{badge({"ok": "OK", "warn": "경고", "error": "오류"}.get(v.get("status"), v.get("status") or "–"), {"ok": "pass", "warn": "warn", "error": "fail"}.get(v.get("status"), ""))}'
            f'{("<ul style=\"margin:4px 0 0;padding-left:18px\">" + problems + "</ul>") if problems else ""}</div></div>{run_html}</div>'
            f'{diff_html}{approved_html}{forms}')


# ---- 탐색기 (Swagger 모드) ------------------------------------------------------------------------
def method_badge(m: str) -> str:
    return f'<span class="m {e((m or "").lower())}">{e((m or "").upper())}</span>'


def _fmt_json(v) -> str:
    return json.dumps(v, ensure_ascii=False, indent=1)


def _path_param_values(template: str, path: str) -> dict:
    """실행 기록의 채워진 경로에서 path 파라미터 값을 되찾는다 (/v1/rooms/{roomId} + /v1/rooms/abc → {roomId: abc})."""
    out = {}
    t = [s for s in (template or "").split("?")[0].split("/") if s]
    p = [s for s in (path or "").split("?")[0].split("/") if s]
    if len(t) != len(p):
        return out
    for a, b in zip(t, p):
        if a.startswith("{") and a.endswith("}"):
            out[a[1:-1]] = b
    return out


def qa_badge(qa: dict | None, op_id: str) -> str:
    """호출 카드 머리의 검증 상태 한 줄 — "TC 5 · 자동화 3/5 · 마지막 pass 09-21". 클릭하면 그 API 의 TC 목록."""
    if qa is None:
        return '<span class="qab none" title="TC 목록을 만들지 못했다">TC 목록 없음</span>'
    if not qa["tc"]:
        return f'<a class="qab none" href="/apis/{e(op_id)}" title="이 API 에 해당하는 TC 가 없다 — OpenAPI 응답 예시·API 매핑을 확인">TC 없음</a>'
    denom = qa["tc"] - qa["excluded"]
    cls = "ok" if denom and qa["covered"] == denom else ("warn" if qa["uncovered"] else "none")
    last = qa.get("last")
    tail = f' · 마지막 {badge(last["verdict"])} <span class="small">{kst(last["created_at"])}</span>' if last else " · 실행 기록 없음"
    ex = f' (제외 {qa["excluded"]})' if qa["excluded"] else ""
    return (f'<a class="qab {cls}" href="/apis/{e(op_id)}" title="{e(", ".join(qa["ids"]))}">TC {qa["tc"]} · 자동화됨 {qa["covered"]}/{denom}{ex}{tail}</a>')


EXPLORER_JS = r"""
(function(){
  var F=document.getElementById('callf'); var LS=window.localStorage;
  var OP=(window.QA&&window.QA.operator)||''; var SFX=OP?(':'+OP):'';   // 담당자별로 따로 저장 (사용자 요청: 즐겨찾기·최근 값을 사람별로)
  function ls(k,d){try{var v=LS.getItem(k);return v==null?d:JSON.parse(v)}catch(e){return d}}
  function lsset(k,v){try{LS.setItem(k,JSON.stringify(v))}catch(e){}}
  // ---- 즐겨찾기 (브라우저·담당자별) ----
  var favs=ls('qa_fav'+SFX,[]); var favbox=document.getElementById('favbox');
  function renderFavs(){
    if(!favbox) return; favbox.innerHTML='';
    var n=0; favs.forEach(function(id){var it=document.querySelector('.opi[data-op="'+id+'"]'); if(!it) return; n++; favbox.appendChild(it.cloneNode(true));});
    var fn=document.getElementById('favn'); if(fn) fn.textContent=n?('('+n+')'):'';
    var fd=document.getElementById('favs'); if(fd) fd.style.display=n?'':'none';
    document.querySelectorAll('.star').forEach(function(b){b.textContent=favs.indexOf(b.dataset.op)>=0?'★':'☆'; b.classList.toggle('on',favs.indexOf(b.dataset.op)>=0)});
    favbox.querySelectorAll('.star').forEach(bindStar);
  }
  function bindStar(b){b.addEventListener('click',function(ev){ev.preventDefault(); var id=b.dataset.op; var i=favs.indexOf(id); if(i>=0) favs.splice(i,1); else favs.unshift(id); lsset('qa_fav'+SFX,favs); renderFavs();});}
  document.querySelectorAll('.opl .star').forEach(bindStar); renderFavs();
  if(!F) return;
  // ---- Normal | Swagger 보기 (같은 값을 두 모양으로) ----
  var nv=document.getElementById('nv'), sv=document.getElementById('sv'), seg=document.getElementById('seg');
  function setView(v){ nv.hidden=(v!=='normal'); sv.hidden=(v!=='swagger'); seg.querySelectorAll('button').forEach(function(b){b.classList.toggle('on',b.dataset.v===v)}); lsset('qa_view',v); }
  seg.addEventListener('click',function(ev){var b=ev.target.closest('button[data-v]'); if(b) setView(b.dataset.v)});
  setView(F.dataset.view||ls('qa_view','normal'));
  // ---- 파라미터: Normal 의 진짜 입력칸(name=p_·q_) ↔ Swagger 표의 거울 칸(data-mirror) ----
  function pathLive(){ var t=F.dataset.path; F.querySelectorAll('input[name^="p_"]').forEach(function(i){ t=t.split('{'+i.name.slice(2)+'}').join(i.value||('{'+i.name.slice(2)+'}')); }); document.querySelectorAll('.pathv').forEach(function(x){x.textContent=t}); }
  F.querySelectorAll('[data-mirror]').forEach(function(m){ var real=F.querySelector('[name="'+m.dataset.mirror+'"]'); if(!real) return; m.value=real.value;
    m.addEventListener('input',function(){real.value=m.value; pathLive()}); real.addEventListener('input',function(){m.value=real.value; pathLive()}); });
  pathLive();
  // ---- 본문: Swagger 의 JSON 칸(name=body)이 정본, Normal 의 키별 칸(data-bk)은 그 키만 ----
  var bodyt=F.querySelector('textarea[name="body"]'); var msg=document.getElementById('nvmsg');
  function parseBody(){ var t=(bodyt.value||'').trim(); if(!t) return {}; return JSON.parse(t); }
  function coerce(raw,type){ if(type==='number'){ var n=Number(raw); return raw.trim()!==''&&!isNaN(n)?n:raw } if(type==='boolean'){ if(raw==='true') return true; if(raw==='false') return false; return raw } if(type==='null'&&raw==='') return null; return raw; }
  function toNormal(){ if(!bodyt) return; var o; try{o=parseBody(); nv.classList.remove('bad'); if(msg) msg.textContent='';}catch(err){ nv.classList.add('bad'); if(msg) msg.textContent='Swagger 보기의 JSON 이 깨져 있다: '+err.message+' — 고치면 다시 열린다'; return; }
    F.querySelectorAll('[data-bk]').forEach(function(f){ var k=f.dataset.bk; var v=o&&Object.prototype.hasOwnProperty.call(o,k)?o[k]:undefined; f.disabled=false;
      if(f.dataset.kind==='json'){ f.value=v===undefined?'':JSON.stringify(v,null,1); } else { f.value=(v===undefined||v===null)?'':String(v); } }); }
  function fromNormal(f){ if(!bodyt) return; var o; try{o=parseBody()}catch(err){o={}} if(o===null||typeof o!=='object'||Array.isArray(o)) o={}; var k=f.dataset.bk;
    if(f.dataset.kind==='json'){ if(f.value.trim()==='') { delete o[k]; f.classList.remove('bad'); } else { try{o[k]=JSON.parse(f.value); f.classList.remove('bad');}catch(err){ f.classList.add('bad'); return; } } }
    else { o[k]=coerce(f.value,f.dataset.type||'string'); }
    bodyt.value=JSON.stringify(o,null,1); }
  F.querySelectorAll('[data-bk]').forEach(function(f){ f.addEventListener('input',function(){fromNormal(f)}); });
  if(bodyt){ bodyt.addEventListener('input',toNormal); if(F.querySelector('[data-bk]')) toNormal(); }
  // ---- 최근 값 (파라미터 이름별, 브라우저에만) ----
  function recentKey(n){return 'qa_recent'+SFX+'.'+n}
  F.querySelectorAll('input[name^="p_"],input[name^="q_"]').forEach(function(i){ var n=i.name.slice(2); var vals=ls(recentKey(n),[]); if(!vals.length) return;
    var dl=document.createElement('datalist'); dl.id='dl_'+n; vals.forEach(function(v){var o=document.createElement('option'); o.value=v; dl.appendChild(o)}); F.appendChild(dl); i.setAttribute('list',dl.id);
    if(!i.value&&i.dataset.autofill!=='0'){ i.value=vals[0]; i.dispatchEvent(new Event('input')); } });
  function remember(n,v){ if(!v) return; var vals=ls(recentKey(n),[]).filter(function(x){return x!==v}); vals.unshift(v); lsset(recentKey(n),vals.slice(0,5)); }
  F.addEventListener('submit',function(){ F.querySelectorAll('input[name^="p_"],input[name^="q_"]').forEach(function(i){remember(i.name.slice(2),i.value.trim())}); var b=F.querySelector('button.primary'); if(b){b.disabled=true;b.textContent='보내는 중…'} });
  // ---- 응답에서 id 자동 수집 → 다음 호출의 최근 값 ----
  var R=window.XRESP; var saved=[]; 
  (function walk(o,d){ if(!o||typeof o!=='object'||d>3) return; Object.keys(o).forEach(function(k){ var v=o[k]; if((/Id$/.test(k)||k==='id')&&(typeof v==='string'||typeof v==='number')){ remember(k,String(v)); saved.push(k+'='+v); } else if(v&&typeof v==='object') walk(v,d+1); }); })(R&&R.data,0);
  var sb=document.getElementById('saved'); if(sb&&saved.length) sb.textContent='응답에서 뽑아 기억한 id (다음 입력칸에 최근에 넣은 값으로 뜬다, 이 브라우저에만): '+saved.join(' · ');
})();
"""


def explorer(spec, op, run: dict | None, steps: list[dict], *, actors: list[str], operators: list[str], operator: str, q: str,
             domain_of=None, qa: dict | None = None, prefill: dict | None = None, spec_hash: str | None = None, fetched_ago: int | None = None) -> str:
    """API 호출 화면 — 왼쪽 op 목록(도메인별·검색·즐겨찾기), 오른쪽 호출 카드(Normal 폼 | Swagger 요청 원문). docs/qa-platform-api.md §5.3·§5.6."""
    ql = (q or "").lower()
    pf = prefill or {}
    groups: dict[str, list] = {}
    for o in sorted(spec.ops.values(), key=lambda o: (o.path, o.method)):
        if not (o.path.startswith("/v1/") or o.path.startswith("/actuator")):
            continue
        if ql and ql not in (o.id + o.path + o.summary).lower():
            continue
        groups.setdefault(domain_of(o.path) if domain_of else "all", []).append(o)
    cur_dom = domain_of(op.path) if (op and domain_of) else None

    def item(o) -> str:
        on = " on" if op and o.id == op.id else ""
        return (f'<div class="opi{on}" data-op="{e(o.id)}"><button type="button" class="star" data-op="{e(o.id)}" title="즐겨찾기">☆</button>'
                f'<a href="/explorer?op={e(o.id)}{("&q=" + e(q)) if q else ""}">{method_badge(o.method)} <span class="mono">{e(o.path)}</span></a>'
                f'<span class="small mut">{e(o.summary)}</span></div>')
    lists = "".join(
        f'<details {"open" if (ql or d == cur_dom) else ""}><summary>{e(d)} <span class="mut small">{len(os_)}</span></summary>{"".join(item(o) for o in os_)}</details>'
        for d, os_ in groups.items()) or '<span class="mut">없음</span>'
    left = (f'<div class="card opl"><form method="get"><input name="q" value="{e(q)}" placeholder="검색 (operationId · 경로 · 요약)" style="width:100%"></form>'
            f'<p class="hint" style="margin:6px 0 0">☆ 즐겨찾기{h("x.fav")} · 한 번 넣은 값은 기억된다{h("x.recent")}</p>'
            f'<details id="favs" open style="display:none"><summary>즐겨찾기 <span id="favn" class="mut small"></span>{h("x.fav")}</summary><div id="favbox"></div></details>'
            f'<div class="oplist">{lists}</div></div>')
    head = ('<h1>API 호출' + h("x.views") + ' <span class="small mut">OpenAPI 로 만든 입력 폼에서 dev 에 요청 하나를 보내 본다. '
            'Normal 은 값만 넣는 폼, Swagger 는 실제로 나갈 요청 원문(메서드·경로·파라미터·JSON) — 둘은 같은 값이다. 보낸 것은 실행 기록에 남는다</span></h1>'
            + f'<p class="small mut" style="margin:-6px 0 10px">OpenAPI(dev 브랜치) <span class="mono">{e(spec_hash or "–")}</span> &nbsp; {refresh_form(operator=operator, next_url="/explorer" + (("?op=" + op.id) if op else ""), spec_hash=spec_hash, fetched_ago=fetched_ago)}</p>')
    if not op:
        right = ('<div class="card"><p class="mut" style="margin:0">왼쪽에서 API 를 고르면 카드가 열린다. ☆ 로 즐겨찾기에 올릴 수 있고, '
                 '한 번 넣은 path·query 값은 이 브라우저에 기억돼 다음 입력칸에 뜬다.</p></div>')
        return f'{head}<div class="xgrid">{left}{right}</div><script>{EXPLORER_JS}</script>'

    # ---- 카드: 값의 정본은 하나 — path·query 는 Normal 의 입력칸(name=p_·q_), 본문은 Swagger 의 JSON 칸(name=body) ----
    pparams = [x for x in op.params if x["in"] == "path"]
    qparams = [x for x in op.params if x["in"] == "query"]
    pv = pf.get("p") or {}
    qv = pf.get("q") or {}
    has_body = op.method in ("POST", "PUT", "PATCH")
    body_obj = op.request_example if has_body else None
    body_text = ""
    if has_body:
        if pf.get("body"):
            body_text = pf["body"]
            try:
                body_obj = json.loads(body_text)
            except ValueError:
                pass   # 깨진 프리필은 그대로 보여 주고 JS 가 Normal 을 잠근다
        elif op.request_example is not None:
            body_text = _fmt_json(op.request_example)

    def field(label: str, inner: str, *, required: bool = False, hint: str = "") -> str:
        return (f'<div class="field"><label>{e(label)}{"<i class=\"req\" title=\"필수\"></i>" if required else ""}'
                f'{(" <span class=\"hint\">" + e(hint) + "</span>") if hint else ""}</label>{inner}</div>')
    normal = "".join(field(x["name"], f'<input name="p_{e(x["name"])}" value="{e(pv.get(x["name"], ""))}" {"required" if x["required"] else ""} autocomplete="off">',
                           required=x["required"], hint=x["description"] or "path") for x in pparams)
    normal += "".join(field(x["name"], f'<input name="q_{e(x["name"])}" value="{e(qv.get(x["name"], ""))}" {"required" if x["required"] else ""} autocomplete="off">',
                            required=x["required"], hint=x["description"] or "query") for x in qparams)
    if has_body:
        if isinstance(body_obj, dict) and body_obj:
            for k, v in body_obj.items():
                if isinstance(v, (dict, list)):
                    normal += field(k, f'<textarea data-bk="{e(k)}" data-kind="json" rows="3">{e(_fmt_json(v))}</textarea>', hint="JSON")
                else:
                    t = "number" if isinstance(v, (int, float)) and not isinstance(v, bool) else ("boolean" if isinstance(v, bool) else ("null" if v is None else "string"))
                    normal += field(k, f'<input data-bk="{e(k)}" data-kind="scalar" data-type="{t}" value="{e("" if v is None else v)}" autocomplete="off">', hint=t if t != "string" else "")
            normal += '<p class="hint">본문 키는 OpenAPI 요청 예시에서 왔다. 예시에 없는 키를 넣으려면 Swagger 보기에서 JSON 을 고친다. 만드는 데이터의 title 은 [QA] 로</p>'
        else:
            normal += '<p class="hint">이 API 의 본문은 Swagger 보기에서 JSON 으로 넣는다 (예시가 객체가 아니다)</p>'
    if not normal:
        normal = '<p class="hint">넣을 값이 없다 — 그대로 보내면 된다</p>'
    normal += '<p id="nvmsg" class="hint bad"></p>'

    prow = "".join(f'<tr><td class="mono">{e(x["name"])}{"<i class=\"req\"></i>" if x["required"] else ""}</td><td class="mut small">{e(x["in"])}</td>'
                   f'<td><input data-mirror="{"p_" if x["in"] == "path" else "q_"}{e(x["name"])}" autocomplete="off"></td></tr>' for x in pparams + qparams)
    swagger = (f'<div class="sline">{method_badge(op.method)} <span class="mono pathv">{e(op.path)}</span></div>'
               f'<h4>Parameters</h4>' + (f'<table class="params"><tr><th>Name</th><th>In</th><th>Value</th></tr>{prow}</table>' if prow else '<p class="hint">없음</p>'))
    if has_body:
        swagger += (f'<h4>Request Body</h4><textarea name="body" rows="12" class="mono">{e(body_text)}</textarea>'
                    f'<p class="hint">💡 OpenAPI 요청 예시로 채웠다. 여기 JSON 이 실제로 나가는 본문이다 — Normal 보기의 칸은 이것을 키별로 보여 준 것</p>')
    errs = "".join(f'<li><span class="mono">{e(code)}</span> {e(i.get("status"))} {e(i.get("message"))}</li>' for code, i in op.errors.items()) or "<li class='mut'>문서화된 에러 없음</li>"
    sel_actor = pf.get("actor") or ""
    acts = f'<label class="radio"><input type="radio" name="actor" value="" {"checked" if not sel_actor else ""}> 비로그인</label>' + "".join(
        f'<label class="radio"><input type="radio" name="actor" value="{e(a)}" {"checked" if a == sel_actor else ""}> {e(a)}</label>' for a in actors)
    ops = "".join(f'<option value="{e(o)}" {"selected" if o == operator else ""}>{e(o)}</option>' for o in operators)
    view = pf.get("view") if pf.get("view") in ("normal", "swagger") else ""
    card = (f'<form method="post" action="/explorer/send" id="callf" class="card call" data-path="{e(op.path)}" data-view="{e(view)}">'
            f'<input type="hidden" name="op" value="{e(op.id)}">'
            f'<div class="callhead"><div><b>{e(op.summary or op.id)}</b> <span class="mono mut small">{e(op.id)}</span><br>{method_badge(op.method)} <span class="mono pathv">{e(op.path)}</span></div>'
            f'<div class="seg" id="seg"><button type="button" data-v="normal" title="값만 넣는 입력 폼">Normal</button><button type="button" data-v="swagger" title="실제로 나가는 요청 원문 (메서드·경로·파라미터·JSON)">Swagger</button>{h("x.views")}</div></div>'
            f'<div class="qaline">{qa_badge(qa, op.id)}{h("x.badge")} <span class="small mut">이 API 의 TC 수와 자동화 상태 — 클릭하면 이 API 의 상세</span></div>'
            f'<div id="nv" class="view">{normal}</div><div id="sv" class="view" hidden>{swagger}</div>'
            f'<div class="callfoot"><div class="field"><label>테스트 계정{h("x.actor")} <span class="hint">dev-sessions 로 토큰을 받아 Authorization 에 넣는다</span></label>{acts}</div>'
            f'<div class="field"><label>담당자<i class="req"></i></label><select name="operator" required><option value="">— 담당자 —</option>{ops}</select></div>'
            f'<button class="primary wide" {"" if operator else "disabled title=\"담당자를 고르면 열린다\""}>보내기 — dev 에 실제로 나간다 (쓰기 API 도 그대로)</button><div class="right" style="margin-top:4px">{h("x.send")}</div></div>'
            f'<details><summary class="small mut">문서화된 에러 코드</summary><ul class="small">{errs}</ul></details></form>')

    result = ""
    resp_json = None
    if run and steps:
        st = steps[0]
        resp = st.get("response") or {}
        rbody = resp.get("json") if resp.get("json") is not None else resp.get("text")
        resp_json = resp.get("json") if isinstance(resp.get("json"), dict) else None
        req = st["request"]
        ok = str(resp.get("status") or "").startswith("2")
        again = {"op": op.id}
        again.update({f"p.{k}": v for k, v in _path_param_values(op.path, req.get("path") or "").items()})
        again.update({f"q.{k}": v for k, v in (req.get("query") or {}).items()})
        if req.get("actor"):
            again["actor"] = req["actor"]
        if req.get("body") is not None:
            again["body"] = _fmt_json(req["body"])
        from urllib.parse import urlencode
        result = (f'<div class="card"><h3 style="margin-top:0">응답 {badge(str(resp.get("status") or "–"), "ok" if ok else "warn")} '
                  f'<span class="small mut">{resp.get("elapsed_ms") or 0} ms · 실행 기록 <a href="/runs/{e(run["id"])}" class="mono">{e(run["id"])}</a></span></h3>'
                  f'{("<div class=\"small\" style=\"color:var(--bad)\">" + e(st.get("error")) + "</div>") if st.get("error") else ""}'
                  f'<details open><summary class="small mut">응답 본문</summary><pre>{e(_fmt_json(rbody) if not isinstance(rbody, str) else rbody)}</pre></details>'
                  f'<details><summary class="small mut">보낸 요청</summary><pre>{e(_fmt_json({k: v for k, v in req.items() if k in ("url", "query", "body", "headers", "actor")}))}</pre></details>'
                  f'<p id="saved" class="hint"></p>'
                  f'<form method="post" action="/explorer/draft" class="actions"><input type="hidden" name="run" value="{e(run["id"])}"><input type="hidden" name="operator" value="{e(operator)}">'
                  f'<button {"" if operator else "disabled"}>스크립트로 담기 (폼)</button>{h("x.draft")} <a class="btn" href="/explorer?{e(urlencode(again))}">같은 요청으로 다시 열기</a>{h("x.again")}'
                  f'<span class="small mut">담기: 관측한 status·error_code 를 기대로 채운 스크립트 폼을 연다. covers 를 채우고 저장한다</span></form></div>')
    xresp = f'<script>window.XRESP={json.dumps(resp_json, ensure_ascii=False).replace("</", "<\\/") if resp_json is not None else "null"}</script>'
    return f'{head}<div class="xgrid">{left}<div>{result}{card}</div></div>{xresp}<script>{EXPLORER_JS}</script>'


# ---- API 별로 모아 보기 (docs/qa-platform-api.md §5.1·§5.2) ----------------------------------------------
def restdocs_anchor(summary: str) -> str:
    """REST Docs(AsciiDoc) HTML 의 절 앵커 — 절 제목에서 만든다: 소문자, 공백·기호 → `_`, 앞에 `_`. 예: 개발 환경 액세스 토큰 발급 → _개발_환경_액세스_토큰_발급.
    같은 제목이 둘이면 AsciiDoc 이 `_2` 를 붙이는데 그건 알 수 없다 — 안 맞으면 문서 맨 위가 열릴 뿐이다."""
    import re
    return "_" + re.sub(r"[^\w]+", "_", (summary or "").lower()).strip("_")


def _call_verdict(c: dict) -> str:
    return badge(c["verdict"]) + (f' <span class="mono small">{e(c["status"])}</span>' if c.get("status") else "")


def refresh_form(*, operator: str, next_url: str, spec_hash: str | None, fetched_ago: int | None) -> str:
    """[API 문서 다시 읽기] — OpenAPI 캐시를 무시하고 다시 받아 TC 목록을 다시 계산한다. 새 API 를 배포한 직후 누른다."""
    ago = "" if fetched_ago is None else (f"{fetched_ago // 60}분 전 읽음" if fetched_ago >= 60 else f"{fetched_ago}초 전 읽음")
    dis = "" if operator else "disabled title=\"담당자를 먼저 고르세요\""
    return (f'<form method="post" action="/spec/refresh" class="inline" onsubmit="var b=this.querySelector(\'button\');b.disabled=true;b.textContent=\'읽는 중…\'">'
            f'<input type="hidden" name="next" value="{e(next_url)}"><input type="hidden" name="operator" value="{e(operator)}">'
            f'<button {dis}>API 문서 다시 읽기</button></form>{h("spec.refresh")}'
            + (f' <span class="small mut">{e(ago)}</span>' if ago else ""))


def apis_list(rows: list[dict], *, domains: list[str], domain: str, only: str, q: str, spec_hash: str | None, spec_source: str | None, docs_url: str,
              operator: str = "", fetched_ago: int | None = None) -> str:
    ql = (q or "").lower()
    link = lambda d, o: f'/apis?domain={e(d)}{("&only=" + e(o)) if o else ""}{("&q=" + e(q)) if q else ""}'  # noqa: E731
    tabs = "".join(f'<a href="{link(d, only)}" class="{"on" if d == domain else ""}">{e(d)}</a>' for d in domains)
    otabs = "".join(f'<a href="{link(domain, o)}" class="{"on" if (only or "") == o else ""}">{lab}</a>'
                    for o, lab in (("", "모두"), ("noscript", "호출하는 스크립트 없음"), ("uncovered", "미자동화 TC 있음"), ("noerrors", "문서화된 에러 없음")))
    trs = ""
    n = 0
    for r in rows:
        if ql:
            if ql not in (r["id"] + r["path"] + r["summary"]).lower():
                continue
        elif r["domain"] != domain:
            continue
        if only == "noscript" and r["scripts"]:
            continue
        if only == "uncovered" and not r["uncovered"]:
            continue
        if only == "noerrors" and r["errors"]:
            continue
        n += 1
        denom = r["tc"] - r["excluded"]
        auto = (f'<span class="qab {"ok" if denom and r["covered"] == denom else ("warn" if r["uncovered"] else "none")}">{r["covered"]}/{denom}</span>'
                + (f' <span class="small mut">(제외 {r["excluded"]})</span>' if r["excluded"] else "")) if r["tc"] else '<span class="mut">–</span>'
        lc = r.get("last")
        last = (f'<a href="/runs/{e(lc["run_id"])}">{_call_verdict(lc)}</a> <span class="small mut">{kst(lc["created_at"])}</span>') if lc else '<span class="mut">–</span>'
        if r.get("stats"):
            last += f'<br>{stats_badge(r["stats"], what="호출")}'
        ly = r["layers"]
        tc = (f'{r["tc"]} <span class="small mut">API 계약 {ly.get("contract", 0)} · 비즈니스 규칙 {ly.get("policy", 0)} · 수동 작성 {ly.get("manual", 0)}</span>') if r["tc"] else '<span class="mut">0</span>'
        trs += (f'<tr><td><a href="/apis/{e(r["id"])}">{method_badge(r["method"])} <span class="mono">{e(r["path"])}</span></a><br><span class="small mut">{e(r["summary"])} · <span class="mono">{e(r["id"])}</span></span></td>'
                f'<td>{tc}</td><td>{auto}</td><td>{r["scripts"] or "<span class=\"mut\">0</span>"}</td><td>{last}</td><td class="small">{r["errors"] or "<span class=\"mut\">0</span>"}</td></tr>')
    if not trs:
        trs = '<tr><td colspan="6" class="mut">해당 없음</td></tr>'
    return (f'<h1>API{h("apis.list")} <span class="small mut">API 하나를 축으로 TC·스크립트·실행 기록을 모아 본다 — "이 API 는 검증이 어디까지 됐고 지난번엔 어땠나"</span></h1>'
            f'<div class="card"><p class="small mut" style="margin-top:0">OpenAPI(dev 브랜치) <span class="mono">{e(spec_hash or "–")}</span> · 출처 {e(spec_source or "–")}'
            f'{(" · <a href=\"" + e(docs_url) + "\">REST Docs 문서</a>") if docs_url else ""} · OpenAPI 의 tags 가 전부 v1 이라 URL 경로로 도메인을 나눴다 &nbsp; {refresh_form(operator=operator, next_url="/apis", spec_hash=spec_hash, fetched_ago=fetched_ago)}</p>'
            f'<form method="get" style="margin:0 0 8px"><input name="q" value="{e(q)}" placeholder="검색 (operationId · 경로 · 요약) — 검색 중엔 모든 도메인" style="width:100%"></form>'
            f'<div class="tabs">{tabs}</div><div class="tabs">{h("apis.filter")} {otabs}</div></div>'
            f'<div class="card"><table><tr><th>API ({n})</th><th>TC{h("apis.tc")}</th><th>자동화됨{h("apis.auto")}</th><th>호출하는 스크립트{h("apis.scripts")}</th><th>마지막 호출{h("apis.last")}</th><th>에러 코드{h("apis.errors")}</th></tr>{trs}</table>'
            f'<p class="hint">TC = 그 API 에 해당하는 테스트 케이스 수(API 계약 · 비즈니스 규칙 · 수동 작성). 자동화됨 = 검증하는 스크립트가 있는 TC / 제외를 뺀 TC. '
            f'호출하는 스크립트 = 단계의 method·경로가 이 API 인 스크립트. 마지막 호출 = 이 API 를 호출한 가장 최근 단계(API 호출 화면 전송 포함). '
            f'그 아래 통계 = 이 API 를 호출한 최근 20회 단계의 통과율(skip 제외)·평균 소요 — 이 배포 이후 기록만.</p></div>')


def api_detail(d: dict, *, operators: list[str], operator: str, hermes: bool) -> str:
    o, qa = d["op"], d["qa"]
    denom = qa["tc"] - qa["excluded"]
    head = (f'<h1>{method_badge(o["method"])} <span class="mono">{e(o["path"])}</span> <span class="small mut">{e(o["id"])} · {e(o["domain"])}</span></h1>'
            f'<div class="card"><div class="callhead"><div><b>{e(o["summary"] or o["id"])}</b><div class="qaline" style="margin:8px 0 0">{qa_badge(qa, o["id"])} {stats_badge(d.get("stats"), what="호출") if d.get("stats") else ""}</div></div>'
            f'<div class="actions" style="margin:0"><a class="btn primary" href="/explorer?op={e(o["id"])}">호출해 보기</a>{h("api.try")} <a class="btn" href="/chat/new?op={e(o["id"])}">Hermes 와 이야기</a>{h("hermes.attach")}'
            f'{(" <a class=\"btn\" href=\"" + e(d["docs_url"]) + "\">REST Docs</a>") if d.get("docs_url") else ""}</div></div></div>')
    # 스펙
    prow = "".join(f'<tr><td class="mono">{e(x["name"])}{"<i class=\"req\"></i>" if x["required"] else ""}</td><td class="small mut">{e(x["in"])}</td><td class="small">{e(x["description"])}</td></tr>' for x in o["params"])
    succ = "".join(f'<details><summary class="small">{e(st)} 응답 예시</summary><pre>{e(_fmt_json(ex))}</pre></details>' for st, ex in (o.get("success") or {}).items())
    errs = "".join(f'<tr><td class="mono">{e(code)}</td><td>{e(i.get("status"))}</td><td>{e(i.get("message"))}</td></tr>' for code, i in (o.get("errors") or {}).items())
    spec = (f'<h2>스펙{h("api.spec")} <span class="small mut">OpenAPI 에 적힌 것 — Swagger 가 보여 주는 것과 같다</span></h2><div class="card">'
            f'<h4>Parameters</h4>{("<table class=\"params\"><tr><th>Name</th><th>In</th><th>설명</th></tr>" + prow + "</table>") if prow else "<p class=\"hint\">없음</p>"}'
            f'{("<h4>Request Body 예시</h4><pre>" + e(_fmt_json(o["request_example"])) + "</pre>") if o.get("request_example") is not None else ""}'
            f'<h4>성공 응답</h4>{succ or "<p class=\"hint\">예시 없음</p>"}'
            f'<h4>문서화된 에러 코드</h4>{("<table><tr><th>코드</th><th>status</th><th>메시지</th></tr>" + errs + "</table>") if errs else "<p class=\"hint\">없음 — API 계약 TC 가 성공 하나뿐이다. 거절 조건이 있다면 백엔드 REST Docs 에 4xx 예시가 빠진 것</p>"}</div>')
    # TC (층별)
    def tc_rows(items: list[dict]) -> str:
        out = ""
        for t in items:
            state = "excluded" if t.get("excluded") else ("covered" if t["scripts"] else "uncovered")
            sc = " ".join(f'<a href="/cases/{e(cid)}" class="mono small">{e(cid)}</a>' + (f' <a href="/runs/{e(t["last"][cid]["run_id"])}">{badge(t["last"][cid]["verdict"])}</a>' if cid in t["last"] else "") for cid in t["scripts"][:3])
            chk = f'<input type="checkbox" name="tc_ids" value="{e(t["id"])}"> ' if state != "excluded" else ""
            out += (f'<tr class="{"ex" if state == "excluded" else ""}"><td>{chk}{tc_link(t["id"])}</td><td>{e(t["title"])}{(" <span class=\"mono small\">" + e(t["error_code"]) + "</span>") if t.get("error_code") else ""}</td>'
                    f'<td>{badge({"covered": "자동화됨", "uncovered": "미자동화", "excluded": "자동화 제외"}[state], state)}'
                    f'{(" <span class=\"small mut\" title=\"" + e(t["excluded"]) + "\">" + e(t["excluded"][:40]) + "</span>") if state == "excluded" else (" " + sc)}</td></tr>')
        return out
    sections = ""
    for layer, lab in (("contract", "API 계약 (OpenAPI 응답·에러 코드)"), ("policy", "비즈니스 규칙 (SSOT, API 매핑으로 연결)"), ("manual", "수동 작성 (manual-tc.yaml)")):
        items = d["tcs"].get(layer) or []
        if items:
            sections += f'<h3>{badge(layer)} {e(lab)} <span class="mut small">{len(items)}</span></h3><table><tr><th>TC</th><th>내용</th><th>자동화 · 검증하는 스크립트</th></tr>{tc_rows(items)}</table>'
    ops = "".join(f'<option value="{e(x)}" {"selected" if x == operator else ""}>{e(x)}</option>' for x in operators)
    tcs = (f'<h2>이 API 의 TC{h("api.tcs")}{h("tc.state")} <span class="small mut">{qa["tc"]}건 · 자동화됨 {qa["covered"]}/{denom}{(" · 제외 " + str(qa["excluded"])) if qa["excluded"] else ""}</span></h2>'
           f'<form method="post" action="/drafts/generate"><div class="card">'
           + (sections or '<p class="mut">이 API 에 해당하는 TC 가 없다. OpenAPI 에 응답 예시가 없거나, SSOT command 가 <span class="mono">catalog/bindings.yaml</span> 에 매핑되지 않았다.</p>')
           + (f'<div class="actions"><select name="operator" required><option value="">— 담당자 —</option>{ops}</select>'
              f'<button class="primary" {"" if hermes else "disabled title=\"HERMES_API_KEY 없음\""}>고른 TC 로 Hermes 가 스크립트 쓰기</button>'
              f'<span class="small mut">같은 도메인 1~10건</span></div>' if sections else "") + '</div></form>')
    # 부르는 스크립트
    srows = "".join(
        f'<tr><td><a href="/cases/{e(s["id"])}" class="mono">{e(s["id"])}</a>{(" <span class=\"small mut\" title=\"스크립트의 operations: 목록에는 있지만 이 API 를 호출하는 단계가 없다\">operations 에만 있음</span>") if not s["steps"] else (" <span class=\"small mut\" title=\"단계는 호출하는데 스크립트의 operations: 목록에 없다\">operations 에 없음</span>" if not s["declared"] else "")}</td>'
        f'<td>{e(s["title"])}</td><td class="small">{e(" · ".join(s["steps"]))}</td><td>{badge(s["suite"])}</td>'
        f'<td>{(("<a href=\"/runs/" + e(s["last"]["run_id"]) + "\">" + badge(s["last"]["verdict"]) + "</a> <span class=\"small mut\">" + kst(s["last"]["created_at"]) + "</span>") if s.get("last") else "<span class=\"mut\">–</span>")}</td></tr>'
        for s in d["scripts"]) or '<tr><td colspan="5" class="mut">이 API 를 호출하는 스크립트가 없다 — 테스트 커버리지가 비는 곳</td></tr>'
    scripts = f'<h2>호출하는 스크립트{h("api.scripts")} <span class="small mut">{len(d["scripts"])}건</span></h2><div class="card"><table><tr><th>스크립트</th><th>제목</th><th>이 API 를 호출하는 단계</th><th>스위트</th><th>마지막 결과</th></tr>{srows}</table></div>'
    # 최근 호출
    crows = ""
    for c in d["recent_calls"]:
        again = {"op": o["id"]}
        again.update({f"p.{k}": v for k, v in _path_param_values(o["path"], c.get("path") or "").items()})
        again.update({f"q.{k}": v for k, v in (c.get("query") or {}).items()})
        if c.get("actor"):
            again["actor"] = c["actor"]
        if c.get("body") is not None:
            again["body"] = _fmt_json(c["body"])
        from urllib.parse import urlencode
        who = "API 호출" if c["trigger"] == "explorer" else f'<a href="/cases/{e(c["case_id"])}" class="mono">{e(c["case_id"])}</a> <span class="small mut">{e(c["name"])}</span>'
        bad = [x for x in (c.get("checks") or []) if not x.get("ok")]
        note = (f' <span class="small" style="color:var(--bad)">{e(c["error"][:100])}</span>' if c.get("error") else "") if (c["verdict"] != "pass") else ""
        crows += (f'<tr><td class="small">{kst(c["created_at"])}</td><td><a href="/runs/{e(c["run_id"])}" class="mono small">{e(c["run_id"])}</a><br><span class="small mut">{e(TRIGGER_KO.get(c["trigger"], c["trigger"]))} · {e(c["operator"])}</span></td>'
                  f'<td>{who}{(" <span class=\"small mut\">" + e(c["actor"]) + "</span>") if c.get("actor") else ""}</td><td>{_call_verdict(c)}{note}</td><td class="small">{c.get("duration_ms") or 0} ms</td>'
                  f'<td><a class="btn" href="/explorer?{e(urlencode(again))}">같은 요청으로 열기</a></td></tr>')
    recent = (f'<h2>최근 호출{h("api.calls")} <span class="small mut">이 API 를 호출한 단계 최근 {len(d["recent_calls"])}건 — 스크립트 실행과 API 호출 화면 전송 모두</span></h2>'
              f'<div class="card"><table><tr><th>시각</th><th>실행 기록</th><th>스크립트 · 단계</th><th>판정 · status</th><th>소요</th><th></th></tr>'
              f'{crows or "<tr><td colspan=\"6\" class=\"mut\">아직 호출한 기록이 없다</td></tr>"}</table></div>')
    return head + spec + tcs + scripts + recent


# ---- 준비 작업 — 버튼 하나로 테스트 데이터 만들기 (docs/qa-platform-api.md §5.4) -----------------------------
SETUP_JS = r"""
(function(){
  function ls(k,d){try{var v=localStorage.getItem(k);return v==null?d:JSON.parse(v)}catch(e){return d}}
  function lsset(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}
  var OP=(window.QA&&window.QA.operator)||''; var SFX=OP?(':'+OP):'';
  document.querySelectorAll('.call').forEach(function(F){
    var nv=F.querySelector('.view.nv'), sv=F.querySelector('.view.sv'), seg=F.querySelector('.seg');
    function setView(v){ nv.hidden=(v!=='normal'); sv.hidden=(v!=='swagger'); seg.querySelectorAll('button').forEach(function(b){b.classList.toggle('on',b.dataset.v===v)}); lsset('qa_view',v); }
    seg.addEventListener('click',function(ev){var b=ev.target.closest('button[data-v]'); if(b) setView(b.dataset.v)});
    setView(ls('qa_view','normal'));
    F.addEventListener('submit',function(){ var b=F.querySelector('button.primary'); if(b){b.disabled=true;b.textContent='실행 중…'} });
  });
  // 결과값을 API 호출 화면 입력칸의 "최근에 넣은 값" 으로 기억 (브라우저에만)
  var R=window.SETUP_OUT||{}; var saved=[];
  Object.keys(R).forEach(function(k){ var v=R[k]; if(v==null||v==='') return; var key='qa_recent'+SFX+'.'+k; var vals=ls(key,[]).filter(function(x){return x!==String(v)}); vals.unshift(String(v)); lsset(key,vals.slice(0,5)); saved.push(k); });
  var sb=document.getElementById('saved'); if(sb&&saved.length) sb.textContent='API 호출 화면의 입력칸에 최근에 넣은 값으로 뜬다 (이 브라우저에만): '+saved.join(', ');
  document.querySelectorAll('button[data-copy]').forEach(function(b){ b.addEventListener('click',function(){ navigator.clipboard&&navigator.clipboard.writeText(b.dataset.copy); b.textContent='복사됨'; setTimeout(function(){b.textContent='복사'},1200); }); });
})();
"""


def cleanup_section(cu: dict | None, *, operators: list[str], operator: str) -> str:
    """QA 데이터 정리 — dev 전용 API(PR #135)로 [QA] 룸과 QA 회원을 지우고 테스트 계정을 초기화한다. 실행 기록이 아니라 감사 로그에만 남는다."""
    if cu is None:
        return ""
    ops = "".join(f'<option value="{e(o)}" {"selected" if o == operator else ""}>{e(o)}</option>' for o in operators)
    def form(action, target, label, *, cls="", confirm=""):
        dis = "" if operator else "disabled title=\"담당자를 먼저 고르세요\""
        return (f'<form method="post" action="/setup/cleanup" class="inline" onsubmit="return confirm({json.dumps(confirm or (label + "?"), ensure_ascii=False)})">'
                f'<input type="hidden" name="action" value="{e(action)}"><input type="hidden" name="target" value="{e(target)}"><input type="hidden" name="operator" value="{e(operator)}">'
                f'<button class="{cls}" {dis}>{e(label)}</button></form>')
    head = (f'<h2 id="cleanup">QA 데이터 정리{h("setup.cleanup")} <span class="small mut">dev 에 남은 [QA] 데이터를 지운다 — 백엔드 dev 전용 API 라 진짜로 행이 없어진다</span></h2>')
    if not cu.get("available"):
        return head + f'<div class="card"><p class="mut" style="margin:0">지금은 쓸 수 없다: {e(cu.get("why") or "")}</p></div>'
    if cu.get("error"):
        er = cu["error"]
        return head + f'<div class="card"><p class="mut" style="margin:0;color:var(--bad)">목록을 못 읽었다 — {e(er.get("code"))}: {e(er.get("message"))}</p></div>'
    rooms = cu.get("rooms") or []
    rrows = "".join(
        f'<tr><td class="mono small">{e(str(r.get("roomId") or "")[:8])}…</td><td>{e(r.get("title"))}</td><td>{badge(r.get("status"))}</td><td>{e(r.get("host_label"))}</td>'
        f'<td class="small">신청 {(r.get("counts") or {}).get("applications", 0)} · 참여 {(r.get("counts") or {}).get("participants", 0)}</td><td class="small mut">{e((r.get("createdAt") or "")[:16].replace("T", " "))}</td>'
        f'<td>{form("delete_room", str(r.get("roomId") or ""), "삭제", cls="danger", confirm=f"[{r.get("title") or ""}] 룸과 딸린 데이터를 전부 지운다. 되돌릴 수 없다.")}</td></tr>'
        for r in rooms) or '<tr><td colspan="7" class="mut">[QA] 룸이 없다</td></tr>'
    members = cu.get("members") or []
    mrows = "".join(
        f'<tr><td class="mono small">{e(str(m.get("memberId") or "")[:8])}…{(" <b>" + e(m["label"]) + "</b>") if m.get("label") else ""}</td><td>{e(m.get("nickname"))}</td><td class="small mut">{e(m.get("email"))}</td>'
        f'<td>{form("delete_member", str(m.get("memberId") or ""), "삭제", cls="danger", confirm="QA 테스트 회원과 그 회원의 데이터를 전부 지운다. 되돌릴 수 없다.")}</td></tr>'
        for m in members)
    resets = " ".join(form("reset", a, f"{a} 초기화", confirm=f"테스트 계정 {a} 를 룸이 하나도 없는 처음 상태로 되돌린다 — 방장인 [QA] 룸과 신청·참여 행을 지운다. 회원·프로필·이력서는 남는다.") for a in cu.get("actors") or [])
    return (head + f'<div class="card"><p class="small mut" style="margin-top:0">지우는 건 백엔드가 제목 <span class="mono">[QA]</span> 로 시작하는 것만 허용한다(아니면 E2201). 모든 버튼은 감사 로그에 남는다. '
            f'담당자: <select onchange="document.cookie=\'qa_operator=\'+this.value+\';path=/;max-age=31536000\';location.reload()"><option value="">— 담당자 —</option>{ops}</select></p>'
            f'<h4>[QA] 룸 {len(rooms)}개</h4><table><tr><th>id</th><th>제목</th><th>상태</th><th>방장</th><th>딸린 행</th><th>만든 시각</th><th></th></tr>{rrows}</table>'
            f'<div class="actions">{form("delete_all", "", "[QA] 룸 전부 삭제", cls="danger", confirm=f"[QA] 룸 {len(rooms)}개와 딸린 데이터를 전부 지운다. 되돌릴 수 없다.")}{h("setup.delete_all")}'
            f'<span class="small mut">테스트 계정 초기화{h("setup.reset")}:</span> {resets}</div>'
            + (f'<h4>QA 테스트 회원 {len(members)}명{h("setup.members")}</h4><table><tr><th>id</th><th>닉네임</th><th>이메일</th><th></th></tr>{mrows}</table>' if members else "")
            + '</div>')


def members_section(qa_members: list[dict], *, actors: list[str], operators: list[str], operator: str, available: bool) -> str:
    """QA 테스트 회원 만들기 — dev 전용 API 로 회원을 만들고, 그 이름을 테스트 계정처럼 쓴다(계정 2개 한계를 넘기려고)."""
    dis = "" if (operator and available) else ("disabled title=\"담당자를 먼저 고르세요\"" if available else "disabled title=\"dev QA API 를 쓸 수 없다\"")
    rows = "".join(f'<tr><td class="mono">{e(m["label"])}</td><td>{e(m.get("nickname") or "")}</td><td class="small mut">{e(m.get("email") or "")}</td>'
                   f'<td class="small mut">{kst(m["created_at"])} · {e(m["operator"])}</td></tr>' for m in qa_members) or '<tr><td colspan="4" class="mut">아직 만든 회원이 없다</td></tr>'
    return (f'<h2 id="members">QA 테스트 회원 만들기{h("setup.member")} <span class="small mut">고정 테스트 계정 2개(qa-host · qa-guest)로 모자랄 때 — 정원 채우기, 세 번째 참여자, 위임 시나리오</span></h2>'
            f'<div class="card"><form method="post" action="/setup/member" class="actions" style="margin-top:0">'
            f'<label>이름 <input name="label" placeholder="예: qa-3" pattern="[a-z0-9][a-z0-9\\-]{{0,30}}" required style="width:160px"></label>'
            f'<input type="hidden" name="operator" value="{e(operator)}"><button class="primary" {dis}>회원 만들기</button>'
            f'<span class="small mut">Google 로그인 없이 실제 가입 경로로 만든다. 이름이 테스트 계정 이름이 되어 스크립트 <span class="mono">actor:</span> 와 API 호출 화면 드롭다운에 바로 뜬다. 토큰은 저장하지 않는다 — 필요할 때 dev-sessions 로 받는다.</span></form>'
            f'<table><tr><th>테스트 계정 이름</th><th>닉네임</th><th>이메일</th><th>만든 때</th></tr>{rows}</table>'
            f'<p class="hint">지우는 건 아래 "QA 데이터 정리"의 QA 테스트 회원 표에서. 지금 쓸 수 있는 테스트 계정 전체: <span class="mono">{e(", ".join(actors) or "없음")}</span></p></div>')


def setup_page(cases: list, *, actors: list[str], operators: list[str], operator: str, result: dict | None, errors: list[str], cleanup: dict | None = None,
               qa_members: list[dict] | None = None) -> str:
    head = ('<h1>테스트 데이터 만들기' + h("setup.cards") + ' <span class="small mut">여러 API 를 순서대로 호출해 dev 에 테스트 데이터를 만드는 일을 버튼 하나로 대신한다. '
            'Normal 은 값만 넣는 입력 폼, Swagger 는 실제로 나가는 요청 원문. 만든 데이터는 지우지 않는다(제목 [QA], 사람이 지운다). 실행은 실행 기록에 남고 Slack 은 안 보낸다</span></h1>')
    res = ""
    if result:
        run, rc, steps, outs = result["run"], result["case"], result["steps"], result["outputs"]
        v = run.get("verdict") or run["status"]
        orows = "".join(f'<tr><td class="mono">{e(k)}</td><td class="mono">{e(val) if val not in (None, "") else "<span class=\"mut\">(없음)</span>"}</td>'
                        f'<td>{("<button type=\"button\" data-copy=\"" + e(val) + "\">복사</button>") if val not in (None, "") else ""}</td></tr>' for k, val in outs.items())
        bad = [s for s in steps if s["verdict"] not in ("pass",)]
        srows = "".join(f'<tr><td>{e(s["name"])}</td><td>{badge(s["verdict"])} <span class="mono small">{e((s.get("response") or {}).get("status") or "")}</span></td>'
                        f'<td class="small" style="color:var(--bad)">{e(s.get("error") or "")}</td></tr>' for s in steps)
        res = (f'<div class="card"><h3 style="margin-top:0">결과 {badge(v)} <span class="small mut">{e(rc["case_title"] if rc else "")} · 실행 기록 <a href="/runs/{e(run["id"])}" class="mono">{e(run["id"])}</a> · {kst(run["created_at"])}</span></h3>'
               + (f'<table><tr><th>결과값{h("setup.outputs")}</th><th></th><th></th></tr>{orows}</table><p id="saved" class="hint"></p>' if outs else '<p class="hint">결과값이 없다</p>')
               + (f'<details {"open" if bad else ""}><summary class="small mut">단계 {len(steps)}개</summary><table><tr><th>단계</th><th>판정</th><th>오류</th></tr>{srows}</table></details>')
               + f'<div class="actions"><a class="btn primary" href="/explorer">API 호출 화면으로</a> <a class="btn" href="/runs/{e(run["id"])}">실행 상세</a></div></div>'
               + f'<script>window.SETUP_OUT={json.dumps({k: v for k, v in outs.items() if v not in (None, "")}, ensure_ascii=False, default=str).replace("</", "<\\/")}</script>')
    errs = "".join(f'<div class="flash err">{e(x)}</div>' for x in errors)
    ops = "".join(f'<option value="{e(o)}" {"selected" if o == operator else ""}>{e(o)}</option>' for o in operators)
    cards = ""
    for c in cases:
        fields = ""
        for name, spec in c.inputs.items():
            d = spec.get("default")
            fields += (f'<div class="field"><label>{e(spec["label"])}{"<i class=\"req\"></i>" if spec["required"] else ""}'
                       f'{(" <span class=\"hint\">" + e(spec["hint"]) + "</span>") if spec.get("hint") else ""}</label>'
                       f'<input name="input.{e(name)}" value="{e("" if d is None else d)}" {"required" if spec["required"] and d in (None, "") else ""} autocomplete="off"></div>')
        if not fields:
            fields = '<p class="hint">넣을 값이 없다 — 그대로 실행하면 된다</p>'
        outs = ", ".join(c.outputs) or "없음"
        sw = ""
        for i, st in enumerate(c.steps, 1):
            req = st["request"]
            body = f'<pre style="margin:4px 0 0">{e(_fmt_json(req["body"]))}</pre>' if req.get("body") is not None else ""
            who = st.get("actor", c.actor)
            sw += (f'<div class="sline"><span class="mut small">{i}.</span> {method_badge(req["method"])} <span class="mono">{e(req["path"])}</span> '
                   f'<span class="small mut">{("전제 " + e(st["given"]) + " · ") if st.get("given") else ""}{e(st["name"])}{(" · " + e(who)) if who else " · 비로그인"}</span>'
                   f'{(" <span class=\"small mut\">→ " + e(", ".join(st["save"].keys())) + "</span>") if st.get("save") else ""}{body}</div>')
        actor_ok = (not c.needs_actor()) or all((a in actors) for a in {c.actor, *[s.get("actor") for s in c.steps]} if a)
        cards += (f'<form method="post" action="/setup/run" class="card call"><input type="hidden" name="case_id" value="{e(c.id)}">'
                  f'<div class="callhead"><div><b>{e(c.title)}</b> <span class="mono mut small">{e(c.id)}</span><br><span class="small mut">{e(c.description)}</span></div>'
                  f'<div class="seg"><button type="button" data-v="normal" title="값만 넣는 입력 폼">Normal</button><button type="button" data-v="swagger" title="실제로 나가는 요청 원문 (메서드·경로·본문)">Swagger</button>{h("setup.swagger")}</div></div>'
                  f'<div class="view nv">{fields}<p class="hint">결과값: <span class="mono">{e(outs)}</span> · 단계 {len(c.steps)}개'
                  f'{(" · 테스트 계정 " + e(", ".join(sorted({a for a in [c.actor, *[s.get("actor") for s in c.steps]] if a})))) if c.needs_actor() else ""}</p></div>'
                  f'<div class="view sv" hidden>{sw}<p class="hint">💡 실제로 나가는 요청을 순서대로 보여 준다. <span class="mono">{{{{input.x}}}}</span> 는 Normal 의 입력값으로, 나머지 치환은 실행 때 채워진다. 여기서는 고칠 수 없다 — 스크립트 파일(<span class="mono">cases/setup.yaml</span>)이 원본</p></div>'
                  f'<div class="callfoot"><div class="field"><label>담당자<i class="req"></i></label><select name="operator" required><option value="">— 담당자 —</option>{ops}</select></div>'
                  f'{"" if actor_ok else "<p class=\"hint bad\">테스트 계정이 설정돼 있지 않다 (QA_ACTORS) — 실행하면 skipped 로 남는다</p>"}'
                  f'<button class="primary wide" {"" if operator else "disabled title=\"담당자를 고르면 열린다\""}>실행 — dev 에 실제로 만든다</button></div></form>')
    if not cards:
        cards = '<div class="card"><p class="mut" style="margin:0">테스트 데이터 만들기 스크립트(suite setup)가 없다. <span class="mono">cases/*.yaml</span> 에 <span class="mono">suite: setup</span> 으로 적는다 (가이드 참고).</p></div>'
    members = members_section(qa_members or [], actors=actors, operators=operators, operator=operator, available=bool(cleanup and cleanup.get("available"))) if cleanup is not None else ""
    return f'{head}{errs}{res}<div class="grid setup-grid">{cards}</div>{members}{cleanup_section(cleanup, operators=operators, operator=operator)}<script>{SETUP_JS}</script>'


# ---- 담당자 고르기 (처음 들어올 때) -----------------------------------------------------------------
def whoami_page(operators: list[str], *, current: str, next_url: str) -> str:
    """처음 들어오면 본인을 고른다(자기 신고). 담당자 자동 선택·감사 로그 이름·즐겨찾기/최근 값/대화(브라우저에만)가 이 이름별로 나뉜다."""
    btns = "".join(f'<form method="post" action="/whoami" class="inline"><input type="hidden" name="next" value="{e(next_url)}"><input type="hidden" name="operator" value="{e(o)}">'
                   f'<button class="{"primary" if o == current else ""}" style="min-width:140px;padding:12px 18px;font-size:15px">{e(o)}</button></form>' for o in operators)
    return (f'<h1>누구세요?{h("whoami")}</h1><div class="card" style="max-width:640px">'
            f'<p>이 플랫폼은 팀 공용 비밀번호로 들어오기 때문에 본인을 직접 고른다. 고른 이름은 버튼을 누를 때 담당자로 자동 선택되고 감사 로그에 남는다. '
            f'즐겨찾기·최근에 넣은 값·열어 둔 Hermes 대화도 이 이름별로 이 브라우저에 따로 저장된다.</p>'
            f'<div class="actions" style="gap:10px">{btns}</div>'
            f'<p class="hint">목록에 없는 이름은 <span class="mono">QA_OPERATORS</span> 설정(compose)에 더한다. 언제든 오른쪽 위 [바꾸기].</p></div>')


# ---- 가이드 --------------------------------------------------------------------------------------
def _sec(title: str, body: str) -> str:
    return f'<h2>{title}</h2><div class="card">{body}</div>'


def guide(*, public_url: str, target: str, wiki_url: str, sprint_days: int) -> str:
    intro = ('<h1>가이드 — 이 플랫폼은 무엇을 하고, 어떻게 쓰는가</h1>'
             '<div class="card"><p style="margin:0"><b>한 줄.</b> 기획 문서(llm-wiki 의 PRD·상태-SSOT)와 백엔드 API 계약(OpenAPI)에서 <b>검증 기준(TC)</b> 을 뽑고 '
             '그 TC 를 검증하는 <b>스크립트</b>(YAML)를 사람이 버튼을 눌러 dev 서버에 실행해 <b>누가 언제 무엇을 검증했는지</b> 남긴다. 자동으로 도는 것은 없다.</p></div>')

    # ---- 0. 개발 과정에서 이렇게 쓴다 (사용자 요청 2026-09-22: 개발 프로세스 기준 + 예시 시나리오 하나. 일반 QA 용어만, 첫 등장에 풀이) ----
    s_howto = """
<p class="small mut" style="margin-top:0">기획 → 구현 → PR → dev 배포 → 확인 → 스프린트 마감 → 릴리스. 이 순서에서 플랫폼이 등장하는 곳은 다섯 군데다. 처음 나오는 말은 그 자리에서 풀이하고, 아래 <a href="#terms">용어</a> 표에도 모아 두었다.</p>
<table><tr><th style="width:150px">단계</th><th style="width:70px">누가</th><th>플랫폼에서 하는 일</th><th>결과</th></tr>
<tr><td><b>1. 기획 확정</b></td><td>기획</td><td>위키의 기획 문서(PRD)와 정책 규칙표(SSOT — 기능마다 "누가 · 어떤 조건이면 · 무엇이 바뀐다"를 적은 표)를 고친다. 플랫폼은 여기서 <b>테스트 케이스(TC, "무엇을 확인해야 하는가" 한 건)</b>를 자동으로 뽑는다</td><td><a href="/catalog">테스트 케이스 (TC)</a> 화면에 확인 항목이 생긴다. 사람이 플랫폼에서 TC 를 손으로 쓰지 않는다 — 빠졌으면 위키를 고친다</td></tr>
<tr><td><b>2. 구현 · PR · dev 머지</b></td><td>개발</td><td><b>평소와 같다.</b> 새 API 가 생겼으면 API 문서(OpenAPI)에 응답 예시·에러 코드가 실리게 하고, 규칙표의 기능과 API 를 잇는 표(API 매핑, <span class="mono">catalog/bindings.yaml</span>)에 한 줄 더한다</td><td>TC 화면에 "API 계약" TC 가 생긴다</td></tr>
<tr class="ex"><td>dev 자동 배포</td><td>자동</td><td>없음 — 플랫폼은 배포를 <b>감지만</b> 한다</td><td><a href="/">대시보드</a>에 그 배포가 <span class="b warn">미검증</span> 으로 뜬다</td></tr>
<tr><td><b>3. 배포 검증</b></td><td>개발</td><td>대시보드에서 [검증]. 플랫폼이 PR 이 바꾼 파일에서 도메인(룸·신청·회원 같은 기능 영역)을 읽어 그 도메인의 <b>sanity 테스트 스크립트</b>(바뀐 부분 위주로 dev 에 요청을 보내 확인하는 것)를 제안한다. 담당자를 고르고 실행</td><td>Slack 에 결과. 통과하면 배포에 ✓. 실패하면 실행 상세의 [Hermes 실패 분석] — 팀 AI 비서 Hermes 가 <b>버그 / 스크립트 노후 / 환경 문제</b> 중 무엇인지 근거와 함께 제안</td></tr>
<tr><td><b>4. 테스트 스크립트 늘리기</b></td><td>개발 · QA</td><td>새 기능의 TC 가 <span class="b uncovered">미자동화</span>(확인하는 스크립트가 없음)로 남아 있다. <a href="/apis">API</a> 화면에서 그 API 를 열어 TC 를 고르고 [고른 TC 로 Hermes 가 스크립트 쓰기](진행이 실시간으로 보이고, 검증을 통과하면 바로 저장된다) 또는 [고른 TC 로 직접 쓰기 (폼)]. 폼은 [저장 전에 한 번 실행해 보기] 로 먼저 돌려 본다. 저장하면 플랫폼이 main 에 커밋하고 바로 실행 스위트에 넣는다</td><td>검증(형식·TC 대조·계약 일치)을 통과하지 못한 스크립트는 저장되지 않는다</td></tr>
<tr><td><b>5. 스프린트 마감 · 릴리스</b></td><td>QA</td><td>스프린트(Linear 사이클, 7일)마다 [스프린트 smoke 실행] — 핵심 기능이 죽지 않았는지 전체를 빠르게 확인하는 읽기 위주 묶음. 릴리스 전 [릴리스 QA] + 체크리스트 + GO / NO-GO <b>기록</b></td><td>안 돌리면 대시보드 배지와 Slack 리마인드(자동 실행은 없다). main 승격은 사람이 따로 — 플랫폼은 막지 않고 근거만 남긴다</td></tr></table>

<h3 style="margin-top:18px">예시 — 참가 신청 반려에 사유를 붙인다</h3>
<p class="small mut">방장이 참가 신청을 반려할 때 사유(직무 불일치 등)를 고르게 하는 기능. 규칙표에는 이미 "방장만 반려할 수 있다", "대기 중인 신청만 반려된다"가 있고, 이번에 "사유는 정해진 값 중 하나여야 한다"가 더해진다. 기획자 A, 개발자 B, QA 담당 C 가 한 스프린트 안에서 이렇게 움직인다.</p>
<table><tr><th style="width:110px">언제</th><th>무슨 일</th></tr>
<tr><td><b>월</b><br><span class="small mut">기획</span></td><td><ul style="margin:0;padding-left:18px">
<li><b>A</b> 가 위키 PRD 「룸 참여 및 참여자 관리」에 반려 사유 항목을 적고, 규칙표(SSOT)의 "신청 반려"에 "사유는 선택지 중 하나" 조건을 더한다.</li>
<li>플랫폼이 규칙표를 다시 읽어 TC 화면에 새 TC(<span class="mono">G.application.reject#reason-in-options</span> "선택지에 없는 사유는 거절")를 만든다. 기존 반려 스크립트에 <span class="b drift">TC 변경</span> 표시 — 확인 기준이 바뀌었으니 스크립트를 다시 보라는 뜻.</li></ul></td></tr>
<tr><td><b>화</b><br><span class="small mut">구현·배포</span></td><td><ul style="margin:0;padding-left:18px">
<li><b>B</b> 가 구현. 반려 API(<span class="mono">POST /v1/rooms/{roomId}/applications/{applicationId}/reject</span>)가 본문에 <span class="mono">reason</span> 을 받고, 없는 값이면 400 <span class="mono">E400</span>. 선택지 조회 API(<span class="mono">GET /v1/rooms/reject-reasons</span>)가 새로 생긴다. REST Docs 테스트에 요청 예시와 400 예시를 넣는다.</li>
<li>PR → 리뷰 → dev 머지 → 자동 배포. 대시보드에 <span class="b warn">미검증</span> 배포로 뜬다. 새 API 는 API 화면에도 나타나고 "API 계약" TC(<span class="mono">op.rejectApplication:E400</span>)가 생긴다.</li></ul></td></tr>
<tr><td><b>화 오후</b><br><span class="small mut">배포 검증</span></td><td><ul style="margin:0;padding-left:18px">
<li><b>B</b> 가 [검증]. PR 변경 파일 → 도메인 <span class="mono">application</span> → sanity 3개 제안. 실행. <span class="b fail">2 통과 · 1 실패</span> — 기존 반려 스크립트의 반려 단계가 400 을 받았다.</li>
<li>[Hermes 실패 분석] → "스크립트 노후: 반려 요청에 <span class="mono">reason</span> 이 필수가 됐는데 스크립트가 안 보낸다. 버그 아님." B 가 동의.</li>
<li>스크립트 상세의 [바뀐 TC 에 맞게 Hermes 가 고치기]. 검증을 통과하면 main 의 그 항목이 바로 바뀌고 "Hermes 작성" 표시가 붙는다. 최근 변경의 커밋에서 무엇이 바뀌었는지 본다. 한두 칸만 고치면 되면 [폼으로 고치기].</li>
<li>다시 [검증] → <span class="b pass">3/3 통과</span>. 배포에 ✓. Slack: "B 가 PR #131 배포 검증 → 3/3 통과".</li></ul></td></tr>
<tr><td><b>수</b><br><span class="small mut">스크립트 추가</span></td><td><ul style="margin:0;padding-left:18px">
<li><b>B</b> 가 API 화면 → <span class="mono">rejectApplication</span> 상세. TC 4건 중 <span class="b uncovered">미자동화</span> 2건(<span class="mono">E400</span>, <span class="mono">G.application.reject#reason-in-options</span>). 둘을 체크 → [고른 TC 로 Hermes 가 스크립트 쓰기]. Hermes 가 쓴 스크립트가 형식·TC 일치 검사를 통과해 바로 저장된다.</li>
<li>손으로도 한 번 본다. <a href="/setup">테스트 데이터 만들기</a>에서 "신청이 하나 들어온 룸" 실행 → 결과값 <span class="mono">roomId</span>·<span class="mono">applicationId</span>. <a href="/explorer">API 호출</a>에서 <span class="mono">rejectApplication</span> 을 열면 그 값이 입력칸에 이미 들어 있다. Normal(값만 넣는 입력 폼)에 <span class="mono">reason</span> 을 엉뚱한 값으로 넣고 보내기 → 400 <span class="mono">E400</span> 확인. Swagger(실제로 나가는 요청 원문)로 보낸 JSON 도 확인.</li>
<li>저장과 동시에 main 에 커밋. 바로 sanity 에 실린다. TC 화면의 <span class="mono">application</span> 도메인 자동화 수가 올라간다.</li></ul></td></tr>
<tr><td><b>금</b><br><span class="small mut">스프린트 마감</span></td><td><ul style="margin:0;padding-left:18px">
<li><b>C</b> 가 [스프린트 smoke 실행]. 실행 상세에 요약 카드(전체·완료·통과율·실패)와 도메인별 막대. <span class="b pass">전부 통과</span>. Slack 에 결과.</li>
<li>스크립트 목록의 "최근 5회 통과율 80%" 로 화요일 실패가 스크립트 노후였음을 다시 확인. <span class="b warn">불안정 (flaky)</span> 표시(스크립트를 안 고쳤는데 결과가 오락가락함)는 없다 — 고친 뒤로는 계속 통과.</li></ul></td></tr>
<tr><td><b>릴리스 전</b></td><td><ul style="margin:0;padding-left:18px">
<li><b>C</b> 가 [릴리스 QA] → 통과. 체크리스트(백엔드 <span class="mono">release-checklist.md</span>)를 확인하고 <b>GO</b> 와 사유를 기록. 필요하면 [위키에 보고서 게시]. main 승격은 팀이 따로.</li>
<li><a href="/activity">감사 로그</a>에 이 주의 모든 클릭이 남아 있다 — 누가 언제 검증했고, 어떤 스크립트를 저장했고, 릴리스를 GO 했는지.</li></ul></td></tr></table>

<h3 style="margin-top:18px">플랫폼이 하지 않는 것</h3>
<ul style="margin:0;padding-left:18px">
<li>저절로 실행하지 않는다. 배포 뒤 자동 검증, 시간 맞춰 도는 smoke, 웹훅 — 없다. 대시보드 표시와 Slack 알림까지만.</li>
<li>live(운영) 서버를 건드리지 않는다. 확인 대상은 항상 dev.</li>
<li>TC 를 플랫폼 안에서 만들지 않는다. 확인 항목이 빠졌으면 위키(규칙표·기획 문서)나 API 문서를 고친다.</li>
<li>AI 가 실행·발행하지 않는다. Hermes 는 스크립트 쓰기(검증을 통과하면 저장, "Hermes 작성" 표시)와 분석과 답변까지.</li>
<li>스크립트가 만든 데이터는 스크립트가 지운다. 예외는 "테스트 데이터 만들기" — 남기는 게 목적이라 제목을 <span class="mono">[QA]</span> 로 시작해 사람이 지운다.</li></ul>
<p class="small mut" style="margin:10px 0 0">화면 하나하나는 아래 "화면별로 무엇을 하나", 실행 버튼을 눌렀을 때 벌어지는 일은 "1. 실행 버튼을 누르면" 절.</p>
"""

    s1 = f"""
<ol>
<li><b>사람이 버튼을 누른다.</b> 대시보드의 [검증](배포 1건) · [스프린트 smoke 실행] · [릴리스 검증] · [수동 실행]. 크론·webhook·자동 실행은 설계상 두지 않았다. 배포 목록은 GitHub Actions 를 <i>읽어서</i> 보여 줄 뿐이다.</li>
<li><b>확인 화면</b>에서는 플랫폼이 범위를 <i>제안</i>한다. 배포 검증이면 PR 변경 파일 → 도메인 → 그 도메인의 sanity 스크립트, 스프린트면 smoke 전체다. 담당자(자기 신고)를 고르고 스크립트를 조정한 뒤 [실행].</li>
<li><b>테스트 실행이 만들어지면서</b> 그 시점의 스크립트 본문(스냅샷)·TC 소스 버전(SSOT·OpenAPI 해시)·대상(<span class="mono">{e(target)}</span>)이 실행 기록에 고정된다. 나중에 스크립트나 TC 가 바뀌어도 과거 기록은 그대로다.</li>
<li><b>러너가 순서대로 보낸다.</b> 한 번에 실행 하나, 스크립트는 순차, 단계는 요청 → 응답 → 검증 항목(assertion)(expect 5종: status · result · error_code · json · exists). 테스트 계정이 필요하면 <span class="mono">POST /v1/auth/dev-sessions</span> 로 토큰을 받아 Bearer 로 보낸다(기록에는 마스킹).</li>
<li><b>판정.</b> 검증 항목(assertion) 불일치 = <b>fail</b>, 예외·네트워크 = <b>error</b>, 테스트 계정·픽스처 미설정 = <b>skipped</b>(설정 문제, 실패 아님). 실행 전체의 결과는 스크립트 결과의 합. Slack 에 시작·종료가 간다.</li>
<li><b>실패하면</b> 실행 상세에서 단계별 요청·응답·검증 항목(assertion)을 본다. [Hermes 실패 분석] 을 누르면 AI 가 <i>버그 / 스크립트 노후 / 환경</i> 중 하나로 분류하고 다음 행동을 제안한다. 진단도 사람이 누를 때만 돈다.</li>
</ol>
<p class="small mut">모든 버튼은 감사 로그 화면(감사 로그)에 담당자·세션 해시·IP 와 함께 남는다. 세션은 팀 공용이라 담당자는 자기 신고다.</p>"""

    s2 = f"""
<p>플랫폼은 TC 를 <b>만들지 않는다</b>. 원본에서 <b>파생</b>하고 같은 입력이면 같은 TC 목록이 나온다.</p>
<table><tr><th>층</th><th>원본</th><th>TC 예</th><th>답하는 질문</th></tr>
<tr><td>정책</td><td><a href="{e(wiki_url)}/policy/">상태-SSOT.yaml</a> (기획 SSOT) — team-wiki-v2 의 <span class="mono">render_tests.cases()</span> 를 그대로 가져와 쓴다</td><td><span class="mono">G.room.create#duplicate-slot-left</span> (게이트 8번째 검사에서 거절) · <span class="mono">C.room.create</span> (성공 전이)</td><td>기획이 정한 규칙이 지켜지는가</td></tr>
<tr><td>계약</td><td>백엔드 OpenAPI (dev 브랜치, REST Docs 산출물)</td><td><span class="mono">op.createRoom:200</span> · <span class="mono">op.createRoom:E1402</span></td><td>API 가 문서대로 응답하는가</td></tr>
<tr><td>수동 작성</td><td>사람이 적는 <span class="mono">qa-platform/catalog/manual-tc.yaml</span> (PRD 절 · 운영 기준)</td><td><span class="mono">PRD.룸-탐색.4.1#1</span> · <span class="mono">OPS.platform.health#1</span></td><td>SSOT 로 형식화되지 않은 요구</td></tr></table>
<p><b>기획과 API 는 1:1 이 아니다.</b> 그래서 <span class="mono">catalog/bindings.yaml</span> 이 SSOT command ↔ operationId, 게이트 검사 ↔ 에러 코드를 잇는다(다대다 허용). 못 잇는 것은 "API 없음" 으로 남는다. 자동화할 수 없는 TC(시스템 전이·OAuth·담당자 전용)는 <span class="mono">catalog/exclusions.yaml</span> 에 <b>사유와 함께</b> 뺀다. 분모에서 빠지지만 화면에는 보인다.</p>
<p><b>스크립트는 <span class="mono">covers:</span> 로 어떤 TC 를 검증하는지 선언</b>하고 플랫폼이 그 선언을 검증한다 — TC id 가 실재하는지, API 계약 TC 라면 단계의 method·path·기대 코드가 실제로 그 계약과 맞는지. 거짓 선언은 "불일치" 로 스위트에서 빠진다. 커버리지 분모는 전체 TC 다.</p>
<p><b>TC 가 바뀌면.</b> 위키 SSOT 나 OpenAPI 가 바뀌면 TC 목록이 다시 계산되고(읽기라 자동), 검증하는 TC 가 바뀐 스크립트에 <span class="b drift">TC 변경</span> 배지가 붙는다. 스크립트를 다시 본 뒤 <span class="mono">reviewed: {{at, by}}</span> 를 적으면 그 이후 변경만 배지로 뜬다. 스크립트를 자동으로 고치거나 테스트를 자동으로 돌리지는 않는다.</p>"""

    s3 = """
<table><tr><th>화면</th><th>언제 여나</th><th>하는 일</th></tr>
<tr><td><a href="/">대시보드</a></td><td>매일</td><td>미검증 dev 배포, 이번 스프린트 smoke 여부, TC 커버리지 매트릭스, 최근 테스트 실행</td></tr>
<tr><td><a href="/runs">실행 기록</a></td><td>실행 후</td><td>테스트 실행 목록·상세(단계별 요청·응답·검증 항목(assertion)), Hermes 실패 분석, 릴리스 판단 기록</td></tr>
<tr><td><a href="/cases">테스트 스크립트</a></td><td>스크립트 관리</td><td>원본은 git <span class="mono">qa-platform/cases/*.yaml</span>. 정합성·TC 변경 배지·실행 이력. [파일에서 다시 읽기]</td></tr>
<tr><td><a href="/catalog">테스트 케이스</a></td><td>커버리지 확인 · 스크립트 늘릴 때</td><td>도메인×층 TC 목록, 검증하는 스크립트, API 매핑, 제외 사유, 스펙 불일치 경고(스펙 누락 등). TC 를 골라 [Hermes 가 스크립트 쓰기] 또는 [직접 쓰기 (폼)]</td></tr>
<tr><td><a href="/drafts">변경 기록</a></td><td>누가 무엇을 바꿨나 볼 때</td><td>폼·Hermes 가 저장한 스크립트·수동 작성 TC 변경과 커밋 링크. 저장은 초안·승인 없이 바로 된다</td></tr>
<tr><td><a href="/chat">Hermes</a></td><td>물어볼 때</td><td>Hermes 와 대화. 실행·스크립트·TC 상세의 [Hermes 와 이야기] 로 그 객체를 첨부해 연다. Hermes 가 부른 도구와 저장한 스크립트가 대화에 남는다</td></tr>
<tr><td><a href="/apis">API</a></td><td>"이 API 검증이 어디까지 됐지" 할 때</td><td>API 하나를 축으로 모아 본다 — 스펙(파라미터·예시·에러 코드), 그 API 에 해당하는 TC(층별, 자동화 여부), 호출하는 스크립트, 최근 호출 20건(스크립트 실행·API 호출 전송 모두). 목록에서 "호출하는 스크립트 없음" 필터가 테스트 커버리지가 비는 API</td></tr>
<tr><td><a href="/setup">테스트 데이터 만들기</a></td><td>손으로 볼 데이터가 필요할 때</td><td>버튼 하나로 dev 에 테스트 데이터를 만든다(모집 중인 룸, 신청 들어온 룸, 확정된 룸). 입력 몇 개 넣고 [실행] → 결과값(roomId 등)이 표로 나오고 API 호출 화면의 입력칸에 최근에 넣은 값으로 뜬다. 만든 데이터는 같은 화면 아래 "QA 데이터 정리"에서 지운다(dev 전용 API, [QA] 제목만). 스크립트는 <span class="mono">cases/setup.yaml</span> 의 <span class="mono">suite: setup</span> — <span class="mono">inputs</span>(입력칸) · <span class="mono">outputs</span>(돌려줄 save 변수) · <span class="mono">{{input.x}}</span> 치환</td></tr>
<tr><td><a href="/explorer">API 호출</a></td><td>손으로 확인할 때</td><td>OpenAPI 로 만든 입력 폼에서 dev 에 한 번 보낸다. <b>Normal</b> 은 값만 넣는 입력 폼, <b>Swagger</b> 는 실제로 나가는 요청 원문(메서드·경로·파라미터·JSON) — 같은 값을 두 모양으로 본다. 폼 위의 배지가 그 API 의 TC 수와 자동화 상태. ☆ 즐겨찾기와 한 번 넣은 path·query 값은 이 브라우저에 기억된다. 보낸 것은 실행 기록에 남고, 응답을 [스크립트 단계로 담기]</td></tr>
<tr><td><a href="/activity">감사 로그</a></td><td>누가 뭘 했는지</td><td>감사 로그 전부</td></tr></table>"""

    s4 = """
<ol>
<li><b>PR 을 dev 에 머지한다.</b> 백엔드 CI 가 dev 에 배포하면 대시보드 "dev 배포" 에 <span class="b warn">미검증</span> 으로 뜬다 (GitHub Actions 조회, 1분 캐시).</li>
<li><b>[검증] 을 누른다.</b> 플랫폼이 PR 변경 파일에서 도메인을 읽어 그 도메인의 sanity 를 제안한다. 확인하고 실행. 통과하면 그 배포에 ✅ 가 붙는다.</li>
<li><b>실패하면 셋 중 하나다.</b> (a) 버그 → 고친다. (b) 스크립트 노후 — 기획이 바뀌어 스크립트가 틀렸다 → 스크립트 상세의 [폼으로 고치기] → 저장. (c) 환경 — 픽스처(공고 id 등)가 바뀜 → SSM <span class="mono">qa-fixtures</span> 를 고친다. Hermes 실패 분석이 셋 중 무엇인지 제안한다.</li>
<li><b>새 기능이면 TC 를 먼저 본다.</b> 기획이 SSOT 에 반영돼 있으면 테스트 케이스 화면에 TC 가 이미 있다. 없으면 위키(SSOT/PRD)를 먼저 고친다. 플랫폼에서 TC 를 직접 만들지 않는다. API 가 새로 생겼으면 <span class="mono">catalog/bindings.yaml</span> 에 command ↔ operationId 를 잇는다.</li>
<li><b>스크립트를 늘린다.</b> 테스트 케이스 화면에서 미자동화 TC 를 골라 [Hermes 가 스크립트 쓰기] 또는 [직접 쓰기 (폼)]. 폼은 [저장 전에 한 번 실행해 보기] 로 먼저 돌려 볼 수 있다. 저장하면 플랫폼이 <span class="mono">qa-platform/cases/&lt;도메인&gt;.yaml</span> 에 커밋하고 바로 실행 스위트에 넣는다. 사람이 직접 쓰려면 [+ 새 스크립트 (폼)]. 검증을 통과하지 못한 스크립트는 저장되지 않는다.</li>
<li><b>쓰기 스크립트 규칙.</b> 만든 데이터는 같은 스크립트 안에서 닫고(취소·철회·삭제) 만드는 데이터의 title 은 <span class="mono">[QA]</span> 로 시작한다. 테스트 계정(qa-host · qa-guest)만 쓴다 — 목데이터 회원은 참여 슬롯이 차 있어 쓰기에 못 쓴다.</li>
</ol>"""

    s5 = f"""
<ul>
<li><b>스프린트마다 한 번</b> ({sprint_days}일 주기, Linear 사이클과 같은 번호) 대시보드에서 [스프린트 smoke 실행]. 배지가 "미실행" 이면 아직 안 한 것이다. 마감 하루 전까지 없으면 Slack 에 한 번 알린다 — 알림만 하고 실행은 하지 않는다.</li>
<li><b>실배포 전</b> [릴리스 검증] → smoke 전체 실행 → 실행 상세의 릴리스 체크리스트(백엔드 <span class="mono">docs/knowledge/release-checklist.md</span> 에서 읽어 옴)를 확인하고 GO / NO-GO 를 <b>기록</b>한다. 기록만 하고 승격을 막지는 않는다.</li>
<li><b>보고서.</b> 스프린트·릴리스 실행은 [위키에 보고서 게시] 로 llm-wiki <span class="mono">wiki/qa/</span> 에 남길 수 있다. 사람이 누를 때만, 개인 식별값은 마스킹.</li>
</ul>"""

    s6 = f"""
<p><b>왜 자동으로 안 도나?</b> 결정이다. 실행의 시작은 언제나 사람이어야 이력에 의미가 있고 dev 데이터 오염·실행 폭주·알림 피로가 구조적으로 막힌다. TC 목록 <i>계산</i>은 읽기라 자동이지만 실행·전송·Hermes 호출·발행은 전부 버튼이다.</p>
<p><b>skipped 는 실패인가?</b> 아니다. 테스트 계정(<span class="mono">qa-actors</span>)이나 픽스처(<span class="mono">qa-fixtures</span>)가 없어 못 보낸 것이다. 설정을 먼저 본다.</p>
<p><b>스펙 불일치 경고는?</b> 매핑한 에러 코드가 OpenAPI 예시에 없다는 뜻이다(예: E1425·E1427 은 dev 에서 확인됐지만 스펙에 아직 없음). 백엔드 REST Docs 에 예시를 추가하면 사라진다.</p>
<p><b>원본은 어디?</b> 스크립트 = git <span class="mono">qa-platform/cases/</span>. TC = llm-wiki SSOT·PRD + OpenAPI. API 매핑·자동화 제외·수동 작성 TC = <span class="mono">qa-platform/catalog/</span>. DB 에는 실행 기록·감사 로그·변경 기록만 있다.</p>
<p class="small mut">설계 문서: <span class="mono">docs/qa-platform.md</span>(P0·P1, 런북) · <span class="mono">docs/qa-platform-tc.md</span>(P2, 기준 관리). 이 화면은 <span class="mono">{e(public_url)}/guide</span>.</p>"""

    s_ai = """
<p><b>런타임에는 AI 가 없다.</b> 실행 버튼을 누르면 도는 것은 결정론 러너다 — 스크립트에 적힌 요청을 보내고 적힌 검증 항목(assertion)과 비교한다. 같은 스크립트·같은 서버면 같은 판정이 나온다. 매 실행마다 LLM 이 판단하면 비용이 들고 결과가 흔들리고 이력을 믿을 수 없어서 설계에서 뺐다.</p>
<p><b>TC 도 AI 가 만들지 않고</b> SSOT·OpenAPI 에서 규칙으로 파생된다(§2). AI 가 TC 를 만들면 검증 기준이 원본에서 떠난다.</p>
<p>AI(Hermes)가 개입하는 지점은 <b>셋이고, 셋 다 실행·발행 버튼에는 손이 닿지 않는다.</b></p>
<table><tr><th>시점</th><th>버튼</th><th>AI 가 하는 것</th><th>AI 가 못 하는 것</th></tr>
<tr><td>스크립트를 늘릴 때</td><td>테스트 케이스 화면 [Hermes 가 스크립트 쓰기]</td><td>고른 TC + OpenAPI 발췌 + PRD 절 본문을 근거로 스크립트 YAML 을 쓴다</td><td>플랫폼의 결정론 검증(covers ⊆ 요청 TC, method·path·코드 일치, 테스트 계정 실재)을 통과한 것만 저장된다. 저장된 것에는 "Hermes 작성" 표시가 붙고, 실행은 사람이 누른다</td></tr>
<tr><td>테스트 실행이 실패한 뒤</td><td>실행 상세 [Hermes 실패 분석]</td><td>단계별 요청·응답·검증 항목(assertion)만 보고 <i>버그 / 스크립트 노후 / 환경</i> 중 하나로 분류하고 다음 행동을 제안한다</td><td>판정을 바꾸지 못한다. 분석 결과는 실행 기록의 스크립트에 메모로 붙을 뿐이다</td></tr>
<tr><td>Hermes 에게 물을 때 (<a href="/chat">Hermes</a> 화면 · Slack)</td><td>대화</td><td>QA 도구(<span class="mono">qa_*</span> 14개)로 테스트 케이스·스크립트·실행 기록·커버리지·OpenAPI·PRD 절을 읽고 답한다. 스크립트를 쓰거나 고치면 검증을 거쳐 바로 저장하고, PRD 절에서 뽑은 수동 작성 TC 도 바로 저장한다</td><td>테스트 실행·API 직접 호출·위키 보고서 게시 도구가 <b>서버에 없다</b>. "돌려 줘" 라고 하면 이 화면의 링크를 준다. 부른 도구는 전부 감사 로그 화면에 <span class="mono">hermes</span> 이름으로 남는다</td></tr></table>
<p class="small mut">[Hermes 가 스크립트 쓰기] 버튼 경로에서는 위키 도구를 AI 에게 주지 않는다. 근거는 플랫폼이 프롬프트에 넣어 주므로 Hermes 가 쓴 스크립트가 무엇을 근거로 했는지가 해시로 남고 검증이 그 근거와 맞춰 볼 수 있다. 런타임에 AI 가 탐색적으로 API 를 두드리는 "에이전트 런" 은 만들지 않았다. 필요하면 별도 결정이다.</p>"""
    s_terms = """
<p class="small mut" style="margin-top:0">이 화면들에서 쓰는 말. 일반 QA 용어를 따르고, 코드·URL 의 영어 키(run, case, catalog, covers, audit)는 그대로 둔다.</p>
<table><tr><th>말</th><th>뜻</th><th>영어 · 코드</th></tr>
<tr><td><b>테스트 케이스 (TC)</b></td><td>"무엇을 확인해야 하는가" 한 건. 기획(SSOT·PRD)과 API 계약(OpenAPI)에서 규칙으로 뽑는다. 사람이 손으로 쓰지 않는다(수동 작성 층만 예외). id 는 <span class="mono">G.room.create#duplicate-slot-left</span>, <span class="mono">op.createRoom:E1402</span> 같은 꼴</td><td>test case · <span class="mono">catalog</span></td></tr>
<tr><td><b>테스트 스크립트</b></td><td>TC 를 실제로 확인하는 실행 단위. 요청·기대 응답을 적은 YAML 이고 git 이 원본. 스크립트 하나가 TC 여러 건을 검증할 수 있다</td><td>test script · <span class="mono">cases/*.yaml</span></td></tr>
<tr><td><b>검증하는 TC</b></td><td>스크립트가 "이 TC 들을 확인한다" 고 선언한 목록. 커버리지의 근거</td><td><span class="mono">covers</span></td></tr>
<tr><td><b>정합성</b></td><td>스크립트의 선언이 TC 목록·API 계약과 맞는지 플랫폼이 검사한 결과. 정합 / 경고 / 불일치. 불일치면 스위트에서 빠진다</td><td><span class="mono">audit</span></td></tr>
<tr><td><b>TC 변경</b></td><td>스크립트가 검증하는 TC 가 마지막 검토 이후 바뀌었다는 표시. 기획이나 API 가 바뀐 것이니 스크립트를 다시 본다</td><td>drift</td></tr>
<tr><td><b>자동화됨 · 미자동화 · 자동화 제외</b></td><td>TC 를 검증하는 스크립트가 있음 · 없음 · 자동으로 확인할 수 없어 사유와 함께 뺌</td><td>covered · uncovered · excluded</td></tr>
<tr><td><b>API 매핑</b></td><td>SSOT 의 기능(command)·검사와 OpenAPI 의 operation·에러 코드를 잇는 표. 1:1 이 아니라 사람이 적는다</td><td><span class="mono">catalog/bindings.yaml</span></td></tr>
<tr><td><b>스펙 불일치 경고</b></td><td>API 매핑이 가리키는 operation 이나 에러 코드가 OpenAPI 에 없을 때</td><td>catalog warnings</td></tr>
<tr><td><b>테스트 실행</b></td><td>사람이 버튼을 눌러 스크립트 묶음을 dev 에 한 번 돌린 기록. 결과·단계별 요청·응답이 남고 바뀌지 않는다</td><td>test run · <span class="mono">/runs</span></td></tr>
<tr><td><b>실행 종류</b></td><td>배포 검증 · 스프린트 smoke · 릴리스 QA · 수동 실행 · 저장 전 실행 · API 호출</td><td>trigger</td></tr>
<tr><td><b>도메인</b></td><td>기능 영역. 룸 · 신청 · 참여 · 회원 · 이력서 · 질문 … PR 변경 파일과 API 경로에서 읽는다</td><td>domain</td></tr>
<tr><td><b>Hermes</b></td><td>팀 AI 비서. 여기서는 실패 원인 분석·스크립트 쓰기·질문 답변만 한다. 실행·발행은 사람</td><td>hermes-gateway</td></tr>
<tr><td><b>스위트</b></td><td>스크립트 묶음. smoke(읽기 전용, 빠름) · sanity(쓰기 포함, 도메인별) · manual(직접 고를 때만)</td><td>suite</td></tr>
<tr><td><b>검증 항목</b></td><td>단계마다 응답을 비교하는 조건. status · result · error_code · json 경로 · 존재 여부</td><td>assertion · <span class="mono">expect</span></td></tr>
<tr><td><b>테스트 계정 · 픽스처</b></td><td>dev 에 있는 QA 전용 회원 · 스크립트가 참조하는 dev 데이터 id(공고 id 등). 값은 SSM 에만</td><td><span class="mono">actor</span> · fixture</td></tr>
<tr><td><b>변경 기록</b></td><td>폼·Hermes 가 스크립트·수동 작성 TC 를 저장한 기록. 저장은 검증을 거쳐 main 에 바로 커밋된다. Hermes 가 쓴 것에는 "Hermes 작성" 표시가 붙고, 사람이 폼으로 저장하면 사라진다</td><td>draft</td></tr>
<tr><td><b>Hermes 작업</b></td><td>스크립트 쓰기·TC 제안·고치기·실패 분석처럼 Hermes 를 부르는 일. 뒤에서 돌고 진행이 실시간으로 보인다</td><td>job</td></tr>
<tr><td><b>Normal · Swagger 보기</b></td><td>같은 요청을 두 모양으로 본다. Normal 은 값만 넣는 입력 폼, Swagger 는 실제로 나가는 요청 원문(메서드·경로·파라미터·JSON 본문, 편집 가능). 토스 QA 플랫폼의 용례를 따랐다</td><td>view</td></tr>
<tr><td><b>테스트 데이터 만들기</b></td><td>여러 API 를 순서대로 호출해 dev 에 데이터(룸 등)를 만드는 스크립트를 버튼 하나로 돌리는 것. 입력칸(<span class="mono">inputs</span>)과 결과값(<span class="mono">outputs</span>)이 있고 만든 데이터는 지우지 않는다</td><td>suite <span class="mono">setup</span></td></tr>
<tr><td><b>최근 통계 · 불안정 (flaky)</b></td><td>스크립트나 API 의 최근 20회 통과율(skip 은 뺀다)과 평균 소요. 불안정 = 스크립트를 안 고쳤는데 최근 10회 안에서 통과↔실패가 2번 이상 뒤집힘 — dev 데이터·타이밍 문제를 의심한다</td><td>pass rate · flaky</td></tr>
<tr><td><b>최근 호출</b></td><td>어떤 API 를 호출한 단계들을 최신순으로 모은 것 — 스크립트 실행과 API 호출 화면 전송 모두. "이 API 지난번에 어땠나" 의 답</td><td><span class="mono">run_steps.op_id</span></td></tr>
<tr><td><b>담당자</b></td><td>버튼을 누른 사람. 팀 세션은 공용이라 본인이 고른다(자기 신고)</td><td><span class="mono">operator</span></td></tr>
<tr><td><b>감사 로그</b></td><td>누가 언제 무엇을 했는지 전부. Hermes 가 부른 도구도 <span class="mono">hermes</span> 이름으로 남는다</td><td>audit log · <span class="mono">events</span></td></tr></table>"""
    return (intro + _sec("개발 과정에서 이렇게 쓴다 — 예시 하나와 함께", s_howto) + '<div id="terms"></div>' + _sec("용어", s_terms) + _sec("1. 실행 버튼을 누르면 무슨 일이 일어나나", s1) + _sec("2. 검증 기준(TC)은 어디서 오나", s2)
            + _sec("3. AI 는 언제 개입하나", s_ai)
            + _sec("4. 화면별로 무엇을 하나", s3) + _sec("5. 기능을 개발하고 나면 — 개발자 워크플로우", s4)
            + _sec("6. QA 워크플로우 — 스프린트와 릴리스", s5) + _sec("7. 자주 묻는 것", s6))


# ---- Hermes 대화 (docs/qa-platform-hermes.md §3.2) ----------------------------------------------
def _operator_select(operator: str, operators: list[str]) -> str:
    ops = "".join(f'<option value="{e(o)}" {"selected" if o == operator else ""}>{e(o)}</option>' for o in operators)
    return (f'<select onchange="document.cookie=\'qa_operator=\'+this.value+\';path=/;max-age=31536000\';location.reload()">'
            f'<option value="">— 담당자 —</option>{ops}</select>')


def _ctx_label(ctx: dict) -> str:
    if ctx.get("run"):
        return f'실행 <a href="/runs/{e(ctx["run"])}" class="mono">{e(ctx["run"])}</a>'
    if ctx.get("case"):
        return f'스크립트 <a href="/cases/{e(ctx["case"])}" class="mono">{e(ctx["case"])}</a>'
    if ctx.get("tc"):
        return f'TC {tc_link(ctx["tc"])}'
    if ctx.get("op"):
        return f'API <a href="/apis/{e(ctx["op"])}" class="mono">{e(ctx["op"])}</a>'
    return "–"


def chats_list(chats: list[dict], *, stale: dict, hermes: bool, operator: str, operators: list[str]) -> str:
    warn = "" if hermes else '<div class="flash err">HERMES_API_KEY 가 없어 Hermes 와 이야기할 수 없다.</div>'
    rows = "".join(
        f'<tr><td><a href="/chat/{e(c["id"])}">{e(c.get("title") or "(제목 없음)")}</a></td><td>{_ctx_label(c["context"])}</td>'
        f'<td>{badge("닫힘", "skipped") if c["status"] != "open" else (badge("오래됨", "skipped") if stale.get(c["id"]) else badge("열림", "pass"))}</td>'
        f'<td class="right">{c["turns"]}</td><td class="right">{c["drafts"]}</td><td>{e(c["operator"])}</td><td class="small mut">{kst(c["updated_at"])}</td></tr>'
        for c in chats) or '<tr><td colspan="7" class="mut">대화 없음</td></tr>'
    return (f'<h1>Hermes{h("hermes.widget")}{h("hermes.list")} <span class="small mut">QA 를 아는 Hermes 와 이야기한다 — 테스트 케이스·스크립트·실행 기록을 읽고, 스크립트를 쓰고, 실패를 해석한다</span></h1>{warn}'
            f'<div class="card"><div class="actions"><a class="btn" href="/chat/new">새 대화</a> <span class="small mut">실행·스크립트·TC 상세의 [Hermes 와 이야기] 로 열면 그 객체가 첨부된다. '
            f'실행·발행은 Hermes 가 못 한다 — 사람이 버튼을 누른다.</span></div></div>'
            f'<div class="card"><table><tr><th>제목</th><th>첨부{h("hermes.attach")}</th><th>상태</th><th>턴</th><th>저장</th><th>담당자</th><th>마지막</th></tr>{rows}</table></div>')


# ---- Hermes 위젯 스크립트 (/static/hermes.js). 표준 라이브러리 서버라 문자열로 낸다 ---------------------------
HERMES_JS_VERSION = "4"
HELP_JS_VERSION = "3"
HERMES_JS = r"""
(function(){
  var Q = window.QA || {}; var SFX = Q.operator ? (':'+Q.operator) : ''; var LS_ID='qa_chat_id'+SFX, LS_OPEN='qa_chat_open'+SFX;   // 담당자별
  var st = {id:null, view:'thread', busy:false, chat:null};
  function h(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function el(tag, cls, html){var x=document.createElement(tag); if(cls) x.className=cls; if(html!=null) x.innerHTML=html; return x;}
  function kst(iso){ if(!iso) return ''; var d=new Date(iso); return isNaN(d)?'':d.toLocaleString('ko-KR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}); }
  function linkify(t){ return h(t).replace(/(https?:\/\/[^\s<]+)/g,'<a href="$1">$1</a>').replace(/\b(d-[0-9a-f]{8})\b/g,'<a href="/drafts/$1" class="mono">$1</a>'); }
  function ctxLabel(c){ c=c||{}; if(c.run) return '실행 <a href="/runs/'+h(c.run)+'" class="mono">'+h(c.run)+'</a>'; if(c.case) return '스크립트 <a href="/cases/'+h(c.case)+'" class="mono">'+h(c.case)+'</a>'; if(c.tc) return 'TC <a href="/catalog/tc?id='+encodeURIComponent(c.tc)+'" class="mono">'+h(c.tc)+'</a>'; if(c.op) return 'API <a href="/apis/'+h(c.op)+'" class="mono">'+h(c.op)+'</a>'; return ''; }

  // ---- DOM ----
  var inline = !!Q.inline, root = inline ? document.getElementById('hx-inline') : document.body;
  var btn = null;
  if(!inline){ btn = el('button','', 'Hermes'); btn.id='hx-btn'; document.body.appendChild(btn); btn.onclick=function(){ toggle(); }; }
  var box = el('div', inline ? 'inline' : ''); box.id='hx';
  box.innerHTML = '<div class="hx-head"><span class="t">Hermes</span><button data-a="list" title="대화 목록">목록</button><button data-a="new">새 대화</button>'+(inline?'':'<button data-a="close" title="닫기">×</button>')+'</div>'
    + '<div class="hx-body"></div>'
    + '<div class="hx-foot"><textarea placeholder="Hermes 에게 물어본다. Enter 전송, Shift+Enter 줄바꿈" rows="2"></textarea><div class="row"><span class="st"></span><button class="primary">보내기</button></div></div>';
  root.appendChild(box);
  var body = box.querySelector('.hx-body'), ta = box.querySelector('textarea'), sendBtn = box.querySelector('.hx-foot button'), stEl = box.querySelector('.st'), title = box.querySelector('.t');
  box.querySelector('.hx-head').onclick = function(ev){ var a = ev.target.getAttribute && ev.target.getAttribute('data-a'); if(a==='close') toggle(false); if(a==='list') showList(); if(a==='new') startNew(Q.context); };
  sendBtn.onclick = send; ta.onkeydown = function(ev){ if((ev.key==='Enter' || ev.keyCode===13) && !ev.shiftKey && !ev.isComposing){ ev.preventDefault(); send(); } };

  function toggle(on){ if(inline) return; var open = on==null ? !box.classList.contains('open') : on; box.classList.toggle('open', open); try{localStorage.setItem(LS_OPEN, open?'1':'');}catch(e){} if(open && !st.loaded){ st.loaded=true; if(st.id) loadThread(st.id); else showNew(Q.context); } if(open) ta.focus(); }
  function note(msg, cls){ body.innerHTML=''; body.appendChild(el('div','hx-note'+(cls?' '+cls:''), msg)); }
  function status(t){ stEl.textContent = t||''; }
  function setBusy(b){ st.busy=b; sendBtn.disabled=b; ta.disabled=b; }

  // ---- 담당자·Hermes 없음 ----
  function guard(){
    if(!Q.hermes){ note('HERMES_API_KEY 가 없어 Hermes 와 이야기할 수 없다.'); return false; }
    if(!Q.operator){ var ops=(Q.operators||[]).map(function(o){return '<option value="'+h(o)+'">'+h(o)+'</option>';}).join('');
      note('먼저 담당자를 고른다 — 대화와 저장한 것이 이 이름으로 남는다.<p><select id="hx-op"><option value="">— 담당자 —</option>'+ops+'</select></p>');
      body.querySelector('#hx-op').onchange=function(){ if(this.value){ document.cookie='qa_operator='+encodeURIComponent(this.value)+';path=/;max-age=31536000'; location.reload(); } };
      return false; }
    return true;
  }

  // ---- 화면 ----
  function showNew(ctx){
    st.id=null; st.chat=null; st.view='new'; st.ctx = ctx||{}; title.textContent='새 대화';
    if(!guard()) return;
    var lab = ctxLabel(st.ctx);
    body.innerHTML = '<div class="hx-note">QA 를 아는 Hermes 다 — 테스트 케이스·스크립트·실행 기록을 읽고, 스크립트를 쓰고, 실패를 해석한다. 실행·발행은 못 한다(사람이 버튼).'+
      (lab ? '<p><label><input type="checkbox" id="hx-attach" checked> 이 화면의 '+lab+' 을 첨부</label></p>' : '')+'</div>';
    setBusy(false); status(''); ta.focus();
  }
  function startNew(ctx){ try{localStorage.removeItem(LS_ID);}catch(e){} showNew(ctx); }
  function showList(){
    st.view='list'; title.textContent='대화 목록'; if(!guard()) return; note('불러오는 중…');
    fetch('/api/chats').then(function(r){return r.json();}).then(function(d){
      var wrap = el('div','hx-list');
      if(!d.chats.length) wrap.appendChild(el('div','hx-note','대화 없음'));
      d.chats.forEach(function(c){ var a = el('a','', h(c.title||'(제목 없음)')+'<small>'+(c.status!=='open'?'닫힘 · ':(c.stale?'오래됨 · ':''))+c.turns+'턴 · 저장 '+c.drafts+' · '+h(c.operator)+' · '+kst(c.updated_at)+'</small>'); a.href='#'; a.onclick=function(ev){ev.preventDefault(); loadThread(c.id);}; wrap.appendChild(a); });
      body.innerHTML=''; body.appendChild(wrap);
    }).catch(function(e){ note('목록을 못 읽었다: '+h(e)); });
  }
  function loadThread(id){
    st.view='thread'; if(!guard()) return; note('불러오는 중…');
    fetch('/api/chats/'+id).then(function(r){ if(!r.ok) throw new Error('없는 대화'); return r.json(); }).then(function(d){
      st.id=id; st.chat=d.chat; try{localStorage.setItem(LS_ID,id);}catch(e){}
      title.textContent = d.chat.title || '대화';
      body.innerHTML=''; var lab = ctxLabel(d.chat.context); if(lab) body.appendChild(el('div','hx-note','첨부: '+lab));
      d.messages.forEach(function(m){ renderMsg(m, d.drafts||{}); });
      var closed = d.chat.status!=='open' || d.stale || d.chat.turns>=d.max_turns;
      setBusy(closed); status(closed ? (d.chat.status!=='open'?'닫힌 대화':(d.stale?'오래된 대화 — 새 대화를 연다':'턴 한도 — 새 대화를 연다')) : d.chat.turns+'/'+d.max_turns+' 턴');
      body.scrollTop = body.scrollHeight;
    }).catch(function(e){ try{localStorage.removeItem(LS_ID);}catch(x){} showNew(Q.context); });
  }
  function renderMsg(m, drafts){
    var d = el('div','msg '+m.role+(m.error?' err':''));
    d.innerHTML = '<div class="who">'+(m.role==='user'?h((st.chat&&st.chat.operator)||Q.operator||'나'):'Hermes')+' · '+kst(m.at)+(m.ms?' · '+Math.round(m.ms/1000)+'초':'')+'</div><div class="tx">'+linkify(m.content)+'</div>';
    (m.tool_calls||[]).forEach(function(c){ d.appendChild(chip(c.name, c.arguments, c.output)); });
    if(m.draft_ids && m.draft_ids.length){ d.appendChild(el('div','small','저장한 것: '+m.draft_ids.map(function(x){ return '<a href="/drafts/'+h(x)+'" class="mono">'+h(x)+'</a>'+(drafts[x]?' ('+h(drafts[x])+')':''); }).join(' '))); }
    body.appendChild(d); return d;
  }
  function chip(name, args, out){
    var a = typeof args==='string'?args:JSON.stringify(args||{}); var o = out==null?null:(typeof out==='string'?out:JSON.stringify(out));
    var c = el('span','tc'+(o==null?' run':''), h(name)+'<pre>'+h('인자 '+(a||'').slice(0,1500)+'\n결과 '+(o==null?'(진행 중)':o.slice(0,2500)))+'</pre>');
    c.onclick=function(){ c.classList.toggle('on'); }; return c;
  }

  // ---- 전송 (SSE) ----
  function send(){
    if(st.busy || !guard()) return; var text = ta.value.trim(); if(!text) return;
    var go = function(){ ta.value=''; setBusy(true); status('Hermes 에게 보냈다…');
      var um = renderMsg({role:'user', content:text, at:new Date().toISOString()}, {});
      var am = el('div','msg assistant'); am.innerHTML='<div class="who">Hermes</div><div class="tx cur"></div>'; body.appendChild(am);
      var tx = am.querySelector('.tx'), chips = {}, buf='';
      body.scrollTop = body.scrollHeight;
      fetch('/api/chats/'+st.id+'/send', {method:'POST', headers:{'Content-Type':'application/json','Accept':'text/event-stream'}, body:JSON.stringify({text:text})})
      .then(function(r){ if(!r.ok) return r.text().then(function(t){ throw new Error(t||r.status); }); var rd = r.body.getReader(), dec = new TextDecoder(), acc='';
        function pump(){ return rd.read().then(function(x){ if(x.done){ return; } acc += dec.decode(x.value,{stream:true}); var parts = acc.split('\n\n'); acc = parts.pop();
          parts.forEach(function(fr){ var ev='message', data=''; fr.split('\n').forEach(function(l){ if(l.indexOf('event:')===0) ev=l.slice(6).trim(); else if(l.indexOf('data:')===0) data+=l.slice(5).trim(); });
            if(!data) return; var d; try{ d=JSON.parse(data);}catch(e){return;} on(ev,d); });
          return pump(); }); }
        return pump(); })
      .catch(function(e){ tx.classList.remove('cur'); am.classList.add('err'); tx.textContent='전송 실패: '+e.message; setBusy(false); status(''); });
      function on(ev, d){
        if(ev==='delta'){ buf += d.text; tx.innerHTML = linkify(buf); body.scrollTop = body.scrollHeight; }
        else if(ev==='tool'){ status('도구를 쓰는 중: '+d.name); var c = chip(d.name, d.arguments, null); chips[d.call_id]=c; am.appendChild(c); body.scrollTop = body.scrollHeight; }
        else if(ev==='tool_result'){ var c2 = chips[d.call_id]; if(c2){ c2.classList.remove('run'); c2.querySelector('pre').textContent = c2.querySelector('pre').textContent.replace('(진행 중)', d.output||''); } status('생각하는 중…'); }
        else if(ev==='done'){ tx.classList.remove('cur'); if(d.error){ am.classList.add('err'); tx.textContent=d.content; } else if(!buf) tx.innerHTML=linkify(d.content);
          if(d.draft_ids && d.draft_ids.length) am.appendChild(el('div','small','저장한 것: '+d.draft_ids.map(function(x){return '<a href="/drafts/'+h(x)+'" class="mono">'+h(x)+'</a>';}).join(' ')));
          if(d.title && st.chat){ st.chat.title=d.title; title.textContent=d.title; } setBusy(false); status((d.turns||'')+' 턴'); ta.focus(); body.scrollTop = body.scrollHeight; }
        else if(ev==='error'){ tx.classList.remove('cur'); am.classList.add('err'); tx.textContent = d.message||'오류'; setBusy(false); status(''); }
      }
    };
    if(st.id) return go();
    var attach = body.querySelector('#hx-attach'); var ctx = (attach && attach.checked) ? st.ctx : {};
    setBusy(true); status('대화를 연다…');
    fetch('/api/chats',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(ctx)}).then(function(r){ if(!r.ok) return r.text().then(function(t){throw new Error(t);}); return r.json(); })
      .then(function(d){ st.id=d.id; st.chat=d.chat; st.view='thread'; try{localStorage.setItem(LS_ID,d.id);}catch(e){} title.textContent=d.chat.title||'대화'; body.innerHTML=''; var lab=ctxLabel(d.chat.context); if(lab) body.appendChild(el('div','hx-note','첨부: '+lab)); go(); })
      .catch(function(e){ setBusy(false); status('대화를 못 열었다: '+e.message); });
  }

  // ---- 시작 ----
  try{ st.id = localStorage.getItem(LS_ID)||null; }catch(e){}
  if(inline){ st.loaded=true; loadThread(Q.inline); }
  else if(Q.autostart){ st.loaded=true; box.classList.add('open'); try{localStorage.setItem(LS_OPEN,'1');}catch(e){} startNew(Q.autostart); }
  else { var open=false; try{ open = localStorage.getItem(LS_OPEN)==='1'; }catch(e){} if(open) toggle(true); }
  window.QA.open = function(ctx){ toggle(true); if(ctx) startNew(ctx); };
})();
"""


# 폼 편집·Hermes 작업 화면 (qa/ui_edit.py) — app 은 ui.editor_page 처럼 여기서 쓴다
from .ui_edit import (EDITOR_JS, EDITOR_JS_VERSION, JOBS_JS, JOBS_JS_VERSION, active_jobs_line,  # noqa: E402,F401
                      editor_page, job_detail, jobs_list, manual_tc_form)
# 시나리오 화면 (qa/ui_scn.py) — 기능·시나리오·변형 트리, 기능 화면, 변형 화면
from .ui_scn import feature_page, scenario_tree, state_badge, tc_variants_card, variant_page, variant_url, variants_of_tc  # noqa: E402,F401
