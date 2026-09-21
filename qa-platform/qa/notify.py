"""Slack incoming webhook — WIKI_SLACK_WEBHOOK_URL 재사용. 실패해도 조용히 넘어간다(fail-open)."""
from __future__ import annotations

import threading

from . import httpx


def slack(url: str, text: str):
    if not url:
        return

    def _send():
        httpx.request("POST", url, body={"text": text}, timeout=10)

    threading.Thread(target=_send, daemon=True).start()
