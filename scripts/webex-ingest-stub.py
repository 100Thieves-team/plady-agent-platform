#!/usr/bin/env python3
"""Local stand-in for the two external services the Webex ingest workflow calls.

Serves, on one port (default 18790):
  GET  /v1/meetings/<id>                     -> Webex meeting details
  GET  /v1/meetingTranscripts/<id>/download  -> transcript text (format=txt)
  GET  /v1/webhooks / POST /v1/webhooks      -> webhook list/create (register workflow)
  POST /v1/chat/completions                  -> Hermes-shaped answer with a ```json draft

The draft it returns is derived from the prompt (it echoes the raw path it is
asked to compile) so the whole chain — webhook signature, Webex fetch, raw
archive, plan, compile, knowledge apply — can be exercised against a local
llm-wiki with no Webex account and no model. It is a test double, nothing more.

  scripts/webex-ingest-stub.py --port 18790 --transcript fixtures/webex-sample.txt
  # then: scripts/webex-ingest-stub.py --fire http://localhost:5678/webhook/webex-transcript --secret <s>
"""
import argparse, hashlib, hmac, json, re, sys, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"transcript": "", "webhooks": [], "title": "데일리 스크럼 (stub)", "topic_hint": ""}


def draft_for(prompt: str) -> dict:
    raw = re.search(r"raw_source_path: \"([^\"]+)\"", prompt)
    raw_path = raw.group(1) if raw else "raw/meetings/webex-unknown"
    date = re.search(r"last_updated: (\d{4}-\d{2}-\d{2})", prompt)
    date = date.group(1) if date else "2026-01-01"
    slug = raw_path.rsplit("/", 1)[-1]
    # Pick the first candidate page from the plan section and append one line to it.
    cand = re.search(r"### ((?:topics|people)/[^\n]+)\n([\s\S]*?)(?=\n### topics/|\n### people/|\n## 원문|\Z)", prompt)
    changes = [{
        "path": f"sources/s-{slug}",
        "content": (
            "---\n"
            f"title: \"{STATE['title']} 요약\"\ntype: source\nstatus: active\n"
            f"summary: \"Webex 자동 ingest 스텁이 만든 요약\"\nlast_updated: \"{date}\"\n"
            f"source_type: meeting\nraw_source_path: \"{raw_path}\"\nsource_date: \"{date}\"\n"
            "tags:\n  - team-meeting\n  - webex\n---\n\n"
            f"# {STATE['title']} 요약\n\n- 스텁 요약: 회의에서 배포 절차 개선을 논의했다.\n"
            f"- 원문: [{raw_path}]({raw_path})\n"
        ),
    }]
    if cand:
        slug_c, body = cand.group(1).strip(), cand.group(2).rstrip()
        body = re.sub(r"last_updated: \"[^\"]+\"", f"last_updated: \"{date}\"", body, count=1)
        changes.append({"path": slug_c, "content": body + f"\n\n## {date} Webex 회의 반영 (stub)\n\n- 회의 요약 페이지: [sources/s-{slug}](sources/s-{slug})\n"})
    return {"message": f"ingest(knowledge): {STATE['title']} — webex {date} (stub)", "changes": changes}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, fmt, *a):
        sys.stderr.write("[stub] " + (fmt % a) + "\n")

    def do_GET(self):
        p = self.path.split("?")[0]
        if p.startswith("/v1/meetings/"):
            mid = p.rsplit("/", 1)[-1]
            return self._send(200, {"id": mid, "title": STATE["title"], "start": "2026-09-04T01:30:00Z", "end": "2026-09-04T02:05:00Z",
                                    "hostDisplayName": "Stub Host", "webLink": f"https://example.webex.com/meet/{mid}", "state": "ended"})
        if p.startswith("/v1/meetingTranscripts/") and p.endswith("/download"):
            return self._send(200, STATE["transcript"].encode("utf-8"), "text/plain; charset=utf-8")
        if p == "/v1/webhooks":
            return self._send(200, {"items": STATE["webhooks"]})
        self._send(404, {"error": "stub: unknown " + p})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n)
        p = self.path.split("?")[0]
        if p == "/v1/webhooks":
            w = json.loads(body); w["id"] = f"stub-{len(STATE['webhooks'])+1}"; w["status"] = "active"; w.pop("secret", None); STATE["webhooks"].append(w)
            return self._send(200, w)
        if p == "/v1/chat/completions":
            req = json.loads(body); prompt = "\n".join(m.get("content", "") for m in req.get("messages", []))
            draft = json.dumps(draft_for(prompt), ensure_ascii=False, indent=1)
            return self._send(200, {"id": "stub", "object": "chat.completion", "model": req.get("model"),
                                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "초안입니다.\n```json\n" + draft + "\n```"}, "finish_reason": "stop"}]})
        self._send(404, {"error": "stub: unknown " + p})


def fire(url, secret, transcript_id="tr-stub-1", meeting_id="m-stub-1"):
    payload = json.dumps({"id": "wh1", "name": "plady-wiki-webex-transcripts", "resource": "meetingTranscripts", "event": "created",
                          "created": "2026-09-04T02:06:00Z", "data": {"id": transcript_id, "meetingId": meeting_id}}).encode()
    sig = hmac.new(secret.encode(), payload, hashlib.sha1).hexdigest()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json", "X-Spark-Signature": sig})
    with urllib.request.urlopen(req, timeout=30) as r:
        print("webhook ->", r.status, r.read()[:200])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=18790); ap.add_argument("--transcript"); ap.add_argument("--title")
    ap.add_argument("--fire"); ap.add_argument("--secret"); ap.add_argument("--bad-signature", action="store_true")
    ap.add_argument("--transcript-id", default="tr-stub-1"); ap.add_argument("--meeting-id", default="m-stub-1")
    a = ap.parse_args()
    if a.fire:
        fire(a.fire, ("wrong-" + (a.secret or "")) if a.bad_signature else a.secret, a.transcript_id, a.meeting_id); sys.exit(0)
    if a.transcript: STATE["transcript"] = open(a.transcript, encoding="utf-8").read()
    if a.title: STATE["title"] = a.title
    print(f"stub listening on :{a.port}", file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()
