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


def feature_page(f: dict, *, check: dict, gate_names: dict, prd_url: str | None) -> str:
    fc = check.get("by_feature", {}).get(f["slug"]) or {"errors": [], "warnings": []}
    msgs = "".join(f'<li style="color:var(--bad)">{e(x)}</li>' for x in fc["errors"]) + "".join(f'<li style="color:var(--warn)">{e(x)}</li>' for x in fc["warnings"])
    body = ""
    for s in f["scenarios"]:
        vrows = "".join(_variant_row(v, indent=False) for v in s["variants"]) or '<tr><td colspan="4" class="mut">변형 없음 — 시나리오 파일에 변형을 더한다</td></tr>'
        rej = "".join(
            f'<tr><td>{tc_link(r["id"])}</td><td class="mono small">{e(r["at"])}</td><td class="small">{e(r["title"])}</td>'
            f'<td class="mono small">{e(r["error_code"] or "")}</td><td class="small">{"자동" if r["mode"] == "auto" else "<span class=mut>사람이 확인으로 시작 (ErrorCode 없음)</span>"}</td></tr>'
            for r in s["untested_rejects"])
        rej_html = (f'<h4>테스트 없는 거절 규칙 {len(s["untested_rejects"])}개{h("feature.rejects")}</h4>'
                    f'<table><tr><th>검사 (TC)</th><th>단계</th><th>내용</th><th>ErrorCode</th><th>시작 방식</th></tr>{rej}</table>') if rej else (
                    '<p class="small mut">테스트 없는 거절 규칙 없음</p>' if s["scenario"] and s["scenario"].gates else '<p class="small mut">단계에 걸린 게이트(gates)를 아직 적지 않았다 — 적으면 테스트 없는 거절 규칙이 계산된다</p>')
        actor = (s["scenario"].actor if s["scenario"] else None) or "–"
        body += (f'<div class="card" id="{e(s["id"])}"><h3 style="margin-top:0"><span class="mono">{e(s["id"])}</span> {e(s["title"])}'
                 f'{"" if s["in_prd"] else " <span class=\"b fail\">PRD 2장에 없다</span>"} <span class="small mut">기본 테스트 계정 {e(actor)}</span></h3>'
                 f'<h4>PRD 단계{h("feature.steps")}</h4>{_steps_html(s, gate_names)}'
                 f'<h4>변형{h("variant.state")}</h4><table style="table-layout:fixed">{_VCOLS}<tr><th>변형</th><th>상태</th><th>스크립트</th><th>최근 결과</th></tr>{vrows}</table>{rej_html}</div>')
    c = f["counts"]
    return (f'<h1>{e(f["feature"])}{h("feature.page")} <span class="small mut">'
            f'{("<a href=\"" + e(prd_url) + "\">PRD</a> · ") if prd_url else ""}'
            f'{("<span class=\"mono\">scenarios/" + e(f["file"]) + "</span>") if f["file"] else "시나리오 파일 없음"}</span></h1>'
            f'<div class="card"><div class="stats" style="margin:0">'
            + "".join(f'<div class="stat"><div class="l">{e(label)}</div><b>{c[k]}</b></div>'
                      for k, label in (("variants", "변형"), ("auto", "자동화됨"), ("manual", "사람이 확인"), ("excluded", "제외"), ("untested", "테스트 없음"), ("rejects", "테스트 없는 거절 규칙")))
            + f'</div>{_bar(c)}</div>'
            f'{("<div class=\"card\"><b>검증</b>" + h("feature.check") + "<ul style=\"margin:6px 0 0\">" + msgs + "</ul></div>") if msgs else ""}{body}')


def variant_page(f: dict, s: dict, v: dict, *, check: dict, tc_records: dict, history: list[dict], step: dict | None) -> str:
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
    return (f'<h1>{kind_badge(va.kind)} {e(va.title)} {state_badge(v["state"])}{h("variant.state")}</h1>'
            f'<p class="small mut"><a href="{feature_url(f["slug"])}">{e(f["feature"])}</a> › <a href="{feature_url(f["slug"])}#{e(s["id"])}">{e(s["id"])} {e(s["title"])}</a> › <span class="mono">{e(v["id"])}</span></p>'
            f'{("<div class=\"card\"><ul style=\"margin:0\">" + "".join("<li style=\"color:var(--warn)\">" + e(x) + "</li>" for x in mine) + "</ul></div>") if mine else ""}'
            f'<div class="card"><div class="kv">{at}<div>전제</div><div>{e(va.given) or "<span class=mut>–</span>"}</div>'
            f'<div>기대 결과</div><div>{e(va.then) or "<span class=mut>–</span>"}</div><div>확인 방식</div><div>{"스크립트" if va.mode == "auto" else "사람이 확인"}</div></div></div>'
            f'<h2>확인할 TC (checks){h("variant.checks")}</h2><div class="card"><ul style="margin:0;padding-left:18px">{checks}</ul></div>'
            f'<h2>구현한 스크립트</h2><div class="card"><table><tr><th>스크립트</th><th>제목</th><th>스위트</th></tr>{scripts}</table>'
            f'<div class="actions"><a class="btn" href="/cases/new?{q}">스크립트 만들기 (폼)</a>{h("variant.new_script")}</div></div>'
            f'<h2>실행 이력</h2><div class="card"><table><tr><th>실행</th><th>스크립트</th><th>결과</th><th>시각</th><th>오류</th></tr>{hist}</table></div>')


def variants_of_tc(ov: list[dict], tid: str) -> list[dict]:
    """TC 상세의 "이 TC 를 확인하는 변형" (§12)."""
    return [v for f in ov for s in f["scenarios"] for v in s["variants"] if tid in v["variant"].checks]


def tc_variants_card(vs: list[dict]) -> str:
    rows = "".join(f'<tr><td><a href="{variant_url(v["id"])}" class="mono small">{e(v["id"])}</a></td><td>{kind_badge(v["variant"].kind)} {e(v["variant"].title)}</td>'
                   f'<td>{state_badge(v["state"])}</td></tr>' for v in vs) or '<tr><td colspan="3" class="mut">이 TC 를 확인하는 변형 없음</td></tr>'
    return f'<h2>이 TC 를 확인하는 변형{h("variant.checks")}</h2><div class="card"><table><tr><th>변형</th><th>제목</th><th>상태</th></tr>{rows}</table></div>'
