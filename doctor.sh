#!/data/data/com.termux/files/usr/bin/sh
set -eu
cd "$HOME/LeQutisOS"

echo "=== LEQUTIS DOCTOR ==="

python -m py_compile core/lequtis.py
python core/lequtis.py init

echo
echo "Database:"
ls -lh state/lequtis.db

echo
echo "Integrity smoke test:"
python core/lequtis.py heartbeat >/dev/null

echo "PASS: LeQutis kernel executable."
