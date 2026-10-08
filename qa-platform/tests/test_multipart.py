"""파일 업로드(request.multipart) — 표본 파일을 만들어 multipart/form-data 로 보낸다."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qa import httpx, multipart  # noqa: E402
from qa.cases import CaseError, parse_one, safety_errors  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.runner import Runner  # noqa: E402
from qa.spec import parse as spec_parse  # noqa: E402
from qa.store import Store  # noqa: E402

CASE = ("id: r\ntitle: t\nsuite: sanity\nactor: qa-host\ncovers: ['op.createResume:201']\nsteps:\n"
        "  - request:\n      method: POST\n      path: /v1/members/me/resumes\n"
        "      multipart: {file: {sample: pdf, filename: '[QA] 이력서.pdf'}, memo: 메모}\n"
        "    covers: ['op.createResume:201']\n    expect: {status: 201}\n")


class MultipartTest(unittest.TestCase):
    def test_samples_and_encode(self):
        self.assertTrue(multipart.sample_bytes("pdf").startswith(b"%PDF-1.4"))
        self.assertGreater(len(multipart.sample_bytes("pdf_oversize")), multipart.LIMIT_BYTES)
        self.assertEqual(multipart.sample_bytes("empty"), b"")
        ctype, body, summary = multipart.encode({"file": {"sample": "pdf", "filename": "[QA] a.pdf"}, "memo": "x"})
        boundary = ctype.split("boundary=")[1]
        self.assertTrue(ctype.startswith("multipart/form-data"))
        self.assertIn(f"--{boundary}--".encode(), body)
        self.assertIn('name="file"; filename="[QA] a.pdf"'.encode(), body)
        self.assertEqual(summary["file"]["content_type"], "application/pdf")

    def test_case_validation(self):
        c = parse_one(CASE)
        self.assertEqual(safety_errors(c), [])
        with self.assertRaises(CaseError):
            parse_one(CASE.replace("sample: pdf", "sample: docx"))
        with self.assertRaises(CaseError):
            parse_one(CASE.replace("memo: 메모}", "memo: 메모}\n      body: {a: 1}"))

    def test_spec_reads_multipart_fields(self):
        doc = {"paths": {"/v1/members/me/resumes": {"post": {"operationId": "createResume", "requestBody": {"content": {"multipart/form-data": {
            "schema": {"type": "object", "required": ["file"], "properties": {"file": {"type": "string", "format": "binary"}}},
            "encoding": {"file": {"contentType": "application/pdf"}}}}}, "responses": {"201": {"description": "ok"}}}}}}
        op = spec_parse(doc)["createResume"]
        self.assertEqual(op.multipart, [{"name": "file", "type": "string", "format": "binary", "required": True, "description": "", "content_type": "application/pdf"}])


class RunnerMultipartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["QA_DATA_DIR"] = self.tmp.name
        os.environ["QA_ACTORS"] = json.dumps({"qa-host": "m1"})
        self.cfg = Config()
        self.store = Store(self.cfg.db_path)
        self.orig = httpx.request

    def tearDown(self):
        httpx.request = self.orig
        for k in ("QA_DATA_DIR", "QA_ACTORS"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def test_runner_sends_multipart(self):
        sent = []

        def fake(method, url, headers=None, body=None, timeout=30, follow_redirects=True):
            if url.endswith("/v1/auth/dev-sessions"):
                return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"accessToken": "tok"}}), 1)
            sent.append((dict(headers or {}), body))
            return httpx.HttpResult(201, {}, json.dumps({"result": "SUCCESS", "data": {"resumeId": "r1"}}), 1)
        httpx.request = fake
        c = parse_one(CASE)
        runner = Runner(self.cfg, self.store, {"r": c})
        rid = self.store.create_run(trigger="manual", operator="bebe", suite=None, env="dev", base_url="https://api.test",
                                    ref="dev", sha=None, pr_number=None, meta={}, cases=[c])
        runner.execute(rid)
        rc = self.store.list_run_cases(rid)[0]
        self.assertEqual(rc["verdict"], "pass", rc["error"])
        headers, body = sent[0]
        self.assertTrue(headers["Content-Type"].startswith("multipart/form-data; boundary="))
        self.assertIsInstance(body, bytes)
        self.assertIn(b"%PDF-1.4", body)
        step = self.store.list_steps(rc["id"])[0]
        self.assertEqual(step["request"]["multipart"]["file"]["filename"], "[QA] 이력서.pdf")
        self.assertNotIn("%PDF", json.dumps(step, ensure_ascii=False))            # 파일 내용은 기록하지 않는다


if __name__ == "__main__":
    unittest.main()
