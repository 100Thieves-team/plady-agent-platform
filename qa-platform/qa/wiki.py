"""llm-wiki 체크아웃(team-wiki-v2) 읽기 — 읽기 전용 볼륨. docs/qa-platform-tc.md §4.5 (안 B).

플랫폼은 `wiki-data` 볼륨을 `/wiki` 에 읽기 전용으로 마운트한다. 여기서
  - `wiki/policy/_src/상태-SSOT.yaml`   정책 TC 의 원천
  - `raw/product/<slug>.md`            PRD 본문 (절 추출)
  - `tools/policy-renderer/render_tests.py`  정책 TC 파생 함수 `cases()` — 복제하지 않고 import 한다
를 읽는다. 락(`.git/llm-wiki.lock`)은 잡지 않는다. 파싱 실패는 1초 뒤 한 번 재시도한다
(wiki-data-sync 가 git pull 로 파일을 바꾸는 순간을 읽었을 수 있다).
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import time
import unicodedata
from pathlib import Path

import yaml

SSOT_REL = Path("wiki/policy/_src/상태-SSOT.yaml")
RENDER_TESTS_REL = Path("tools/policy-renderer/render_tests.py")
PRD_REL = Path("raw/product")
# PRD 요구 id (team-wiki-v2 tools/policy-renderer/prd_reqs.py 와 같은 규칙): 규칙 줄 끝의 `R22`, 표 행은 마지막 칸
_REQ_TAG = re.compile(r"\s`R(\d+)`\s*\|?\s*$")
_REQ_SOURCE = re.compile(r"^PRD/(.+?)\s+(R\d+)\s*$")
_REQ_HEADING = re.compile(r"^#{2,4}\s*(\d+(?:[.-]\d+)*)[.\s]")
_REQ_LIST = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
# PRD 2장 사용자 시나리오 (docs/qa-platform-scenarios.md §2): `### 시나리오 S1: 제목`, 단계 `1. 문장 `R1``, 분기 `\t- 분기: 문장 `R3``
_SCN_HEAD = re.compile(r"^###\s*시나리오\s+(S\d+)\s*[:：]\s*(.+?)\s*$")
_SCN_STEP = re.compile(r"^(\d+)\.\s+(.*)$")
_SCN_BRANCH = re.compile(r"^\s+[-*]\s*분기\s*[:：]\s*(.*)$")
_REQ_ANY = re.compile(r"`(R\d+)`\s*$")


def doc_slug(doc: str) -> str:
    """'룸 참여 및 참여자 관리' → '룸-참여-및-참여자-관리' (render_wiki.doc_slug 와 같은 규칙)."""
    return re.sub(r"\s+", "-", doc.strip())


def file_hash(path: Path) -> str:
    """render_wiki 와 같은 규칙: 파일 바이트 sha256 앞 12자리."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


class WikiError(RuntimeError):
    pass


