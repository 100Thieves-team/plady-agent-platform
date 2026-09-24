"""시나리오 화면 — 대시보드 아래 기능·시나리오·변형 트리, 기능 화면, 변형 화면. docs/qa-platform-scenarios.md §12.

ui.py 가 맨 끝에서 이 모듈의 이름을 다시 내보낸다(app 은 ui.scenario_tree 처럼 쓴다). 계산은 qa/scenarios.py 의 overview 가 한다.
"""
from __future__ import annotations

from urllib.parse import quote

from .scenarios import KIND_KO, STATE_KO
from .ui import badge, e, h, kst, tc_link

_GRID = "display:grid;grid-template-columns:minmax(180px,1.4fr) repeat(7,minmax(54px,.5fr)) minmax(120px,1fr);gap:8px;align-items:center"
_VCOLS = '<colgroup><col><col style="width:110px"><col style="width:240px"><col style="width:170px"></colgroup>'     # 시나리오마다 표가 따로라 열 너비를 고정한다
STATE_CLS = {"auto": "covered", "manual": "warn", "excluded": "excluded", "untested": "uncovered"}


def state_badge(st: str) -> str:
    return f'<span class="b {STATE_CLS.get(st, "")}">{e(STATE_KO.get(st, st))}</span>'


def kind_badge(kind: str) -> str:
    return f'<span class="b {"fail" if kind == "reject" else ("pass" if kind == "happy" else "manual")}">{e(KIND_KO.get(kind, kind))}</span>'


def feature_url(slug: str, sid: str | None = None, key: str | None = None) -> str:
    return "/features/" + "/".join(quote(x, safe="") for x in (slug, sid, key) if x)


def variant_url(vid: str) -> str:
    slug, sid, key = vid.split("/", 2)
    return feature_url(slug, sid, key)


def _last(lv: dict | None) -> str:
    if not lv:
        return '<span class="mut small">–</span>'
    return f'<a href="/runs/{e(lv["run_id"])}">{badge(lv["verdict"])}</a> <span class="small mut">{kst(lv.get("created_at"))}</span>'


def _bar(c: dict) -> str:
    tot = c["variants"] or 1
    seg = "".join(f'<i class="{cls}" style="width:{c[k] * 100 / tot:.1f}%" title="{e(STATE_KO[k])} {c[k]}"></i>'
                  for k, cls in (("auto", "p"), ("manual", "r"), ("excluded", "s"), ("untested", "f")) if c[k])
    return f'<div class="bar" title="변형 {c["variants"]}개">{seg}</div>'


def _count_vals(c: dict) -> list[str]:
    """변형 · 자동화됨 · 사람이 확인 · 제외 · 테스트 없음 · 테스트 없는 거절 규칙 · 최근 결과."""
    return [str(c["variants"]) if c["variants"] else '<span class="mut">0</span>', str(c["auto"]), str(c["manual"]), str(c["excluded"]),
            f'<b style="color:var(--bad)">{c["untested"]}</b>' if c["untested"] else "0",
            f'<b style="color:var(--warn)">{c["rejects"]}</b>' if c["rejects"] else "0",
            f'통과 {c["pass"]} · 실패 {c["fail"]}' if (c["pass"] or c["fail"]) else '<span class="mut">–</span>']


def _variant_row(v: dict, *, indent: bool = True) -> str:
    va = v["variant"]
    scripts = " ".join(f'<a href="/cases/{e(c.id)}" class="mono small">{e(c.id)}</a>' for c in v["scripts"]) or '<span class="mut small">–</span>'
    return (f'<tr><td style="padding-left:{36 if indent else 8}px">{kind_badge(va.kind)} <a href="{variant_url(v["id"])}">{e(va.title)}</a>'
            f' <span class="mono small mut">{e(va.key)}</span></td><td>{state_badge(v["state"])}</td><td>{scripts}</td><td>{_last(v["last"])}</td></tr>')


