#!/data/data/com.termux/files/usr/bin/sh
set -eu
cd "$HOME/LeQutisOS"

python core/lequtis.py init >/dev/null

python core/lequtis.py remember \
"Initial LeQutis memory: A71 is the current build and runtime host." >/dev/null

python core/lequtis.py goal \
"Build the first autonomous notice-think-act-learn loop." >/dev/null

python core/lequtis.py heartbeat

echo
echo "=== LEQUTIS SMOKE TEST: PASS ==="
