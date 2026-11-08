# LeQutisOS kernel

LOCAL PROOF, NOT LIVE VPS VERIFIED.

This directory is the working kernel extended from public commit `dd77615b97872ee25a98ef95b6314ab177252af6`. It is not GitHub `main`, and pull request 1 was not merged.

`database/schema.sql` creates the tables `core/lequtis.py` creates, at revision `lequtis-os-kernel-3`. Opening a database from the unmodified `dd77615` kernel fails closed and does not alter it.

`goal --key` replays the same title without a second agenda item. A different title with that key is rejected. `run-once` writes one allowlisted artifact and asks `core/verifier_main.py`, a separate process, to check its path, hash, and correlation id. A rejected verdict leaves the agenda incomplete. `recover` does not take a lease whose process is still alive. After that process is killed, the old lease token cannot complete the agenda.

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
```