def scenario_tree(ov: list[dict], *, errors: list[str] | None = None, title: str = "기능 · 시나리오 · 변형") -> str:
    """대시보드 아래 트리 (§12). 기능 줄은 합계와 막대, 펼치면 시나리오, 다시 펼치면 변형."""
    if not ov:
        return (f'<h2>{e(title)}{h("dash.scenarios")}</h2><div class="card mut small">위키 체크아웃이 없거나 PRD 가 없다 — 시나리오를 그릴 수 없다</div>')
    rows = ""
    for f in ov:
        c = f["counts"]
        scn = ""
        for s in f["scenarios"]:
            vrows = "".join(_variant_row(v) for v in s["variants"])
            n_rej = len(s["untested_rejects"])
            empty = '<tr><td colspan="4" class="mut small" style="padding-left:36px">변형 없음</td></tr>' if not s["variants"] else ""
            scn += (f'<details style="margin:2px 0 2px 18px"><summary><a class="mono" href="{feature_url(f["slug"])}#{e(s["id"])}">{e(s["id"])}</a> {e(s["title"])}'
                    f' <span class="small mut">변형 {len(s["variants"])}{(" · 테스트 없는 거절 규칙 " + str(n_rej)) if n_rej else ""}</span>'
                    f'{"" if s["in_prd"] else " <span class=\"b fail\">PRD 에 없다</span>"}</summary>'
                    f'<table style="table-layout:fixed">{_VCOLS}{vrows}{empty}</table></details>')
        no_file = "" if f["file"] else ' <span class="small mut">시나리오 파일 없음</span>'
        rows += (f'<tr><td colspan="9" style="padding:0"><details><summary style="padding:7px 8px;{_GRID}">'
                 f'<span><a href="{feature_url(f["slug"])}"><b>{e(f["feature"])}</b></a>{no_file} <span class="small mut">시나리오 {len(f["scenarios"])}</span></span>'
                 + "".join(f'<span class="small">{x}</span>' for x in _count_vals(c))
                 + f'{_bar(c)}</summary>{scn}</details></td></tr>')
    head = (f'<div style="{_GRID};padding:0 8px 6px;color:var(--mut);font-size:12px;font-weight:600">'
            '<span>기능</span><span>변형</span><span>자동화됨</span><span>사람이 확인</span><span>제외</span><span>테스트 없음</span><span>테스트 없는 거절 규칙</span><span>최근 결과</span><span></span></div>')
    errs = "".join(f'<li class="small" style="color:var(--bad)">{e(x)}</li>' for x in errors or [])
    return (f'<h2>{e(title)}{h("dash.scenarios")} <a class="small" href="/features">기능 목록</a></h2>'
            f'{("<div class=\"flash err\"><b>시나리오 파일 오류</b><ul>" + errs + "</ul></div>") if errs else ""}'
            f'<div class="card">{head}<table>{rows}</table>'
            f'<p class="small mut" style="margin-bottom:0">시나리오는 PRD 2장이 정하고, 변형은 <span class="mono">qa-platform/scenarios/</span> 가 더한다. 상태는 스크립트의 <span class="mono">variant:</span>·자동화 제외를 보고 매번 계산한다.</p></div>')


def _steps_html(s: dict, gate_names: dict) -> str:
    gates = (s["scenario"].gates if s["scenario"] else {}) or {}
    lis = ""
    for st in s["steps"]:
        g = gates.get(st.get("req") or "") or []
        chips = "".join(f' <span class="b manual mono" title="{e(gate_names.get(x, ""))}">{e(x)}</span>' for x in g)
        lead = "분기: " if st["branch"] else f'{st["no"]}. '
        lis += (f'<li style="{"margin-left:22px;list-style:circle" if st["branch"] else "list-style:none"}">{e(lead)}{e(st["text"])} '
                f'{("<span class=\"mono small mut\">" + e(st["req"]) + "</span>") if st.get("req") else ""}{chips}</li>')
    return f'<ol style="padding-left:6px;margin:6px 0">{lis}</ol>' if lis else '<p class="mut small">PRD 2장에 단계가 없다</p>'


