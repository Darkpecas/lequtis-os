#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
cd "$ROOT"

test_state="$(mktemp -d "$ROOT/.lequtis-doctor.XXXXXX")"
trap 'rm -rf "$test_state"' EXIT HUP INT TERM
export LEQUTIS_ROOT="$ROOT"
export LEQUTIS_STATE="$test_state"

echo "=== LEQUTIS DOCTOR ==="

python3 -m py_compile core/lequtis.py core/workers.py core/skills.py core/verifier.py core/access_parity.py core/golden_master.py core/failed_hypotheses.py core/routing_contract.py
python3 core/lequtis.py init

echo
echo "Database:"
ls -lh "$LEQUTIS_STATE/lequtis.db"

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
