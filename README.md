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

This bootstrap establishes the persistence foundation only.