def _reject_prefill(f: dict, s: dict, r: dict) -> str:
    """[변형으로 추가] — 테스트 없는 거절 규칙 하나로 변형 폼을 채워 연다. key 가 겹치면 게이트 이름을 앞에 붙인다(§5)."""
    keys = {v["variant"].key for v in s["variants"]}
    same = [x for x in s["untested_rejects"] if x["key"] == r["key"] and x["gate"] != r["gate"]]      # host-only 처럼 게이트 여럿에 같은 key
    key = r["key"] if (r["key"] not in keys and not same) else f'{r["gate"].rsplit(".", 1)[-1]}.{r["key"]}'
    title = r["title"].split(" — ", 1)[-1] if " — " in r["title"] else r["title"]
    q = {"kind": "reject", "at": r["at"], "key": key, "title": title + (f" ({r['error_code']})" if r.get("error_code") else ""),
         "checks": r["id"], "mode": r["mode"]}
    return feature_url(f["slug"], s["id"], "new") + "?" + "&".join(f"{k}={quote(str(v), safe='')}" for k, v in q.items())


def feature_page(f: dict, *, check: dict, gate_names: dict, prd_url: str | None, operator: str = "", scripts_of: dict | None = None) -> str:
    fc = check.get("by_feature", {}).get(f["slug"]) or {"errors": [], "warnings": []}
    msgs = "".join(f'<li style="color:var(--bad)">{e(x)}</li>' for x in fc["errors"]) + "".join(f'<li style="color:var(--warn)">{e(x)}</li>' for x in fc["warnings"])
    body = ""
    for s in f["scenarios"]:
        vrows = "".join(_variant_row(v, indent=False) for v in s["variants"]) or '<tr><td colspan="4" class="mut">변형 없음 — 시나리오 파일에 변형을 더한다</td></tr>'
        rej = "".join(
            f'<tr><td>{tc_link(r["id"])}</td><td class="mono small">{e(r["at"])}</td><td class="small">{e(r["title"])}</td>'
            f'<td class="mono small">{e(r["error_code"] or "")}</td><td class="small">{"자동" if r["mode"] == "auto" else "<span class=mut>사람이 확인으로 시작 (ErrorCode 없음)</span>"}</td>'
            f'<td><a class="btn" href="{e(_reject_prefill(f, s, r))}">변형으로 추가</a></td></tr>'
            for r in s["untested_rejects"])
        rej_html = (f'<h4>테스트 없는 거절 규칙 {len(s["untested_rejects"])}개{h("feature.rejects")}</h4>'
                    f'<table><tr><th>검사 (TC)</th><th>단계</th><th>내용</th><th>ErrorCode</th><th>시작 방식</th><th></th></tr>{rej}</table>') if rej else (
                    '<p class="small mut">테스트 없는 거절 규칙 없음</p>' if s["scenario"] and s["scenario"].gates else '<p class="small mut">단계에 걸린 게이트(gates)를 아직 적지 않았다 — 적으면 테스트 없는 거절 규칙이 계산된다</p>')
        actor = (s["scenario"].actor if s["scenario"] else None) or "–"
        btns = (f' <a class="btn" href="{feature_url(f["slug"], s["id"], "new")}">+ 변형</a>' if s["in_prd"] else "") + \
               (f' <a class="btn" href="{feature_url(f["slug"], s["id"], "edit")}">시나리오 고치기</a>{h("scenario.form")}' if s["in_prd"] else "")
        del_box = delete_box(what=f'시나리오 {s["id"]}', action="scenario-delete", feature=f["feature"], scenario=s["id"], key=None,
                             scripts=[c for v in s["variants"] for c in v["scripts"]], operator=operator) if s["scenario"] else ""
        body += (f'<div class="card" id="{e(s["id"])}"><h3 style="margin-top:0"><span class="mono">{e(s["id"])}</span> {e(s["title"])}'
                 f'{"" if s["in_prd"] else " <span class=\"b fail\">PRD 2장에 없다</span>"} <span class="small mut">기본 테스트 계정 {e(actor)}</span>{btns}</h3>'
                 f'<h4>PRD 단계{h("feature.steps")}</h4>{_steps_html(s, gate_names)}'
                 f'<h4>변형{h("variant.state")}</h4><table style="table-layout:fixed">{_VCOLS}<tr><th>변형</th><th>상태</th><th>스크립트</th><th>최근 결과</th></tr>{vrows}</table>{rej_html}{del_box}</div>')
    c = f["counts"]
    return (f'<h1>{e(f["feature"])}{h("feature.page")} <span class="small mut">'
            f'{("<a href=\"" + e(prd_url) + "\">PRD</a> · ") if prd_url else ""}'
            f'{("<span class=\"mono\">scenarios/" + e(f["file"]) + "</span>") if f["file"] else "시나리오 파일 없음"}</span></h1>'
            f'<div class="card"><div class="stats" style="margin:0">'
            + "".join(f'<div class="stat"><div class="l">{e(label)}</div><b>{c[k]}</b></div>'
                      for k, label in (("variants", "변형"), ("auto", "자동화됨"), ("manual", "사람이 확인"), ("excluded", "제외"), ("untested", "테스트 없음"), ("rejects", "테스트 없는 거절 규칙")))
            + f'</div>{_bar(c)}</div>'
            f'{("<div class=\"card\"><b>검증</b>" + h("feature.check") + "<ul style=\"margin:6px 0 0\">" + msgs + "</ul></div>") if msgs else ""}{body}')


