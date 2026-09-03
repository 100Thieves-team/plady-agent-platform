#!/usr/bin/env python3
"""otel-report.py — what do I actually ask my coding agents, and when?

Reads the file export of the PERSONAL local collector (compose.otel-local.yaml,
otel/collector-config.local.yaml) and prints a Markdown report over the Claude
Code and Codex telemetry it holds: prompts (most repeated, slash commands,
hour-of-day / weekday rhythm), tool usage, tokens and cost, sessions per day.

    scripts/otel-report.py                      # read otel-local.json* from the docker volume
    scripts/otel-report.py --file dump.json     # read an extracted file (one OTLP JSON object per line)
    scripts/otel-report.py --since 14d --top 30 --tz Asia/Seoul
    scripts/otel-report.py --prompts            # also dump every prompt, newest first

Standard library only. Timestamps are shown in --tz (default Asia/Seoul).
Everything here is the developer's own data from their own laptop; the file
contains prompt text and must not leave the machine (docs/otel-collector.md).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import statistics
import subprocess
import sys
from zoneinfo import ZoneInfo

VOLUME = "100thieves-wiki-mcp_otel-data"
FILE_GLOB = "/data/otel-local.json*"

# Claude Code events carry `event.name`; Codex events carry `event.name` too,
# prefixed `codex.`. Names below are what the two CLIs emit today.
PROMPT_EVENTS = {"user_prompt": "claude", "codex.user_prompt": "codex"}
TOOL_EVENTS = {"tool_result": "claude", "tool_decision": "claude", "codex.tool_result": "codex"}
API_EVENTS = {"api_request": "claude", "codex.sse_event": "codex", "codex.api_request": "codex"}
SESSION_EVENTS = {"codex.conversation_starts": "codex"}

# Slash commands and skills the report groups separately from free prompts.
SLASH = re.compile(r"^\s*/([A-Za-z0-9:_\-]+)")

# Prompts the CLIs send on the user's behalf (Codex thread-title generation,
# Claude Code's own summaries). They arrive as user_prompt events but nobody
# typed them; counting them would put a canned sentence at the top of every
# "most repeated" table.
MACHINE_PROMPTS = (
    "Generate a concise, single-line task title",
    "Summarize the conversation",
)


# ── reading ───────────────────────────────────────────────────────────────────

def read_from_volume(volume: str) -> list[str]:
    cmd = ["docker", "run", "--rm", "-v", f"{volume}:/data", "busybox", "sh", "-c",
           f"cat {FILE_GLOB} 2>/dev/null"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"could not read volume {volume}: {out.stderr.strip()}")
    return out.stdout.splitlines()


def attr_value(v: dict):
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return v["doubleValue"]
    if "boolValue" in v:
        return v["boolValue"]
    if "arrayValue" in v:
        return [attr_value(x) for x in v["arrayValue"].get("values", [])]
    return None


def attrs(items) -> dict:
    return {a["key"]: attr_value(a["value"]) for a in (items or [])}


def records(lines):
    """Yield ('log', ts, attrs, body, resource) and ('metric', name, dp_attrs, value, ts)."""
    for line in lines:
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        for rl in d.get("resourceLogs", []):
            res = attrs(rl.get("resource", {}).get("attributes"))
            for sl in rl.get("scopeLogs", []):
                for r in sl.get("logRecords", []):
                    a = attrs(r.get("attributes"))
                    ts = int(r.get("timeUnixNano") or r.get("observedTimeUnixNano") or 0)
                    yield ("log", ts, a, r.get("body", {}).get("stringValue", ""), res)
        for rm in d.get("resourceMetrics", []):
            res = attrs(rm.get("resource", {}).get("attributes"))
            for sm in rm.get("scopeMetrics", []):
                for m in sm.get("metrics", []):
                    for kind in ("sum", "gauge"):
                        for dp in m.get(kind, {}).get("dataPoints", []):
                            val = dp.get("asInt", dp.get("asDouble"))
                            yield ("metric", m["name"], attrs(dp.get("attributes")),
                                   float(val) if val is not None else 0.0, int(dp.get("timeUnixNano") or 0))


# ── analysis ──────────────────────────────────────────────────────────────────

def num(v):
    """Codex emits some counters as strings ('550002'); treat digits as numbers."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v.strip()):
        return float(v) if "." in v else int(v)
    return None


def normalise(prompt: str) -> str:
    """Key for 'the same prompt again': whitespace-collapsed, case-folded, trimmed."""
    return re.sub(r"\s+", " ", prompt).strip().casefold()[:200]


def parse_since(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    m = re.fullmatch(r"(\d+)([dhw])", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"d": dt.timedelta(days=n), "h": dt.timedelta(hours=n), "w": dt.timedelta(weeks=n)}[unit]
        return dt.datetime.now(dt.timezone.utc) - delta
    return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)


