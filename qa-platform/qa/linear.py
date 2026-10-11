"""Linear 이슈 만들기 (docs/qa-platform-v2.md §17). 사람이 버튼을 눌렀을 때만 부른다.

키는 SSM qa-linear-token 의 개인 API 키다. 이슈 작성자는 키 주인으로 남고 담당자는 비운다.
상태는 팀에 Triage 가 켜져 있으면 Triage, 없으면 Backlog.
"""
from __future__ import annotations

import time

from . import httpx

API = "https://api.linear.app/graphql"


class LinearError(RuntimeError):
    pass


class Linear:
    def __init__(self, token: str, team_key: str = "MOI", timeout: int = 20):
        self.token, self.team_key, self.timeout = token, team_key, timeout
        self._team: dict | None = None
        self._team_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _gql(self, query: str, variables: dict | None = None) -> dict:
        if not self.token:
            raise LinearError("Linear API 키(SSM qa-linear-token)가 없다")
        r = httpx.request("POST", API, headers={"Authorization": self.token, "Content-Type": "application/json"},
                          body={"query": query, "variables": variables or {}}, timeout=self.timeout)
        if r.error or r.status >= 300:
            raise LinearError(f"Linear API {r.status or r.error}: {(r.text or '')[:200]}")
        d = r.json or {}
        if d.get("errors"):
            raise LinearError("Linear API: " + "; ".join(str(e.get("message")) for e in d["errors"])[:300])
        return d.get("data") or {}

    # ---- 팀 정보 (상태·라벨·프로젝트 이름 → id). 10분 캐시 --------------------------------------
    def team(self) -> dict:
        if self._team and time.time() - self._team_at < 600:
            return self._team
        # 한 번에 묻으면 Linear 가 "Query too complex" 로 거절한다(2026-10-11) — 셋으로 나눠 묻는다
        d = self._gql("""query($key: String!) { teams(filter: {key: {eq: $key}}) { nodes { id key name states { nodes { id name type } } } } }""",
                      {"key": self.team_key})
        nodes = (d.get("teams") or {}).get("nodes") or []
        if not nodes:
            raise LinearError(f"Linear 팀 {self.team_key} 를 찾지 못했다")
        t = nodes[0]
        d2 = self._gql("""query($id: String!) { team(id: $id) { labels(first: 100) { nodes { id name } } projects(first: 50) { nodes { id name } } } }""",
                       {"id": t["id"]})
        d3 = self._gql("""query { issueLabels(first: 100, filter: {team: {null: true}}) { nodes { id name } } }""")
        tm = d2.get("team") or {}
        labels = {x["name"]: x["id"] for x in ((d3.get("issueLabels") or {}).get("nodes") or [])}
        labels.update({x["name"]: x["id"] for x in ((tm.get("labels") or {}).get("nodes") or [])})
        self._team = {"id": t["id"], "key": t["key"], "name": t.get("name"),
                      "states": (t.get("states") or {}).get("nodes") or [],
                      "labels": labels,
                      "projects": {x["name"]: x["id"] for x in ((tm.get("projects") or {}).get("nodes") or [])}}
        self._team_at = time.time()
        return self._team

    def start_state(self) -> dict:
        """이슈를 만들 상태: Triage 가 켜져 있으면 Triage, 아니면 Backlog. {id, name, note}."""
        states = self.team()["states"]
        tri = next((s for s in states if s.get("type") == "triage"), None)
        if tri:
            return {**tri, "note": None}
        back = next((s for s in states if s.get("type") == "backlog"), None)
        if not back:
            raise LinearError("Linear 팀에 Triage 도 Backlog 상태도 없다")
        return {**back, "note": "팀에 Triage 가 꺼져 있어 Backlog 에 만든다. Linear 팀 설정에서 Triage 를 켜면 Triage 로 간다"}

    # ---- 이슈 --------------------------------------------------------------------------------------
    def create_issue(self, *, title: str, description: str, labels: list[str], project: str | None) -> dict:
        t = self.team()
        missing = [n for n in labels if n not in t["labels"]]
        if missing:
            raise LinearError(f"Linear 에 없는 라벨: {', '.join(missing)}")
        if project and project not in t["projects"]:
            raise LinearError(f"Linear 팀 {t['key']} 에 없는 프로젝트: {project}")
        inp = {"teamId": t["id"], "title": title, "description": description, "stateId": self.start_state()["id"],
               "labelIds": [t["labels"][n] for n in labels]}
        if project:
            inp["projectId"] = t["projects"][project]
        d = self._gql("""mutation($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier url title state { name type } } } }""", {"input": inp})
        res = d.get("issueCreate") or {}
        if not res.get("success") or not res.get("issue"):
            raise LinearError("Linear 가 이슈를 만들지 못했다")
        return res["issue"]

    def comment(self, issue_id: str, body: str) -> None:
        d = self._gql("""mutation($input: CommentCreateInput!) { commentCreate(input: $input) { success } }""",
                      {"input": {"issueId": issue_id, "body": body}})
        if not (d.get("commentCreate") or {}).get("success"):
            raise LinearError("Linear 가 댓글을 달지 못했다")

    def states_of(self, issue_ids: list[str]) -> dict[str, dict]:
        """이슈 uuid → {identifier, state, type}. 화면을 열 때 읽는다(webhook 없음)."""
        ids = [i for i in dict.fromkeys(issue_ids) if i]
        if not ids:
            return {}
        d = self._gql("""query($ids: [ID!]) { issues(filter: {id: {in: $ids}}, first: 100) {
  nodes { id identifier url state { name type } } } }""", {"ids": ids})
        return {n["id"]: {"identifier": n["identifier"], "url": n.get("url"), "state": (n.get("state") or {}).get("name"),
                          "type": (n.get("state") or {}).get("type")} for n in ((d.get("issues") or {}).get("nodes") or [])}