def variant_page(f: dict, s: dict, v: dict, *, check: dict, tc_records: dict, history: list[dict], step: dict | None, operator: str = "") -> str:
    va = v["variant"]
    checks = "".join(
        f'<li>{tc_link(t)} <span class="small">{e((tc_records.get(t) or {}).get("title") or "TC 목록에 없다")}</span>'
        f'{(" " + badge("자동화 제외", "excluded")) if (tc_records.get(t) or {}).get("excluded") else ""}'
        f'{"" if any(t in c.covers for c in v["scripts"]) or not v["scripts"] else " <span class=\"b warn\">스크립트 covers 에 없음</span>"}</li>'
        for t in va.checks) or '<li class="mut">적지 않았다</li>'
    scripts = "".join(
        f'<tr><td><a href="/cases/{e(c.id)}" class="mono">{e(c.id)}</a></td><td>{e(c.title)}</td><td>{badge(c.suite)}</td></tr>' for c in v["scripts"]) \
        or '<tr><td colspan="3" class="mut">이 변형을 구현한 스크립트가 없다</td></tr>'
    hist = "".join(
        f'<tr><td><a href="/runs/{e(r["run_id"])}" class="mono">{e(r["run_id"])}</a></td><td class="mono small">{e(r["case_id"])}</td><td>{badge(r["verdict"])}</td>'
        f'<td class="small mut">{kst(r["created_at"])}</td><td class="small" style="color:var(--bad)">{e(r.get("error") or "")}</td></tr>' for r in history) \
        or '<tr><td colspan="5" class="mut">실행 이력 없음</td></tr>'
    at = (f'<div>갈라지는 단계</div><div><span class="mono">{e(va.at)}</span> {e((step or {}).get("text") or "(PRD 2장에서 찾지 못했다)")}</div>') if va.at else ""
    q = "&".join([f"variant={quote(v['id'], safe='')}"] + [f"tc={quote(t, safe='')}" for t in va.checks])
    fc = check.get("by_feature", {}).get(f["slug"]) or {"errors": [], "warnings": []}
    mine = [x for x in fc["errors"] + fc["warnings"] if x.startswith(f'{s["id"]}/{va.key}')]
    del_box = delete_box(what=f"변형 {va.key}", action="variant-delete", feature=f["feature"], scenario=s["id"], key=va.key, scripts=v["scripts"], operator=operator)
    hermes = ' <span class="b warn">Hermes 작성</span>' if va.raw.get("written_by") == "hermes" else ""
    return (f'<h1>{kind_badge(va.kind)} {e(va.title)} {state_badge(v["state"])}{hermes}{h("variant.state")} '
            f'<a class="btn" href="{feature_url(f["slug"], s["id"], va.key)}/edit">폼으로 고치기</a>{h("scenario.form")}</h1>'
            f'<p class="small mut"><a href="{feature_url(f["slug"])}">{e(f["feature"])}</a> › <a href="{feature_url(f["slug"])}#{e(s["id"])}">{e(s["id"])} {e(s["title"])}</a> › <span class="mono">{e(v["id"])}</span></p>'
            f'{("<div class=\"card\"><ul style=\"margin:0\">" + "".join("<li style=\"color:var(--warn)\">" + e(x) + "</li>" for x in mine) + "</ul></div>") if mine else ""}'
            f'<div class="card"><div class="kv">{at}<div>전제</div><div>{e(va.given) or "<span class=mut>–</span>"}</div>'
            f'<div>기대 결과</div><div>{e(va.then) or "<span class=mut>–</span>"}</div><div>확인 방식</div><div>{"스크립트" if va.mode == "auto" else "사람이 확인"}</div></div></div>'
            f'<h2>확인할 TC (checks){h("variant.checks")}</h2><div class="card"><ul style="margin:0;padding-left:18px">{checks}</ul></div>'
            f'<h2>구현한 스크립트</h2><div class="card"><table><tr><th>스크립트</th><th>제목</th><th>스위트</th></tr>{scripts}</table>'
            f'<div class="actions"><a class="btn" href="/cases/new?{q}">스크립트 만들기 (폼)</a>{h("variant.new_script")}</div></div>'
            f'<h2>실행 이력</h2><div class="card"><table><tr><th>실행</th><th>스크립트</th><th>결과</th><th>시각</th><th>오류</th></tr>{hist}</table></div>{del_box}')


