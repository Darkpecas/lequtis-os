#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
cd "$ROOT"

export LEQUTIS_ROOT="$ROOT"
export LEQUTIS_STATE="${LEQUTIS_STATE:-$ROOT/state}"

echo "=== LEQUTIS DOCTOR ==="

python3 -m py_compile core/lequtis.py core/workers.py core/skills.py core/verifier.py core/access_parity.py
python3 core/lequtis.py init

echo
echo "Database:"
ls -lh state/lequtis.db 2>/dev/null || ls -lh "$LEQUTIS_STATE/lequtis.db"

echo
echo "Integrity smoke test:"
python3 core/lequtis.py heartbeat >/dev/null
python3 core/lequtis.py verify
python3 core/lequtis.py parity

echo
echo "Disposable autonomous loop suite:"
python3 tests/autonomous_loop_test.py
python3 tests/test_skills_verifier_parity.py

echo "PASS: LeQutis kernel executable + autonomous loop verified."
