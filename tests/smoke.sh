#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

test_state="$(mktemp -d "$ROOT/.lequtis-smoke.XXXXXX")"
trap 'rm -rf "$test_state"' EXIT HUP INT TERM
export LEQUTIS_ROOT="$ROOT"
export LEQUTIS_STATE="$test_state"

python3 core/lequtis.py init >/dev/null
python3 core/lequtis.py remember "Disposable smoke-test memory." >/dev/null
python3 core/lequtis.py goal "Remember a smoke-test note through the autonomous loop." >/dev/null

loop_result="$(python3 core/lequtis.py loop)"
printf '%s\n' "$loop_result"
printf '%s\n' "$loop_result" | python3 -c 'import json,sys; result=json.load(sys.stdin); assert result.get("status") == "completed", result'

verify_result="$(python3 core/lequtis.py verify)"
printf '%s\n' "$verify_result"
printf '%s\n' "$verify_result" | python3 -c 'import json,sys; result=json.load(sys.stdin); assert result.get("ok") is True, result'

echo
echo "=== LEQUTIS SMOKE TEST: PASS ==="
