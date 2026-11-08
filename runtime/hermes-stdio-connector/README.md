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
