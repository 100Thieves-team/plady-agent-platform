"""메일 수신 — QA 전용 메일함을 IMAP 으로 읽어 QA 회원에게 온 알림 메일을 알림함에 넣는다 (docs/qa-platform-v2.md §15.2).

QA 회원 메일 주소는 그 메일함의 `+` 주소다(예: moimyeon.qa+qa-<키>@gmail.com, 백엔드 QA_MEMBER_EMAIL_TEMPLATE).
받기만 한다. 메일은 읽음 표시도 바꾸지 않는다(읽기 전용으로 연다). 어디까지 읽었는지는 settings 에 폴더마다 UID 로 적는다.
"""
from __future__ import annotations

import imaplib
import re
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import inbox as I


class MailReader:
    def __init__(self, cfg, store, resolve):
        """resolve(address) → (base_url, actor) | None — 메일 주소가 어느 테스트 계정 것인지."""
        self.cfg, self.store, self.resolve = cfg, store, resolve
        self._lock = threading.Lock()
        self._last = 0.0
        self.error: str | None = None
        self.last_ok: str | None = None
        self.connect = lambda: imaplib.IMAP4_SSL(cfg.mail_imap_host, timeout=20)     # 테스트가 바꾼다

    def unavailable(self) -> str | None:
        if not (self.cfg.mail_user and self.cfg.mail_password):
            return "QA 메일함(QA_MAIL_USER · QA_MAIL_APP_PASSWORD)이 없다"
        return None

    def mine(self, address: str | None) -> bool:
        """이 메일함의 + 주소인가."""
        if not address or "@" not in self.cfg.mail_user:
            return False
        user, dom = self.cfg.mail_user.lower().split("@", 1)
        a = address.lower()
        return a.endswith("@" + dom) and (a.split("@")[0] == user or a.split("@")[0].startswith(user + "+"))

    def start(self) -> None:
        if self.unavailable():
            return

        def loop():
            while True:
                try:
                    self.poll()
                except Exception:
                    traceback.print_exc()
                time.sleep(max(5, self.cfg.mail_poll))
        threading.Thread(target=loop, name="mail-reader", daemon=True).start()

    def poll(self, *, min_gap: float = 0) -> int:
        """새 메일을 읽어 알림함에 넣는다 → 넣은 수. min_gap 초 안에 다시 부르면 건너뛴다."""
        if self.unavailable():
            return 0
        with self._lock:
            if min_gap and time.monotonic() - self._last < min_gap:
                return 0
            self._last = time.monotonic()
            try:
                n = self._poll()
                self.error, self.last_ok = None, datetime.now(timezone.utc).isoformat(timespec="seconds")
                return n
            except Exception as ex:
                self.error = f"{type(ex).__name__}: {ex}"[:300]
                return 0

    def _folders(self, imap) -> list[str]:
        out = ["INBOX"]
        typ, rows = imap.list()
        for r in rows or []:
            line = r.decode(errors="replace") if isinstance(r, bytes) else str(r)
            if "\\Junk" in line:                          # Gmail 스팸함 — 이름은 언어마다 달라 속성으로 찾는다
                m = re.search(r'"([^"]+)"\s*$', line) or re.search(r"(\S+)\s*$", line)
                if m:
                    out.append(m.group(1))
        return out

    def _poll(self) -> int:
        imap = self.connect()
        added = 0
        try:
            imap.login(self.cfg.mail_user, self.cfg.mail_password)
            for folder in self._folders(imap):
                typ, _ = imap.select(f'"{folder}"', readonly=True)
                if typ != "OK":
                    continue
                validity = (imap.response("UIDVALIDITY")[1] or [b"0"])[0]
                validity = validity.decode() if isinstance(validity, bytes) else str(validity)
                key = f"mail_uid:{folder}:{validity}"
                last = int(self.store.get_setting(key) or 0)
                if last:
                    typ, data = imap.uid("search", None, f"UID {last + 1}:*")
                else:                                      # 처음에는 하루 전부터만
                    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%d-%b-%Y")
                    typ, data = imap.uid("search", None, f"SINCE {since}")
                uids = sorted(int(u) for u in (data[0] or b"").split() if int(u) > last)
                for uid in uids:
                    typ, msg = imap.uid("fetch", str(uid), "(BODY.PEEK[])")
                    raw = next((p[1] for p in msg or [] if isinstance(p, tuple)), None)
                    if raw and self._store(raw):
                        added += 1
                    self.store.set_setting(key, str(uid))
        finally:
            try:
                imap.logout()
            except Exception:
                pass
        return added

    def _store(self, raw: bytes) -> bool:
        item = I.from_mail(raw)
        address = next((a for a in item.get("to_all") or [] if self.mine(a)), None)
        if not address:
            return False                                   # QA 회원 주소로 온 메일만 담는다
        who = self.resolve(address)
        base, actor = who if who else (self.cfg.target_base_url, None)
        received = None
        try:
            from email import message_from_bytes
            d = message_from_bytes(raw).get("Date")
            received = parsedate_to_datetime(d).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if d else None
        except Exception:
            received = None
        return self.store.add_inbox(channel="email", base_url=base, actor=actor, address=address, type=item["type"], title=item["title"],
                                    body=item["body"], link=item["link"], event_id=None, raw=raw.decode("utf-8", errors="replace")[:50000],
                                    dedup=I.dedup_key(item, address), received_at=received) is not None
