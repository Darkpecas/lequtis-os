# LeQutisOS

Canonical GitHub home: **https://github.com/Darkpecas/lequtis-os**

LeQutis is a proactive, autonomous, self-improving AI partner.

LeQutis owns identity, memory, agenda, skills, evidence and evolutionary history.
Models and tools are replaceable workers — never senior to LeQutis.

## Where the body of work lives

External stores are evidence feeds, not senior authority:

| Store | Role |
| --- | --- |
| **GitHub `Darkpecas/lequtis-os`** | Canonical runtime / kernel home |
| Google Docs / Google Drive | Main durable prose + attachments |
| iCloud | Mobile chats / backups / Files |
| ChatGPT / Gemini | Conversation corpora (workers) |
| NotebookLM | Grounded research notebooks |
| Obsidian + personal graph SOPs | SOPs and personal knowledge graph |

```sh
python3 core/lequtis.py sources list
python3 core/lequtis.py assimilate          # docs/evidence
python3 core/lequtis.py ingest              # knowledge/inbox/<source_id>/
python3 core/lequtis.py gates               # LIVE LOOP gate ledger
python3 core/lequtis.py seed-gates          # open/partial gates → agenda
```

Google Drive is often connected in Desktop Cursor but **not** in a given cloud
agent run. If Drive MCP shows `needsAuth`, drop Doc exports into
`knowledge/inbox/google_docs/` instead of re-prompting auth.

## Architecture

- `core/` — living kernel + autonomous loop
- `knowledge/` — source registry (`SOURCES.yaml` / `SOURCES.json`)
- `database/` — persistent state schema
- `tests/` — disposable integration evidence
- `docs/evidence/` — assimilated export pack
- `state/` — runtime SQLite WAL DB (gitignored)
- `logs/` — runtime logs (gitignored)

## Autonomous loop

```
NOTICE → THINK → CHOOSE → ACT → OBSERVE → EVALUATE → LEARN → REMEMBER → UPDATE AGENDA
```

Every phase emits a hash-chained audit event.

## Quick start

```sh
python3 core/lequtis.py init
python3 core/lequtis.py goal "Inspect kernel status via autonomous loop"
python3 core/lequtis.py loop
python3 core/lequtis.py verify
python3 core/lequtis.py verify-independent
python3 core/lequtis.py parity
python3 core/lequtis.py skills propose "example-skill"
python3 core/lequtis.py search "LeQutis"
python3 tests/autonomous_loop_test.py
python3 tests/test_skills_verifier_parity.py
./doctor.sh
```

`doctor.sh` and `tests/smoke.sh` use disposable state and do not touch an
existing LeQutis database. Use the read-only Hermes host preflight when checking
an existing installation.

Host vs phone roles: see repo-root `COMPUTER_REQUIREMENTS.md`.

Disposable tests never touch production state. Set `LEQUTIS_STATE` to point at a temp directory.

## Cognitive workers (THINK / CHOOSE)

Replaceable workers rank and propose; **ACT stays the safe registry**.

```sh
# default
LEQUTIS_WORKER=deterministic python3 core/lequtis.py loop

# external JSON script worker
LEQUTIS_WORKER=script LEQUTIS_WORKER_SCRIPT=/path/to/worker.py python3 core/lequtis.py loop

# OpenAI-compatible HTTP worker (optional)
LEQUTIS_WORKER_MAX_REQUESTS_PER_DAY=0 LEQUTIS_WORKER=openai LEQUTIS_WORKER_URL=https://api.openai.com/v1/chat/completions \
  LEQUTIS_WORKER_MODEL=gpt-4o-mini LEQUTIS_WORKER_API_KEY=... python3 core/lequtis.py loop
```

Unsafe proposals are rejected and fall back to deterministic policy.

Hosted HTTP calls are blocked unless `LEQUTIS_WORKER_MAX_REQUESTS_PER_DAY` is
set explicitly. Its default is `0`; the hard maximum is 20 requests per UTC
day. Output is capped at 512 tokens and input at 32,768 characters per request.
`credits` reports reservations and provider-reported token usage from the
existing hash-chained LeQutis event ledger. It cannot report currency charges;
check the provider billing dashboard for that. Failed requests still consume
their reservation. A custom `script` worker can make its own network calls and
is outside this HTTP request budget.

```sh
python3 core/lequtis.py credits
```

## Kernel hardening (lequtis-os-kernel-4)

LOCAL PROOF, NOT LIVE VPS VERIFIED.

`GOLDEN_MASTER.json` remains the original immutable kernel snapshot;
`GOLDEN_MASTER_v2.json` seals the current versioned kernel files. The seal is a
SHA-256 manifest for drift detection, not a signature or a tamper-proof ledger.

These controls sit on the current kernel. Existing commands, `LEQUTIS_STATE`, and `LEQUTIS_ROOT` still work. `LEQUTIS_DB` selects the database file when it is set; otherwise the file remains `$LEQUTIS_STATE/lequtis.db`.

- An existing database whose columns or `identity.schema_revision` are not `lequtis-os-kernel-4` fails closed. `status` and `init` exit 3 with `schema guard` and do not write.
- A `lequtis-os-kernel-3` database stays at that revision until `python3 core/lequtis.py migrate`. Migrate is explicit, idempotent when already current, and refused for any other shape. The migration and its `schema.migrated` event commit together.
- `goal --key <key> <title>` replays the same title as one agenda row. The same key with a different title is a conflict.
- `cancel --key <key> agenda <id>` or `cancel --key <key> execution <id>` records one hash-chained cancellation. The same key and request replays. A later result commit for a cancelled execution is rejected.
- `run-once` writes one allowlisted artifact and asks `core/verifier_main.py`, a separate process, to check its path, hash, and correlation id. The verifier does not read the worker self-report. A rejected verdict leaves the agenda incomplete.
- `recover` does not take a lease whose process is still alive. After that process is killed, `complete` with the old lease token cannot finish the agenda.
- `verify` exits 1 when the event chain is invalid. `verify-events` still exits 1 in that case.

`run.sh` calls `python core/lequtis.py daemon 900`. `daemon` repeats `run-once`.

## Safe actions

Registered actions only: `inspect_status`, `store_note`, `ping`, `deliberate_fail`.
No arbitrary destructive system execution.

## Brahma Evo

Brahma Evo is a research candidate only. Its licence forbids importing its source into LeQutis. Patterns may be independently reimplemented under LeQutis governance — never as a rival sovereign brain.
