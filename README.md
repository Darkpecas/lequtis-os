# LeQutisOS

LeQutisOS local foundation.

## Architecture

- `core/` — core runtime
- `database/` — persistent state schema
- `bridges/` — external integrations
- `telemetry/` — telemetry
- `tasks/` — task execution state
- `logs/` — runtime logs

Runtime databases and logs are intentionally excluded from Git.

## Verification target

The autonomous execution path must eventually prove:

goal -> task -> execution -> state -> result -> audit

The kernel includes a constrained execution loop for `remember: ...` agenda
items. It records execution phases in the hash-chained event log, stores the
result and learned experience, and completes the agenda item. Other goal types
are blocked with an explicit failure; no shell or arbitrary system actions are
available.

## Execution

Run one deterministic action with:

```sh
python core/lequtis.py goal "remember: a fact to retain"
python core/lequtis.py run-once
python core/lequtis.py verify-events
```

`python core/lequtis.py daemon 900` checks for work every 900 seconds. After an
unexpected process stop, `recover` marks unfinished executions as interrupted
and blocks them. Inspect the agenda with `agenda`, then explicitly resume an
item using `retry <agenda-id>`.

The integration suite uses a temporary SQLite database and can be run with:

```sh
python -m unittest discover -s tests -p 'test_*.py'
```

This is an initial, safe execution slice—not a general autonomous agent. Model
providers, research, arbitrary tools, and broader evaluation capabilities are
not implemented.
