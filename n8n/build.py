#!/usr/bin/env python3
"""Assemble n8n workflow JSON from n8n/src/*.js.

The Code nodes are the substance of these workflows and JSON strings are a bad
place to maintain JavaScript. Edit the .js files, run `python3 n8n/build.py`,
commit both. Deploy imports n8n/workflows/*.json (scripts/ec2-deploy.sh).
"""
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent
SRC, OUT = ROOT / "src", ROOT / "workflows"


def js(name, *prefix):
    parts = [(SRC / p).read_text() for p in prefix] + [(SRC / name).read_text()]
    return "\n".join(p.rstrip("\n") for p in parts) + "\n"


def code(id_, name, x, y, source, *prefix):
    return {"id": id_, "name": name, "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [x, y],
            "parameters": {"jsCode": js(source, *prefix)}}


def http_oauth(id_, name, x, y, url, **extra):
    p = {"url": url, "authentication": "genericCredentialType", "genericAuthType": "oAuth2Api", "options": {"timeout": 30000}}
    p.update(extra)
    return {"id": id_, "name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [x, y], "parameters": p}


def call_ingest(id_, x, y):
    return {"id": id_, "name": "wiki-ingest-raw", "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.2, "position": [x, y],
            "parameters": {"workflowId": {"__rl": True, "value": "wiki-ingest-raw", "mode": "id"},
                           "workflowInputs": {"mappingMode": "passthrough"}, "options": {"waitForSubWorkflow": True}}}


def chain(*names):
    return {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(names, names[1:])}


def wf(id_, description, nodes, connections, active):
    return {"id": id_, "name": id_, "active": active,
            "settings": {"executionOrder": "v1", "saveManualExecutions": True, "timezone": "Asia/Seoul"},
            "meta": {"description": description}, "nodes": nodes, "connections": connections}


WEBEX = "={{ ($env.WEBEX_API_BASE || 'https://webexapis.com') + '/v1/"

workflows = [
    wf("wiki-ingest-raw",
       "공용 뒤단: 정규화된 회의 원문 1건 → wiki_apply archive(raw 보관) → wiki_ingest_plan → Hermes 초안 → wiki_apply knowledge. Webex/Slack 앞단이 Execute Workflow 로 호출. docs/webex-ingest.md",
       [{"id": "trigger", "name": "From caller", "type": "n8n-nodes-base.executeWorkflowTrigger", "typeVersion": 1.1, "position": [0, 0],
         "parameters": {"inputSource": "passthrough"}},
        code("archive", "Archive raw (wiki_apply)", 220, 0, "archive.js", "mcp_client.js"),
        code("compile", "Compile (Hermes → wiki_apply)", 440, 0, "compile.js", "mcp_client.js")],
       # n8n 2.x refuses to run a sub-workflow that is not published: keep it active.
       chain("From caller", "Archive raw (wiki_apply)", "Compile (Hermes → wiki_apply)"), True),

    wf("webex-transcript-ingest",
       "Webex 회의 transcript 생성 웹훅 → 서명 검증 → 회의·transcript 수집 → wiki-ingest-raw. docs/webex-ingest.md",
       [{"id": "webhook", "name": "Webex webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 0], "webhookId": "webex-transcript",
         "parameters": {"httpMethod": "POST", "path": "webex-transcript", "responseMode": "onReceived", "options": {"rawBody": True}}},
        code("verify", "Verify signature", 220, 0, "webex_verify.js"),
        http_oauth("meeting", "Get meeting", 440, 0, WEBEX + "meetings/' + $json.meetingId }}"),
        http_oauth("transcript", "Download transcript", 660, 0,
                   WEBEX + "meetingTranscripts/' + $('Verify signature').item.json.transcriptId + '/download' }}",
                   sendQuery=True, queryParameters={"parameters": [{"name": "format", "value": "txt"}]},
                   options={"timeout": 120000, "response": {"response": {"responseFormat": "text", "outputPropertyName": "transcript"}}}),
        code("normalize", "Normalize", 880, 0, "webex_normalize.js"),
        call_ingest("ingest", 1100, 0)],
       chain("Webex webhook", "Verify signature", "Get meeting", "Download transcript", "Normalize", "wiki-ingest-raw"), True),

    wf("webex-register-webhook",
       "1회 실행: Webex 에 meetingTranscripts/created 웹훅을 등록한다 (secret 은 컨테이너 env 에서). docs/webex-ingest.md",
       [{"id": "manual", "name": "Run once", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 0], "parameters": {}},
        http_oauth("list", "List existing webhooks", 220, 0, WEBEX + "webhooks' }}",
                   sendQuery=True, queryParameters={"parameters": [{"name": "max", "value": "100"}]}),
        code("decide", "Already registered?", 440, 0, "webex_register_decide.js"),
        {"id": "if", "name": "Need to create", "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [660, 0],
         "parameters": {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                                       "conditions": [{"id": "c1", "leftValue": "={{ $json.skip }}", "rightValue": False, "operator": {"type": "boolean", "operation": "equals"}}],
                                       "combinator": "and"}, "options": {}}},
        http_oauth("create", "Create webhook", 880, -80, WEBEX + "webhooks' }}", method="POST", sendBody=True, specifyBody="json",
                   jsonBody="={{ JSON.stringify($json.body) }}")],
       {**chain("Run once", "List existing webhooks", "Already registered?", "Need to create"),
        "Need to create": {"main": [[{"node": "Create webhook", "type": "main", "index": 0}], []]}}, False),

    wf("slack-huddle-notes-ingest",
       "Slack Events API → 서명 검증·URL challenge → 허들 AI 노트 캔버스가 붙은 메시지만 → 캔버스 내용 수집 → wiki-ingest-raw. docs/webex-ingest.md",
       [{"id": "webhook", "name": "Slack events", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 0], "webhookId": "slack-events",
         "parameters": {"httpMethod": "POST", "path": "slack-events", "responseMode": "responseNode", "options": {"rawBody": True}}},
        code("verify", "Verify & classify", 220, 0, "slack_verify.js"),
        {"id": "respond", "name": "Respond 200", "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": [440, 0],
         "parameters": {"respondWith": "text", "responseBody": "={{ $json.respond }}", "options": {"responseCode": 200}}},
        {"id": "if", "name": "Is huddle notes", "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [660, 0],
         "parameters": {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                                       "conditions": [{"id": "c1", "leftValue": "={{ $json.ignore }}", "rightValue": False, "operator": {"type": "boolean", "operation": "equals"}}],
                                       "combinator": "and"}, "options": {}}},
        code("fetch", "Fetch canvas", 880, -80, "slack_fetch.js"),
        call_ingest("ingest", 1100, -80)],
       {**chain("Slack events", "Verify & classify", "Respond 200", "Is huddle notes"),
        "Is huddle notes": {"main": [[{"node": "Fetch canvas", "type": "main", "index": 0}], []]},
        **chain("Fetch canvas", "wiki-ingest-raw")}, True),
]

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for w in workflows:
        (OUT / f"{w['id']}.json").write_text(json.dumps(w, ensure_ascii=False, indent=2) + "\n")
        print("wrote", w["id"], len(w["nodes"]), "nodes")