def variants_of_tc(ov: list[dict], tid: str) -> list[dict]:
    """TC 상세의 "이 TC 를 확인하는 변형" (§12)."""
    return [v for f in ov for s in f["scenarios"] for v in s["variants"] if tid in v["variant"].checks]


def tc_variants_card(vs: list[dict]) -> str:
    rows = "".join(f'<tr><td><a href="{variant_url(v["id"])}" class="mono small">{e(v["id"])}</a></td><td>{kind_badge(v["variant"].kind)} {e(v["variant"].title)}</td>'
                   f'<td>{state_badge(v["state"])}</td></tr>' for v in vs) or '<tr><td colspan="3" class="mut">이 TC 를 확인하는 변형 없음</td></tr>'
    return f'<h2>이 TC 를 확인하는 변형{h("variant.checks")}</h2><div class="card"><table><tr><th>변형</th><th>제목</th><th>상태</th></tr>{rows}</table></div>'


# ---------------------------------------------------------------------------------------------
# 시나리오 폼 (§14 5단계) — 변형 만들기·고치기·지우기, 시나리오의 기본 테스트 계정·gates 고치기
# ---------------------------------------------------------------------------------------------
def _msgs(errors, warnings) -> str:
    li = "".join(f'<li style="color:var(--bad)">{e(x)}</li>' for x in errors or []) + "".join(f'<li style="color:var(--warn)">{e(x)}</li>' for x in warnings or [])
    return f'<div class="card"><b>저장하지 않았다</b><ul style="margin:6px 0 0">{li}</ul></div>' if li else ""


def _op_select(name: str, opts: list, cur: str, blank: str | None = None) -> str:
    o = (f'<option value="">{e(blank)}</option>' if blank is not None else "") + "".join(
        f'<option value="{e(v)}"{" selected" if v == cur else ""}>{e(label)}</option>' for v, label in opts)
    return f'<select name="{e(name)}">{o}</select>'


def _operator_hidden(operator: str) -> str:
    return f'<input type="hidden" name="operator" value="{e(operator)}">'