class Wiki:
    def __init__(self, root: Path | str | None, branch: str = "main", public_url: str = "https://wiki.agent.plady.io"):
        self.root = Path(root) if root else None
        self.branch = branch
        self.public_url = public_url.rstrip("/")
        self._rt_mod = None
        self._rt_mtime: float | None = None
        self._reqs: dict[str, tuple[float, dict]] = {}     # 문서 → (mtime, {R id: {section, text}})

    # ---- 존재 ---------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return bool(self.root) and (self.root / SSOT_REL).is_file()

    @property
    def ssot_path(self) -> Path:
        if not self.root:
            raise WikiError("QA_WIKI_DIR 이 설정되지 않았다")
        return self.root / SSOT_REL

    def head(self) -> str | None:
        """체크아웃의 브랜치 HEAD (표시용). wiki-ui 와 같은 파일을 읽는다."""
        if not self.root:
            return None
        ref = self.root / ".git" / "refs" / "heads" / self.branch
        try:
            if ref.is_file():
                return ref.read_text().strip()[:12] or None
            packed = self.root / ".git" / "packed-refs"
            if packed.is_file():
                for line in packed.read_text().splitlines():
                    if line.endswith(f" refs/heads/{self.branch}"):
                        return line.split()[0][:12]
        except OSError:
            return None
        return None

    # ---- SSOT ---------------------------------------------------------------------
    def read_ssot(self) -> tuple[dict, str]:
        """(파싱된 SSOT, 내용 해시). 반쪽 파일을 읽었을 가능성에 대비해 한 번 재시도."""
        p = self.ssot_path
        last: Exception | None = None
        for attempt in (0, 1):
            try:
                raw = p.read_bytes()
                d = yaml.safe_load(raw.decode("utf-8"))
                if not isinstance(d, dict) or "gates" not in d:
                    raise WikiError("SSOT 형식이 아니다 (gates 없음)")
                return d, hashlib.sha256(raw).hexdigest()[:12]
            except (OSError, yaml.YAMLError, UnicodeDecodeError, WikiError) as e:
                last = e
                if attempt == 0:
                    time.sleep(1)
        raise WikiError(f"SSOT 읽기 실패: {last}")

    def ssot_hash(self) -> str | None:
        try:
            return file_hash(self.ssot_path)
        except (OSError, WikiError):
            return None

    # ---- render_tests.cases() import -------------------------------------------------
    def render_tests(self):
        """team-wiki-v2 의 render_tests 모듈. 파일이 바뀌면 다시 읽는다."""
        if not self.root:
            raise WikiError("QA_WIKI_DIR 이 설정되지 않았다")
        p = self.root / RENDER_TESTS_REL
        if not p.is_file():
            raise WikiError(f"{RENDER_TESTS_REL} 이 위키 체크아웃에 없다")
        mtime = p.stat().st_mtime
        if self._rt_mod is None or self._rt_mtime != mtime:
            spec = importlib.util.spec_from_file_location("wiki_render_tests", p)
            if spec is None or spec.loader is None:
                raise WikiError("render_tests.py 를 import 할 수 없다")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for fn in ("cases", "reject_name", "success_name", "OWNER_PKG"):
                if not hasattr(mod, fn):
                    raise WikiError(f"render_tests.py 에 {fn} 이 없다 — team-wiki-v2 쪽 시그니처가 바뀌었다")
            self._rt_mod, self._rt_mtime = mod, mtime
        return self._rt_mod

    # ---- PRD ----------------------------------------------------------------------
    def prd_path(self, doc: str) -> Path | None:
        if not self.root:
            return None
        p = self.root / PRD_REL / f"{doc_slug(doc)}.md"
        return p if p.is_file() else None

    def prd_reqs(self, doc: str) -> dict[str, dict]:
        """PRD 의 요구 id → {section, text}. 파일이 바뀔 때만 다시 읽는다."""
        p = self.prd_path(doc)
        if not p:
            return {}
        mt = p.stat().st_mtime
        hit = self._reqs.get(doc)
        if hit and hit[0] == mt:
            return hit[1]
        out, sec = {}, None
        for ln in p.read_text(encoding="utf-8").split("\n"):
            h = _REQ_HEADING.match(ln)
            if h:
                sec = h.group(1)
                continue
            t = _REQ_TAG.search(ln)
            if t:
                text = " ".join(_REQ_LIST.sub("", _REQ_TAG.sub("", ln)).strip().strip("|").split())
                out[f"R{t.group(1)}"] = {"section": sec, "text": text}
        self._reqs[doc] = (mt, out)
        return out

    def prd_docs(self) -> list[str]:
        """위키의 PRD 문서 이름 (파일 이름의 하이픈을 공백으로). `_index.md` 는 뺀다."""
        if not self.root or not (self.root / PRD_REL).is_dir():
            return []
        return sorted(unicodedata.normalize("NFC", p.stem).replace("-", " ") for p in (self.root / PRD_REL).glob("*.md") if not p.name.startswith("_"))

    def prd_scenarios(self, doc: str) -> list[dict]:
        """PRD 2장의 시나리오 → [{id, title, steps: [{no, text, req, branch, parent}]}]. 분기는 바로 앞 단계 번호가 parent.
        요구 id 가 없는 줄도 넣는다(req None). `> ` 인용과 다른 절은 건너뛴다."""
        p = self.prd_path(doc)
        if not p:
            return []
        out, cur, in_ch2, last_no = [], None, False, None
        for ln in p.read_text(encoding="utf-8").split("\n"):
            if ln.startswith("## "):
                in_ch2 = bool(re.match(r"^##\s*2[.\s]", ln))
                cur = None
                continue
            if not in_ch2:
                continue
            if ln.startswith("###"):
                m = _SCN_HEAD.match(ln)
                cur = {"id": m.group(1), "title": m.group(2), "steps": []} if m else None
                if cur:
                    out.append(cur)
                last_no = None
                continue
            if cur is None:
                continue
            r = _REQ_ANY.search(ln)
            req = r.group(1) if r else None
            text = " ".join(_REQ_ANY.sub("", ln).split())
            m = _SCN_STEP.match(ln)
            if m:
                last_no = int(m.group(1))
                cur["steps"].append({"no": last_no, "text": " ".join(_REQ_ANY.sub("", m.group(2)).split()), "req": req, "branch": False, "parent": None})
                continue
            b = _SCN_BRANCH.match(ln)
            if b:
                cur["steps"].append({"no": None, "text": " ".join(_REQ_ANY.sub("", b.group(1)).split()), "req": req, "branch": True, "parent": last_no})
        return out

    def resolve_source(self, ref: str) -> dict | None:
        """SSOT 출처 한 줄 → {doc, section, req?, text?}. 'PRD/룸 생성 R22' 는 그 요구의 절과 문장까지, '§4.3' 은 절만.
        DEC-nnn 등은 None."""
        m = _REQ_SOURCE.match(str(ref).strip())
        if m:
            doc, rid = m.group(1).strip(), m.group(2)
            info = self.prd_reqs(doc).get(rid) or {}
            return {"doc": doc, "section": info.get("section"), "req": rid, "text": info.get("text")}
        parsed = self.parse_source(str(ref))
        return {"doc": parsed[0], "section": parsed[1]} if parsed else None

    def prd_url(self, doc: str) -> str:
        return f"{self.public_url}/raw/product/{doc_slug(doc)}/"

    def prd_section(self, doc: str, section: str, max_lines: int = 80) -> str | None:
        """PRD 의 `### 4.7 …` 절 본문(헤딩 포함)을 다음 같은 급 이상 헤딩 전까지. `4` 처럼 큰 절은 `## 4.` 를 찾는다."""
        p = self.prd_path(doc)
        if not p:
            return None
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        sec = section.strip().rstrip(".")
        head_rx = re.compile(r"^(#{1,6})\s+" + re.escape(sec) + r"(?:[.\s]|$)")
        start, level = None, 0
        for i, line in enumerate(lines):
            m = head_rx.match(line)
            if m:
                start, level = i, len(m.group(1))
                break
        if start is None:
            return None
        out = [lines[start]]
        for line in lines[start + 1:]:
            m = re.match(r"^(#{1,6})\s", line)
            if m and len(m.group(1)) <= level:
                break
            out.append(line)
            if len(out) >= max_lines:
                out.append("…")
                break
        return "\n".join(out).strip()

    @staticmethod
    def parse_source(ref: str) -> tuple[str, str] | None:
        """'PRD/룸 생성 §4.7' → ('룸 생성', '4.7'). DEC-nnn 등은 None."""
        m = re.match(r"^PRD/(.+?)\s*§\s*([0-9][0-9.]*)\s*$", ref.strip())
        return (m.group(1).strip(), m.group(2).rstrip(".")) if m else None
