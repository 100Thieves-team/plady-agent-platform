"""스프린트 smoke 리마인더 — 알림만 한다. 실행하지 않는다. docs/qa-platform.md §12 P3.

스프린트 종료 QA_SPRINT_REMIND_DAYS 일 전부터, 이번 스프린트에 smoke 런이 하나도 없으면 Slack 에 한 번 알린다.
"한 번" 은 events(action sprint.remind, target 스프린트 번호)로 보장한다. 알림은 사람에게 버튼을 누르라고 말할 뿐이다 —
사람 트리거 원칙(사용자 결정 ①)과 어긋나지 않는다. QA_SPRINT_REMINDER=0 이면 스레드를 띄우지 않는다.
"""
from __future__ import annotations

import threading
import traceback
from datetime import datetime, timedelta, timezone

from .config import Config
from .store import Store

ACTION = "sprint.remind"


def due(now: datetime, sprint: dict, smoke_runs: int, already: bool, days_before: int) -> bool:
    """순수 판정: 마감 days_before 일 전 이후이고, smoke 런이 없고, 아직 안 알렸으면 True."""
    if already or smoke_runs > 0:
        return False
    return now >= sprint["ends_at"] - timedelta(days=days_before)


class Reminder:
    def __init__(self, cfg: Config, store: Store, notify, interval_s: int = 3600):
        self.cfg = cfg
        self.store = store
        self.notify = notify          # (text) -> None
        self.interval_s = interval_s
        self._thread = threading.Thread(target=self._loop, name="qa-sprint-reminder", daemon=True)

    def start(self):
        if not self.cfg.sprint_reminder or not self.cfg.slack_webhook_url:
            return
        self._thread.start()

    def _loop(self):
        while True:
            try:
                self.tick()
            except Exception:
                traceback.print_exc()
            threading.Event().wait(self.interval_s)

    def tick(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        sprint = self.cfg.current_sprint(now)
        since = sprint["starts_at"].isoformat().replace("+00:00", "Z")
        runs = self.store.runs_since(since, "sprint-smoke")
        target = str(sprint["number"])
        already = any(ev.get("target") == target for ev in self.store.list_events(50, None, ACTION))
        if not due(now, sprint, len(runs), already, self.cfg.sprint_remind_days):
            return False
        ends = sprint["ends_at"].astimezone(timezone(timedelta(hours=9))).strftime("%m-%d")
        self.notify(f"[QA] Cycle {target} 스프린트 smoke 가 아직 없다 ({ends} 마감). 대시보드에서 [스프린트 smoke 실행] — {self.cfg.public_url}/")
        self.store.add_event(operator="system", action=ACTION, target=target, detail={"ends_at": since and sprint["ends_at"].isoformat(), "days_before": self.cfg.sprint_remind_days})
        return True