def variant_form(f: dict, s: dict, raw: dict, *, mode: str, operator: str, tc_options: list[tuple[str, str]],
                 errors: list | None = None, warnings: list | None = None) -> str:
    """mode new | edit. raw 는 파일 모양의 변형 맵 (checks 는 목록)."""
    edit = mode == "edit"
    steps = [(st["req"], ("분기: " if st["branch"] else f'{st["no"]}. ') + st["text"][:60]) for st in s["steps"] if st.get("req")]
    kinds = [(k, f"{v} ({k})") for k, v in KIND_KO.items()]
    checks = ", ".join(raw.get("checks") or [])
    dis = "" if operator else 'disabled title="담당자를 먼저 고르세요"'
    back = variant_url(f'{f["slug"]}/{s["id"]}/{raw.get("key")}') if edit else feature_url(f["slug"]) + f'#{s["id"]}'
    return (f'<h1>{"변형 고치기" if edit else "변형 만들기"}{h("scenario.form")} <span class="small mut">{e(f["feature"])} › {e(s["id"])} {e(s["title"])}</span></h1>'
            f'{_msgs(errors, warnings)}'
            f'<form method="post" action="/features/save" class="card">{_operator_hidden(operator)}'
            f'<input type="hidden" name="feature" value="{e(f["feature"])}"><input type="hidden" name="scenario" value="{e(s["id"])}">'
            f'<input type="hidden" name="action" value="variant"><input type="hidden" name="original_key" value="{e(raw.get("key") if edit else "")}">'
            f'<div class="field"><label class="req">key</label><input name="key" class="mono" value="{e(raw.get("key") or "")}" {"readonly" if edit else ""} placeholder="headcount-range">'
            f'<p class="hint">{"고칠 때는 key 를 바꿀 수 없다 — 스크립트 variant: 가 이 이름을 가리킨다" if edit else "소문자·숫자·점·하이픈. 거절 변형은 검사 key 를 그대로 쓴다"}</p></div>'
            f'<div class="field"><label class="req">종류</label>{_op_select("kind", kinds, raw.get("kind") or "happy")}</div>'
            f'<div class="field"><label>갈라지는 단계 (at)</label>{_op_select("at", steps, raw.get("at") or "", "없음 (정상 흐름·추가)")}<p class="hint">분기와 거절은 필요하다. PRD 2장 단계의 요구 id 다</p></div>'
            f'<div class="field"><label class="req">제목</label><input name="title" value="{e(raw.get("title") or "")}" placeholder="최대 모집 인원이 최소 진행 인원보다 작으면 E1402 로 거절된다"></div>'
            f'<div class="field"><label>전제 (given)</label><input name="given" value="{e(raw.get("given") or "")}"></div>'
            f'<div class="field"><label>기대 결과 (then)</label><input name="then" value="{e(raw.get("then") or "")}"></div>'
            f'<div class="field"><label>확인할 TC (checks){h("variant.checks")}</label><input name="checks" class="mono" list="dl-scn-tcs" value="{e(checks)}" placeholder="G.room.create#headcount-range">'
            f'<p class="hint">쉼표로 여러 개. 거절 변형은 검사 하나가 기본이다</p></div>'
            f'<div class="field"><label>확인 방식</label>{_op_select("mode", [("auto", "스크립트로 확인 (auto)"), ("manual", "사람이 확인 (manual)")], raw.get("mode") or "auto")}</div>'
            f'<datalist id="dl-scn-tcs">{"".join(f"<option value=\"{e(t)}\">{e(label)}</option>" for t, label in tc_options)}</datalist>'
            f'<div class="actions"><button class="primary" {dis}>저장</button> <a href="{back}">돌아가기</a></div>'
            f'<p class="small mut">저장하면 §6.1 검사를 거쳐 main 의 <span class="mono">scenarios/{e(f["slug"])}.yaml</span> 에 바로 커밋된다.</p></form>')


