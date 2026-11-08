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
