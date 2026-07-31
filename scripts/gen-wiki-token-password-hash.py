#!/usr/bin/env python3
"""wiki-auth 발급기용 비밀번호 해시 생성 (docs/wiki-token-issuer.md).

비밀번호를 프롬프트로 받아(에코 없음) PBKDF2 해시만 출력한다. 출력 형식은
pbkdf2_sha256:<iters>:<salt_hex>:<hash_hex> — '$' 없이 콜론 구분이라
.env/compose 보간과 충돌하지 않는다. 비밀번호 원문은 어디에도 저장하지 않는다.

사용:
  scripts/gen-wiki-token-password-hash.py
  # 출력된 해시를 사람이 SSM SecureString 으로 저장:
  #   /plady/agent-platform/<env>/wiki-token-password-hash
"""
import getpass
import hashlib
import secrets
import sys

ITERATIONS = 600_000

password = getpass.getpass("wiki token password: ")
confirm = getpass.getpass("again: ")
if password != confirm:
    sys.exit("mismatch — aborted")
if len(password) < 12:
    sys.exit("12자 이상을 사용하세요 — aborted")

salt = secrets.token_hex(16)
digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
print(f"pbkdf2_sha256:{ITERATIONS}:{salt}:{digest}")
