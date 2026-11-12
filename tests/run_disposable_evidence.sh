#!/usr/bin/env bash
# Shared disposable suite used by LeQutis GitHub Actions.
# Local execution evidence only. Not a live Hostinger or VPS proof.
set -euo pipefail
cd "$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export LEQUTIS_HERMES_QUERY=""
export LEQUTIS_WORKER=deterministic

python3 tests/autonomous_loop_test.py
python3 tests/test_skills_verifier_parity.py
python3 tests/test_workers.py
python3 tests/test_bridge.py
python3 tests/test_host_preflight.py
python3 tests/test_hermes_route.py
python3 tests/test_host_receipt.py
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v

echo "CI tests disposable/local behavior only."
echo "No Hostinger tunnel, canonical production database, or live Hermes claims."
