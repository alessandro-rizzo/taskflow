#!/usr/bin/env bash
# T1 W3 specification validator and deterministic negative-mutation suite.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

root="$(cd "$(dirname "$0")" && pwd)"

python3 "$root/test_validate.py"
python3 "$root/validate.py" "$root/examples"
