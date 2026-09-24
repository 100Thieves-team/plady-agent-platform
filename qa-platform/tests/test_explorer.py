"""API 호출 화면 P5a (docs/qa-platform-api.md §5.3·§5.6) — op → 테스트 조건 역색인, QA 배지 요약, 호출 카드(Normal/Swagger) 렌더, 프리필, 테스트 조건 목록 op 필터."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App  # noqa: E402
from qa import ui  # noqa: E402
from qa.catalog import domain_of_path  # noqa: E402
from qa.config import Config  # noqa: E402

# 위키 체크아웃 — 기본은 레포 옆 wiki-workspace, QA_TEST_WIKI_DIR 로 바꿀 수 있다 (예: SSOT 조각 브랜치 worktree)
WIKI_DIR = Path(os.environ.get("QA_TEST_WIKI_DIR") or ROOT.parent / "wiki-workspace")
SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"


class ExplorerCardTest(unittest.TestCase):
    """App 없이 spec 만으로 카드가 그려지는지 — 정본이 하나(path·query 는 Normal 칸, 본문은 Swagger 의 JSON 칸)인지 확인."""

    def setUp(self):
        from qa.spec import Spec
        self.spec = Spec("", Path(tempfile.mkdtemp()), file=str(SPEC_FIXTURE)).get()

    def render(self, op_id, **kw):
        kw.setdefault("actors", ["qa-host"]); kw.setdefault("operators", ["bebe"]); kw.setdefault("operator", "bebe"); kw.setdefault("q", "")
        return ui.explorer(self.spec, self.spec.ops[op_id], None, [], domain_of=domain_of_path, **kw)

    def test_body_keys_become_normal_fields_and_json_stays_single_source(self):
        h = self.render("createRoom")
        self.assertIn('data-bk="postingId"', h)                       # Normal: 본문 최상위 키가 칸으로
        self.assertIn('data-type="number"', h)                        # 예시 타입 힌트
        self.assertEqual(h.count('<textarea name="body"'), 1)                   # 본문 정본은 Swagger 의 JSON 칸 하나뿐
        self.assertIn('<span class="m post">POST</span>', h)          # 메서드 배지
        self.assertIn('id="seg"', h)                                  # Normal | Swagger 토글
        self.assertIn('class="qab none"', h)                          # qa=None → "TC ?"

    def test_path_param_is_real_input_in_normal_and_mirror_in_swagger(self):
        h = self.render("roomDetail", prefill={"p": {"roomId": "r-1"}, "view": "swagger"})
        self.assertIn('name="p_roomId" value="r-1" required', h)      # Normal 의 진짜 칸 (프리필)
        self.assertIn('data-mirror="p_roomId"', h)                    # Swagger 표의 거울 칸
        self.assertIn('data-view="swagger"', h)                       # view 프리필
        self.assertNotIn('<textarea name="body"', h)                  # GET 은 본문 없음

    def test_prefill_body_overrides_example(self):
        h = self.render("createRoom", prefill={"body": '{"postingId": 9}', "actor": "qa-host"})
        self.assertIn('{&quot;postingId&quot;: 9}', h)
        self.assertIn('value="qa-host" checked', h)

    def test_list_groups_by_domain_and_marks_selected(self):
        h = self.render("termsList")
        self.assertIn("<summary>catalog", h)
        self.assertIn("<summary>room", h)
        self.assertIn('class="opi on" data-op="termsList"', h)
        self.assertIn('class="star" data-op="termsList"', h)

    def test_path_param_recovery_for_reopen(self):
        self.assertEqual(ui._path_param_values("/v1/rooms/{roomId}/applications", "/v1/rooms/abc/applications"), {"roomId": "abc"})
        self.assertEqual(ui._path_param_values("/v1/rooms/{roomId}", "/v1/rooms"), {})


@unittest.skipUnless((WIKI_DIR / "wiki/policy/_src/상태-SSOT.yaml").is_file(), "wiki-workspace 체크아웃 없음")
class OpQaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {"QA_DATA_DIR": self.tmp.name, "QA_WIKI_DIR": str(WIKI_DIR), "QA_SPEC_FILE": str(SPEC_FIXTURE),
               "QA_ACTORS": json.dumps({"qa-host": "m1"}), "QA_FIXTURES": json.dumps({"postingId": 1}), "QA_PUBLIC_URL": "https://qa.test"}
        self.app = App(Config(env))
        self.cat = self.app.current_catalog()

    def tearDown(self):
        self.tmp.cleanup()

    def test_by_operation_covers_three_layers(self):
        idx = self.cat.by_operation()
        self.assertIn("op.createRoom:200", idx["createRoom"])            # API 계약 TC (operation)
        self.assertTrue(any(i.startswith("G.room.create#") or i == "C.room.create" for i in idx["createRoom"]))   # 비즈니스 규칙 TC (bindings)
        self.assertIn("PRD.룸-생성.4.1#1", idx["roomFormOptions"])         # 수동 작성 TC (operations)
        self.assertIs(idx, self.cat.by_operation())                       # 캐시

    def test_op_qa_summary_and_badge(self):
        qa = self.app.op_qa("termsList")
        self.assertEqual(qa["tc"], len(self.cat.by_operation()["termsList"]))
        self.assertIn("catalog.terms", qa["scripts"])                    # cases/platform.yaml 이 op.termsList:200 을 검증
        self.assertGreaterEqual(qa["covered"], 1)
        self.assertIsNone(qa["last"])                                     # 실행 기록 없음
        h = ui.qa_badge(qa, "termsList")
        self.assertIn(f"테스트 조건 {qa['tc']}", h)
        self.assertIn('href="/apis/termsList"', h)
        self.assertIn("실행 기록 없음", h)
        self.assertEqual(self.app.op_qa("noSuchOp")["tc"], 0)
        self.assertIn("테스트 조건 없음", ui.qa_badge(self.app.op_qa("noSuchOp"), "noSuchOp"))

    def test_catalog_list_op_filter_crosses_domains(self):
        cov = self.app.coverage(self.cat)
        ids = self.cat.by_operation()["createRoom"]
        h = ui.catalog_list(self.cat, cov, {}, domain="room", layer="", only="", changes={}, wiki_available=True, op="createRoom", op_ids=ids)
        self.assertIn("의 테스트 조건만 보인다", h)
        for i in ids:
            self.assertIn(ui.tc_link(i), h)
        self.assertNotIn("op.termsList:200", h)


if __name__ == "__main__":
    unittest.main()
