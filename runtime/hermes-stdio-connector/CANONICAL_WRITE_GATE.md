# Canonical write gate (candidate, not deployed)

## Scope
The local stdio adapter now supports `lequtis_commit_record` on explicit opt-in. It writes a task row (intent), a caller-provided receipt (unverified observation), optional memory, and a hash-chained event **in one SQLite transaction** against an existing `LEQUTIS_STATE/lequtis.db`. No schema migration or new server is introduced.

## Security boundary
Both `LEQUTIS_CANONICAL_WRITE=1` and `LEQUTIS_TRUSTED_LOCAL_TRANSPORT=1` must be set **by an authorized host administrator**. These flags are *not* authentication; the adapter inherits the host process's access. Do not enable on an exposed, unauthenticated MCP endpoint. Authenticate callers before stdio dispatch; constrain OS permissions to the canonical DB; review real Hostinger/A71 schema compatibility and back up the DB before any production deployment. Avoid passing secrets through receipts or memory.

Default: **disabled**. With writes disabled, existing read tools remain usable. For disposable verification only, use `python3 tests/test_canonical_write.py`.

## RPC
`tools/call` `lequtis_commit_record` with:
```json
{"key":"unique:task:001","title":"Verify harmless task","receipt":{"source":"local-test","observation":"sample"},"memory":"Optional test observation","memory_kind":"observation"}
```
`key` must be stable, 8–128 characters [A-Za-z0-9._:-]. Repeated identical requests return `replay:true`, conflicting requests return `idempotency_conflict`. No arbitrary SQL, shell command, or external tool execution is performed.

## Nonclaims and additional gates
- A caller-provided receipt is **not independent evidence**. `verified:false` and `live_host:false` remain explicit.
- This operation does not execute the Hermes task or prove a Live Loop.
- The independent verifier must read back task, event, memory and hash chain and cross-check independently observed Hermes receipt against correlation IDs before accepting execution.
- Live secure transport, authorized Hostinger read/write, end-to-end loop, fresh-session replay and Doc/TBQ sign-off remain OPEN until tested.
- Do not merge or deploy before a real test run verifies compatibility, concurrency, failed-transaction rollback, and authentication provenance.
