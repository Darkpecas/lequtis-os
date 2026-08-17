#!/data/data/com.termux/files/usr/bin/sh
cd "$HOME/LeQutisOS" || exit 1
mkdir -p logs
exec python core/lequtis.py daemon 900 >> logs/daemon.log 2>&1
