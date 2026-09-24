"""런 → 위키 보고서(markdown). 사람이 [위키에 발행] 을 누를 때만 만들어진다. docs/qa-platform-tc.md §9.

페이지는 `wiki/qa/<YYYY-Www>-<trigger>` 슬러그, frontmatter `managed_by: harness` (wiki_apply mode generated 의 조건).
회원 UUID 는 마스킹한다.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from .mcp import mask_ids

KST = timezone(timedelta(hours=9))
LAYER_KO = {"policy": "정책", "contract": "계약", "manual": "서술"}
TRIGGER_KO = {"deploy-sanity": "배포 검증", "sprint-smoke": "스프린트 smoke", "release": "릴리스 QA", "manual": "임의 실행"}


def slug_for(run: dict) -> str:
    dt = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).astimezone(KST)
    y, w, _ = dt.isocalendar()
    return f"qa/{y}-W{w:02d}-{run['trigger']}"


def render(run: dict, rcs: list[dict], *, coverage: dict | None, catalog, public_url: str, sprint: dict | None, groups: tuple | None = None) -> str:
    """groups(scenarios.group_run_cases 결과)가 있으면 스크립트 표를 기능 · 시나리오 · 케이스 순서로 묶는다."""
    meta = run.get("meta") or {}
    created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).astimezone(KST)
    title = f"QA {TRIGGER_KO.get(run['trigger'], run['trigger'])} {created.strftime('%Y-%m-%d')}"
    verdict = run.get("verdict") or run.get("status")
    lines = [
        "---",
        f'title: "{title}"',
        "type: doc",
        "status: active",
        f'summary: "{TRIGGER_KO.get(run["trigger"], run["trigger"])} 런 {run["id"]} — {verdict}, 통과 {run["passed"]}/{run["total"]}"',
        f'last_updated: "{created.strftime("%Y-%m-%d")}"',
        "managed_by: harness",
        f'source: "qa-platform run {run["id"]}"',
        "tags: [qa, report]",
        "---",
        "",
        f"# {title}",
        "",
        "> 이 페이지는 QA 플랫폼이 런 기록에서 생성했다. 직접 수정하지 말고 플랫폼에서 다시 발행한다.",
        "",
        "## 런",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 런 | [{run['id']}]({public_url}/runs/{run['id']}) |",
        f"| 트리거 | {TRIGGER_KO.get(run['trigger'], run['trigger'])} |",
        f"| 운영자 | {run['operator']} |",
        f"| 대상 | `{run.get('base_url') or ''}` · sha `{(run.get('sha') or '–')[:8]}`" + (f" · PR #{run['pr_number']}" if run.get("pr_number") else "") + " |",
        f"| 시각 | {created.strftime('%Y-%m-%d %H:%M')} KST |",
        f"| 판정 | **{verdict}** — 통과 {run['passed']} · 실패 {run['failed']} · 오류 {run['errored']} · skip {run['skipped']} / {run['total']} |",
    ]
    if sprint:
        lines.append(f"| 스프린트 | Cycle {sprint['number']} |")
    cat = meta.get("catalog") or {}
    if cat:
        lines.append(f"| 기준 버전 | SSOT `{cat.get('ssot') or '–'}` · OpenAPI `{cat.get('openapi') or '–'}` |")
    rel = meta.get("release")
    if rel:
        lines.append(f"| 릴리스 판단 | **{rel.get('decision', '').upper()}** — {rel.get('operator')} · {rel.get('reason') or '(사유 없음)'} |")
    def row(rc):
        note = (rc.get("error") or "").replace("|", "\\|").replace("\n", " ")[:160]
        return f"| `{rc['case_id']}` {rc['case_title']} | {rc['case_suite']} | {rc['verdict']} | {note} |"
    head = ["| 스크립트 | 스위트 | 판정 | 비고 |", "|---|---|---|---|"]
    if groups and groups[0]:
        lines += ["", "## 시나리오별 결과", "", "| 기능 | 시나리오 | 케이스 | 판정 |", "|---|---|---|---|"]
        for g in groups[0]:
            vs = [rc["verdict"] for rc in g["rcs"]]
            v = "fail" if "fail" in vs else ("error" if "error" in vs else ("pass" if "pass" in vs else vs[0]))
            lines.append(f"| {g['feature']} | {g['scenario']} {g['scenario_title']} | {g['title']} | {v} |")
        for g in groups[0]:
            lines += ["", f"### {g['feature']} › {g['scenario']} › {g['title']}", ""] + head + [row(rc) for rc in g["rcs"]]
        if groups[1]:
            lines += ["", "### 시나리오에 연결되지 않은 스크립트", ""] + head + [row(rc) for rc in groups[1]]
    else:
        lines += ["", "## 스크립트", ""] + head + [row(rc) for rc in rcs]
    bad = [rc for rc in rcs if rc.get("triage")]
    if bad:
        lines += ["", "## 진단 (Hermes)", ""]
        for rc in bad:
            lines += [f"### {rc['case_id']}", "", "```", rc["triage"].strip()[:1500], "```", ""]
    if coverage and catalog is not None:
        layers = [l for l in ("policy", "contract", "manual") if any(l in v for v in coverage["matrix"].values())]
        lines += ["", "## 기준 커버리지 (발행 시점)", "", "| 도메인 | " + " | ".join(LAYER_KO[l] for l in layers) + " |", "|---|" + "---|" * len(layers)]
        for d in catalog.domains():
            cells = []
            for l in layers:
                c = coverage["matrix"].get(d, {}).get(l)
                cells.append("–" if not c else f"{c['covered']}/{c['total'] - c['excluded']}" + (f" (제외 {c['excluded']})" if c["excluded"] else ""))
            lines.append(f"| {d} | " + " | ".join(cells) + " |")
        lines.append("")
        lines.append("분모는 전체 테스트 조건에서 사유가 적힌 제외를 뺀 수. 정본은 `wiki/policy/_src/상태-SSOT.yaml`(정책)과 백엔드 OpenAPI(계약).")
    lines += ["", f"— 생성: qa-platform, {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} KST"]
    return mask_ids("\n".join(lines)) + "\n"
