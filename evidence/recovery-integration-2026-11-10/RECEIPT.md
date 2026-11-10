# Integrated recovery acceptance

10 November 2026. LOCAL DISPOSABLE PROOF; NOT LIVE VPS VERIFIED.

Inputs: main ffa77ea1a74e9cba1c1791b4111c772f2a4b8d25,
PR #29 head 7fe2821fb9eea6587b04d921df781adfb9272b3a,
and recovery fix published as feb369cedd8ad4cdd767c48d41e7024d7f9aec60.
All three are combined; main's existing Hermes receipt gate and workflow are preserved.

`python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v`
passed 47 tests. Raw output: tests.log. Golden master verification passed with
manifest 2284247cfb7d8da7429d1d63bca3a3161e7348e7ad39bc18a94721c6e09a9aa8.
The prior standalone script evidence is retained under recovery-after-act-2026-11-10.

The added/newer local-model provider was inspected as source and exercised by
the tests; no live local model endpoint was configured or invoked in this session.
A synthetic provider harness is not evidence of LLM quality or live deployment.

Host route discovery: no callable Hostinger/Hermes tools were exposed. CLI
`codex mcp get hostinger` returned no configured server. No route variable names
containing HERMES/HOSTINGER/TUNNEL/SSH/TAILSCALE were configured. Plugin discovery
returned Hostinger Mail only, which cannot deploy this runtime. The cloud browser
had no pre-existing tabs and Hostinger guidance explicitly restricts sign-in
from that browser; no sign-in was attempted. Desktop Commander and Vercel were
excluded as directed. Canonical production SQL was not accessed.

Both access registry files retain historical evidence and add a scoped
current-session continuation. Live deployment and real Hermes request/result
read-back remain blocked by missing authenticated host execution capability.
No production database, service, migration or remote permissions were changed.

Next automatic operation once the existing route is callable: read host
identity, checkout/commit and canonical DB schema without mutation; capture a
consistent SQLite backup including committed WAL; prepare an isolated candidate
release; run host tests on disposable state; perform an explicit compatible
migration only with rollback ready; switch the intended service; correlate a
safe Hermes request with independent durable read-back and replay test. Actual
paths, service name and host configuration must come from that read-only probe.

## CI correction

Initial PR #32 CI runs 42911593778 and 42911593891 failed the parity check:
`matrix_principal_unknown: codex_work_mode`. The first registry continuation
used nested YAML not supported by the stdlib fallback parser in core/access_parity.py.
The records were flattened to the existing principals/routes/matrix schema,
without weakening the checker. Historical principal observations remain intact.
This is a correction to the newly added access records, not a recovery-kernel failure.
