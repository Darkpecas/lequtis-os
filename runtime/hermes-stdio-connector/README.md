# Hermes stdio connector (G01)

**Status:** integration candidate — recovered/reconstructed locally from the
LIVE LOOP ledger contract. **Not deployed. Not a Hostinger live proof.**

## Tools

| Tool | Default | Notes |
| --- | --- | --- |
| `lequtis_status` | on | Read-only kernel status |
| `lequtis_verify_events` | on | Hash chain `previous\|ts\|type\|payload` |
| `hermes_probe` | on | Local binary probe only |
| `hermes_query` | **off** | Requires `LEQUTIS_HERMES_QUERY=1` |

`hermes_query` never writes LeQutis intent, events, evaluation, memory, or agenda.

## Optional canonical intake write gate

**Intake only — held for approval, not an execution queue.** Both agenda and
task rows persist as `awaiting_approval`. Neither existing `run_loop` nor
`run_once`/daemon selects these rows. No approval/promotion tool is exposed.
Use `lequtis_canonical_read` to recover held submissions; existing `unfinished`
and open-agenda counters do not include this status. A future approved dispatcher
needs explicit action-specific acceptance and compatibility checks before it may
release a submission. Do not change the status to `open`/`pending` as a shortcut:
the existing `run_loop` treats successful `inspect_status` as enough to close its
linked agenda, while `run_once` supports a different `remember` execution path.
The intake gate deliberately grants neither execution mode approval.

`lequtis_canonical_write` and `lequtis_canonical_read` are absent by default.
The trusted stdio host must set both `LEQUTIS_CANONICAL_WRITE=1` and a validated
`LEQUTIS_WRITE_PRINCIPAL` before starting the adapter. This principal is the
host-authenticated caller binding, not a request parameter. Only bind one
principal per stdio process; do not expose the process to untrusted clients.
No web/HTTP authentication, transport, host deployment or live route is added.

The write gate opens only the existing kernel database selected by `LEQUTIS_DB`
or `$LEQUTIS_STATE/lequtis.db`, using SQLite `mode=rw`. It refuses missing,
symlinked, non-WAL or incompatible database paths and never initializes or
migrates one. The symlink check is performed before opening; concurrent path
replacement is not covered by this guard.
It validates fields and the existing event chain, then uses one
`BEGIN IMMEDIATE` transaction to persist:

- one agenda row and one allowlisted task intent, both `awaiting_approval`;
- one memory row marked `submitted_<kind>`, never trusted semantic promotion;
- one `canonical.intake` hash-chained event containing the receipt claim,
  request digest, principal and row IDs.

The entire intake commits or rolls back. Principal-scoped idempotency keys
replay unchanged requests without duplication and refuse altered requests.
A new connection reads the committed rows and checks stored bindings before
returning. `lequtis_canonical_read` offers a separate read-back invocation.
Stored receipts remain `unverified_claim`: hashing establishes content
integrity, not truth, producer authentication or successful execution.
The gate does not execute work, mark it done, or enable Hermes queries.

Example write-tool arguments (JSON, maximum 64 KiB):

```json
{
  "idempotency_key": "ios-observation-001",
  "title": "Inspect current kernel status",
  "action": "inspect_status",
  "payload": {},
  "receipt": {"source": "iphone", "observation": "Operator requested inspection"},
  "memory": {"kind": "episodic", "content": "Submitted inspection request"}
}
```

Read-tool arguments: `{"idempotency_key":"ios-observation-001"}`.
Actions: `inspect_status`, `store_note`, `ping`, `deliberate_fail`.
Memory kinds accepted: `semantic`, `episodic`, `working`; all persist with a
`submitted_` prefix. Unknown request fields, caller principals, SQL and paths
are not accepted. Sensitive values intentionally submitted in payloads are
persisted; callers must not include credentials in receipts or notes.

Disposable acceptance:

```sh
python3 tests/test_canonical_write.py
python3 tests/test_bridge.py
```

Local proof only. A live host check requires the authorized existing bridge,
an explicit host write capability and independent read-back on that host.

## MCP protocol compatibility (2026-11-08 audit)

This reconstructed stdio adapter implements the **legacy 2024-11-05** MCP
initialize handshake only. It MUST NOT claim July 2026 compatibility just
because a client requests version `2026-07-28`. During legacy
`initialize`, it responds with its actually supported version
(`2024-11-05`) so clients can disconnect or negotiate appropriately.

The new July 2026 **modern** protocol instead uses per-request `_meta`
and `server/discover` with no initialization handshake. This adapter
does **not** implement that modern contract; `server/discover` returns
method not found rather than a fabricated success. No modern MCP Tasks,
MCP Apps, HTTP listener, or live tunnel is claimed.

Before any modern implementation, inspect the real Hostinger/Hermes
client capabilities, preserve legacy compatibility, test transport framing
and authorization on disposable state, and then independently verify a
live read-only round trip. No deployment is implied by this documentation.

Official references:
- https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning
- https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle

## Preflight exit codes

| Code | Meaning |
| --- | --- |
| 0 | Stdio OK + host prerequisites present |
| 2 | Stdio failure |
| 3 | Stdio OK, host prerequisites absent |

```sh
python3 runtime/hermes-stdio-connector/host_preflight.py --json
python3 tests/test_bridge.py
python3 tests/test_host_preflight.py
```

## Provenance

Private System Access Manager plugin paths cited in evidence:

- `runtime/hermes-stdio-connector/lequtis_mcp_stdio.py`
- `runtime/hermes-stdio-connector/host_preflight.py`
- releases through v1.2.22 / `pluginrel_6aeff36a6184819184515cdc43099529`

Exact private package bytes were **not** available to the recovering cloud
agent session. This tree is a **contract-faithful reconstruction** for
disposable verification (G01 → `VERIFIED_DISPOSABLE`). Live gates G02+ stay OPEN.
