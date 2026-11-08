# Secure MCP tunnel runbook (evidence-only)

**Not executed in this session.** No tunnel ID, runtime API key, or ChatGPT
connector registration is fabricated or stored here.

## Purpose

Document the *authorized* path once an operator has:

1. Hostinger/Hermes principal verified
2. Official OpenAI Secure MCP Tunnel provisioned (outbound-only)
3. This stdio adapter running against a real host DB (not disposable)

## Operator steps (manual)

1. On Hostinger VPS, confirm:
   - `python3 core/lequtis.py status`
   - `python3 runtime/hermes-stdio-connector/host_preflight.py --json` → exit 0
   - `hermes --version` (or host-specific `--help`)
2. Keep `LEQUTIS_HERMES_QUERY` **unset** until scope is approved.
3. Configure official `tunnel-client` with the account's existing tunnel ID
   and runtime API key **on the host** (never paste secrets into chat).
4. Point the tunnel at:
   `python3 runtime/hermes-stdio-connector/lequtis_mcp_stdio.py`
5. From ChatGPT, call read-only `lequtis_status` / `hermes_probe` and archive
   the raw receipt into LeQutis evidence (G03).

## References (public docs)

- https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- https://github.com/openai/tunnel-client/blob/master/docs/onboarding.md

## Hard rules

- No public anonymous listener
- No secrets in git or chat
- Adapter success ≠ sovereign live loop (still need canonical write/read-back,
  replay, fresh-session continuity — gates G04+)