def bar(n: int, scale: int, width: int = 30) -> str:
    return "█" * (round(n / scale * width) if scale else 0)


def report(lines, tz: ZoneInfo, since: dt.datetime | None, top: int, dump_prompts: bool) -> str:
    prompts = []          # (ts, source, text, session)
    tools = collections.defaultdict(lambda: {"n": 0, "ok": 0, "ms": []})
    tokens = collections.defaultdict(lambda: collections.Counter())  # (source, model) -> counters
    cost = collections.Counter()   # model -> usd
    sessions = collections.defaultdict(set)  # source -> session ids
    days = collections.Counter()
    first = last = None

    for rec in records(lines):
        if rec[0] == "log":
            _, ts, a, body, res = rec
            if not ts:
                continue
            when = dt.datetime.fromtimestamp(ts / 1e9, tz=dt.timezone.utc)
            if since and when < since:
                continue
            first = when if first is None or when < first else first
            last = when if last is None or when > last else last
            name = a.get("event.name") or body
            if name in PROMPT_EVENTS:
                src = PROMPT_EVENTS[name]
                text = a.get("prompt") or ""
                if text.lstrip().startswith(MACHINE_PROMPTS):
                    continue
                sid = a.get("session.id") or a.get("conversation.id") or "?"
                prompts.append((when, src, text, sid))
                sessions[src].add(sid)
                days[when.astimezone(tz).date()] += 1
            elif name in TOOL_EVENTS:
                src = TOOL_EVENTS[name]
                tool = a.get("tool_name") or a.get("tool") or "?"
                t = tools[(src, tool)]
                t["n"] += 1
                if a.get("success") in (True, "true", "True") or a.get("decision") == "accept":
                    t["ok"] += 1
                if num(a.get("duration_ms")) is not None:
                    t["ms"].append(float(num(a["duration_ms"])))
            elif name in API_EVENTS:
                src = API_EVENTS[name]
                model = a.get("model") or "?"
                c = tokens[(src, model)]
                if src == "claude":
                    for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"):
                        if num(a.get(k)) is not None:
                            c[k] += int(num(a[k]))
                    if num(a.get("cost_usd")) is not None:
                        cost[model] += float(num(a["cost_usd"]))
                    c["requests"] += 1
                elif name == "codex.sse_event":
                    # Only the completion event carries usage; the rest of the
                    # stream would create empty rows per model.
                    if not any(num(a.get(k)) is not None for k in ("input_token_count", "output_token_count")):
                        continue
                    for k, out in (("input_token_count", "input_tokens"), ("output_token_count", "output_tokens"),
                                   ("cached_token_count", "cache_read_tokens"), ("reasoning_token_count", "reasoning_tokens")):
                        if num(a.get(k)) is not None:
                            c[out] += int(num(a[k]))
                    c["requests"] += 1
                else:
                    # codex.api_request: request/failure count only, no usage.
                    status = num(a.get("http.response.status_code")) or 0
                    if a.get("success") in (False, "false") or status >= 400:
                        c["failed"] += 1
                    else:
                        continue
            elif name in SESSION_EVENTS:
                sessions[SESSION_EVENTS[name]].add(a.get("conversation.id") or "?")
        else:
            _, mname, a, val, ts = rec
            if mname == "claude_code.session.count" and a.get("session.id"):
                sessions["claude"].add(a["session.id"])

    out = []
    period = f"{first.astimezone(tz):%Y-%m-%d %H:%M} → {last.astimezone(tz):%Y-%m-%d %H:%M} ({tz.key})" if first else "no data"
    out.append(f"# Agent usage report\n\n기간: {period}\n")

    # Sessions & prompts
    out.append("## 세션 / 프롬프트\n")
    out.append("| | Claude Code | Codex |\n|---|---:|---:|")
    n_claude = sum(1 for p in prompts if p[1] == "claude")
    n_codex = sum(1 for p in prompts if p[1] == "codex")
    out.append(f"| 세션 | {len(sessions['claude'])} | {len(sessions['codex'])} |")
    out.append(f"| 프롬프트 | {n_claude} | {n_codex} |")
    lens = [len(p[2]) for p in prompts if p[2]]
    if lens:
        out.append(f"| 프롬프트 길이 중앙값 (자) | {int(statistics.median([len(p[2]) for p in prompts if p[1]=='claude' and p[2]] or [0]))} | {int(statistics.median([len(p[2]) for p in prompts if p[1]=='codex' and p[2]] or [0]))} |")
    out.append("")

    # Top repeated prompts
    freq = collections.Counter(normalise(p[2]) for p in prompts if p[2] and not SLASH.match(p[2]))
    repeated = [(k, v) for k, v in freq.most_common(top) if v > 1]
    out.append(f"## 반복해서 쓰는 프롬프트 (2회 이상, 상위 {top})\n")
    if repeated:
        out.append("| 횟수 | 프롬프트 |\n|---:|---|")
        for k, v in repeated:
            out.append(f"| {v} | {k[:120].replace('|', '\\|')} |")
    else:
        out.append("_아직 같은 프롬프트를 두 번 쓴 적이 없다._")
    out.append("")

    # Slash commands / skills
    slash = collections.Counter(SLASH.match(p[2]).group(1) for p in prompts if p[2] and SLASH.match(p[2]))
    out.append("## 슬래시 커맨드 / 스킬\n")
    if slash:
        out.append("| 횟수 | 커맨드 |\n|---:|---|")
        for k, v in slash.most_common(top):
            out.append(f"| {v} | /{k} |")
    else:
        out.append("_슬래시 커맨드 사용 없음._")
    out.append("")

    # Rhythm
    hours = collections.Counter(p[0].astimezone(tz).hour for p in prompts)
    wd = collections.Counter(p[0].astimezone(tz).strftime("%a") for p in prompts)
    out.append("## 시간대별 프롬프트 (hour of day)\n")
    out.append("```")
    peak = max(hours.values(), default=0)
    for h in range(24):
        out.append(f"{h:02d}h {hours[h]:4d} {bar(hours[h], peak)}")
    out.append("```")
    out.append("요일: " + ", ".join(f"{d} {wd[d]}" for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")) + "\n")

    # Per day
    out.append("## 일별 프롬프트\n")
    out.append("```")
    peak = max(days.values(), default=0)
    for d in sorted(days):
        out.append(f"{d} {days[d]:4d} {bar(days[d], peak)}")
    out.append("```\n")

    # Tools
    out.append("## 툴 사용\n")
    if tools:
        out.append("| 엔진 | 툴 | 호출 | 성공률 | 중앙값 ms |\n|---|---|---:|---:|---:|")
        for (src, tool), t in sorted(tools.items(), key=lambda kv: -kv[1]["n"])[:top]:
            rate = f"{t['ok']/t['n']*100:.0f}%" if t["n"] else "-"
            med = f"{int(statistics.median(t['ms']))}" if t["ms"] else "-"
            out.append(f"| {src} | {tool} | {t['n']} | {rate} | {med} |")
    else:
        out.append("_툴 이벤트 없음 (Claude Code 는 OTEL_LOG_TOOL_DETAILS=1 일 때 tool_result 를 낸다)._")
    out.append("")

    # Tokens / cost
    out.append("## 토큰 / 비용\n")
    if tokens:
        out.append("| 엔진 | 모델 | 요청 | input | output | cache read | cache write | reasoning | USD |\n|---|---|---:|---:|---:|---:|---:|---:|---:|")
        for (src, model), c in sorted(tokens.items(), key=lambda kv: -(kv[1]["input_tokens"] + kv[1]["output_tokens"])):
            if not c["requests"]:
                continue  # failure-only rows are summarised in the footer
            usd = f"{cost[model]:.2f}" if src == "claude" else "-"
            out.append(f"| {src} | {model} | {c['requests']} | {c['input_tokens']:,} | {c['output_tokens']:,} | {c['cache_read_tokens']:,} | {c['cache_creation_tokens']:,} | {c['reasoning_tokens']:,} | {usd} |")
        failed = sum(c["failed"] for c in tokens.values())
        out.append("\nUSD 는 Claude Code 가 보고한 `cost_usd` 합 (구독이면 참고값). Codex 는 비용을 보고하지 않는다."
                   + (f" 실패한 Codex API 요청: {failed}." if failed else ""))
    else:
        out.append("_API 이벤트 없음._")
    out.append("")

    if dump_prompts:
        out.append("## 프롬프트 전체 (최신순)\n")
        for when, src, text, sid in sorted(prompts, key=lambda p: p[0], reverse=True):
            one = re.sub(r"\s+", " ", text).strip()
            out.append(f"- `{when.astimezone(tz):%m-%d %H:%M}` **{src}** {one[:200]}")
        out.append("")

    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="read this extracted export instead of the docker volume")
    ap.add_argument("--volume", default=VOLUME, help=f"docker named volume (default {VOLUME})")
    ap.add_argument("--since", help="window: 7d, 36h, 2w, or an ISO date (UTC)")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--tz", default="Asia/Seoul")
    ap.add_argument("--prompts", action="store_true", help="append every prompt, newest first")
    args = ap.parse_args()

    lines = open(args.file, encoding="utf-8").read().splitlines() if args.file else read_from_volume(args.volume)
    print(report(lines, ZoneInfo(args.tz), parse_since(args.since), args.top, args.prompts))


if __name__ == "__main__":
    main()
