#!/usr/bin/env bash
set -euo pipefail

python3 "$(dirname "$0")/normalize_legacy_raw.py" "$@"