def scenario_form(f: dict, s: dict, *, operator: str, actors: list[str], gate_options: list[tuple[str, str]],
                  errors: list | None = None, warnings: list | None = None, values: dict | None = None) -> str:
    sc = s["scenario"]
    gates = (values or {}).get("gates") if values else (sc.gates if sc else {})
    actor = (values or {}).get("actor") if values else (sc.actor if sc else "")
    rows = "".join(
        f'<tr><td class="small">{e(("분기: " if st["branch"] else str(st["no"]) + ". ") + st["text"][:70])} <span class="mono mut">{e(st["req"])}</span></td>'
        f'<td><input name="gate.{e(st["req"])}" class="mono" list="dl-scn-gates" value="{e(", ".join((gates or {}).get(st["req"]) or []))}" style="width:100%"></td></tr>'
        for st in s["steps"] if st.get("req"))
    dis = "" if operator else 'disabled title="담당자를 먼저 고르세요"'
    return (f'<h1>시나리오 고치기{h("scenario.form")} <span class="small mut">{e(f["feature"])} › {e(s["id"])} {e(s["title"])}</span></h1>'
            f'{_msgs(errors, warnings)}'
            f'<form method="post" action="/features/save" class="card">{_operator_hidden(operator)}'
            f'<input type="hidden" name="feature" value="{e(f["feature"])}"><input type="hidden" name="scenario" value="{e(s["id"])}"><input type="hidden" name="action" value="scenario">'
            f'<div class="field"><label>기본 테스트 계정</label>{_op_select("actor", [(a, a) for a in sorted(set(actors) | ({actor} if actor else set()))], actor or "", "없음")}</div>'
            f'<h3>단계에 걸린 게이트 (gates){h("feature.steps")}</h3><p class="small mut">단계마다 그 행동을 허락하는 규칙표 게이트를 적는다. 쉼표로 여러 개. 여기 적은 게이트의 거절 검사가 테스트 없는 거절 규칙이 된다.</p>'
            f'<table><tr><th>PRD 단계</th><th style="width:45%">게이트</th></tr>{rows}</table>'
            f'<datalist id="dl-scn-gates">{"".join(f"<option value=\"{e(g)}\">{e(n)}</option>" for g, n in gate_options)}</datalist>'
            f'<div class="actions"><button class="primary" {dis}>저장</button> <a href="{feature_url(f["slug"])}#{e(s["id"])}">돌아가기</a></div></form>')


def delete_box(*, what: str, action: str, feature: str, scenario: str, key: str | None, scripts: list, operator: str) -> str:
    """지우기 확인 (§9) — 가리키던 스크립트를 보이고, 그 스크립트는 지우지 않고 "시나리오 밖" 으로 돌린다."""
    names = ", ".join(c.id for c in scripts)
    confirm = f"{what} 를 지운다." + (f" 스크립트 {names} 는 지우지 않고 시나리오 밖으로 돌린다." if scripts else "")
    return (f'<details class="card"><summary>{e(what)} 지우기{h("scenario.delete")}</summary>'
            f'<form method="post" action="/features/delete" class="actions" onsubmit="return confirm({e(json_str(confirm))})">{_operator_hidden(operator)}'
            f'<input type="hidden" name="feature" value="{e(feature)}"><input type="hidden" name="scenario" value="{e(scenario)}"><input type="hidden" name="action" value="{e(action)}">'
            f'<input type="hidden" name="key" value="{e(key or "")}"><input name="reason" placeholder="사유 (선택, 커밋 메시지에 남는다)" style="flex:1">'
            f'<button class="danger" {"" if operator else "disabled"}>지우기</button></form>'
            f'<p class="small mut" style="margin:0">{("이것을 구현한 스크립트 " + e(names) + " 는 지우지 않는다. variant: 를 떼어 시나리오 밖으로 돌린다.") if scripts else "이것을 구현한 스크립트는 없다."}</p></details>')


def json_str(s: str) -> str:
    import json
    return json.dumps(s, ensure_ascii=False)
