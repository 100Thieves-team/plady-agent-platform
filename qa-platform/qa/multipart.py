"""스크립트의 파일 업로드(request.multipart). 파일 내용은 플랫폼이 만든 표본을 쓴다 — 레포에 파일을 두지 않는다.

request:
  method: POST
  path: /v1/members/me/resumes
  multipart:
    file: {sample: pdf, filename: "[QA] 이력서 {{rand}}.pdf"}
    memo: 글자 값도 된다

표본: pdf(1쪽 PDF) · pdf_oversize(10MB 를 넘는 PDF) · text(PDF 가 아닌 글 파일) · empty(0바이트).
"""
from __future__ import annotations

import secrets

SAMPLES = ("pdf", "pdf_oversize", "text", "empty")
_DEFAULTS = {"pdf": ("sample.pdf", "application/pdf"), "pdf_oversize": ("oversize.pdf", "application/pdf"),
             "text": ("sample.txt", "text/plain"), "empty": ("empty.pdf", "application/pdf")}
LIMIT_BYTES = 10 * 1024 * 1024


def _pdf(lines: list[str]) -> bytes:
    content = "BT /F1 12 Tf 72 720 Td 16 TL " + " ".join(f"({x}) Tj T*" for x in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n"
    return out.encode("latin-1")


def sample_bytes(kind: str) -> bytes:
    if kind == "pdf":
        return _pdf(["QA test resume", "Backend developer, 3 years. Kotlin, Spring Boot, MySQL.", "Built REST APIs and batch jobs."])
    if kind == "pdf_oversize":
        base = _pdf(["QA oversize resume"])
        return base + b"%" + b"0" * (LIMIT_BYTES + 1024 - len(base)) + b"\n"
    if kind == "text":
        return "QA 테스트용 글 파일. PDF 가 아니다.\n".encode("utf-8")
    if kind == "empty":
        return b""
    raise ValueError(f"모르는 표본 {kind}")


def validate(value) -> str | None:
    """request.multipart 형식 오류 메시지. 맞으면 None."""
    if not isinstance(value, dict) or not value:
        return "multipart 는 필드 이름 → 값(글자) 또는 {sample, filename, content_type} 맵"
    for k, v in value.items():
        if isinstance(v, dict):
            if v.get("sample") not in SAMPLES:
                return f"multipart.{k}.sample 은 {' · '.join(SAMPLES)} 중 하나"
        elif not isinstance(v, (str, int, float, bool)):
            return f"multipart.{k} 는 글자 값이나 파일 표본"
    return None


def encode(fields: dict) -> tuple[str, bytes, dict]:
    """(Content-Type 헤더, 본문, 기록용 요약). 기록에는 파일 내용을 넣지 않는다."""
    boundary = "----qa" + secrets.token_hex(12)
    parts, summary = [], {}
    for name, v in fields.items():
        if isinstance(v, dict):
            dname, dtype = _DEFAULTS[v["sample"]]
            fname, ctype = str(v.get("filename") or dname), str(v.get("content_type") or dtype)
            data = sample_bytes(v["sample"])
            head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'
            parts.append(head.encode("utf-8") + data + b"\r\n")
            summary[name] = {"sample": v["sample"], "filename": fname, "content_type": ctype, "bytes": len(data)}
        else:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{v}\r\n'.encode("utf-8"))
            summary[name] = v
    body = b"".join(parts) + f"--{boundary}--\r\n".encode("utf-8")
    return f"multipart/form-data; boundary={boundary}", body, summary
