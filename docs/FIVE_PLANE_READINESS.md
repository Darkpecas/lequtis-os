# Five-plane readiness

Date: 2026-11-10
Audited tree: `main` at `425a2f32f3ddf762f6371e8508f8a78e290d4663`, plus the files this branch adds.
Evidence label for every executable check below: **LOCAL PROOF, NOT LIVE VPS VERIFIED**.
No canonical database was created or opened. No Hostinger, VPS, or live Hermes call was made.

VERIFIED means a file or a command run here showed it. UNVERIFIED means a public request did not confirm it (the unsuffixed Muse Spark id and `LiquidAI/d1-ultra` on Hugging Face returned HTTP 401). NOT FOUND means no file or public page showed it. FAILED is used for the tampered hash chain. INFERRED and BLOCKED were not needed.

## Readiness table

| Plane / rule | Implementing files | Evidence label | Gap |
| --- | --- | --- | --- |
| P0 hash-chained SQLite WAL ledger (`previous_hash`, `event_hash`) | `database/schema.sql`; `core/lequtis.py` (`event`, `verify_event_chain`, `PRAGMA journal_mode=WAL`); `evidence/readiness-2026-11-10/` | VERIFIED | The column is `previous_hash`, not `prev_hash`. Schema has no trigger that rejects UPDATE or DELETE. Disposable proof: `journal_mode=wal`, sidecar present after init, chain `ok: true` (20 events), then one payload update made `verify` return `ok: false`, `event_hash_mismatch` at seq 1. `verify` still exited 0. `verify-events` exited 1 with `valid: false`. |
| P1 immutable golden-master seal | `core/golden_master.py`; `GOLDEN_MASTER.json`; `tests/test_golden_master.py` | VERIFIED | Absent on the audited `main` commit before this branch. The seal is a SHA-256 manifest of git-tracked `core/` and `database/schema.sql` (10 files, `manifest_sha256` `21e2bfed433fea0d52e0b6d484b3f007cf53ce4025c3f651bbb78d1120d31717`). It refuses to overwrite an existing seal and verifies a clone path. It does not itself launch an experiment. |
| P2 local memory storage | `database/schema.sql` `memory`; `core/lequtis.py` `remember` | VERIFIED | Rows are local SQLite. There is no mesh, activation score, or decay field. |
| P2 bounded activation decay | none | NOT FOUND | Repository search found no activation or decay implementation. `docs/LIQUID_NEUROLOGY_DESIGN_CONTEXT.md` does not specify one. |
| P3 core plus an 8-swarm Adaptive Research Hive | `core/workers.py`; `docs/LIQUID_NEUROLOGY_DESIGN_CONTEXT.md` | NOT FOUND | `workers.py` is one replaceable THINK/CHOOSE slot with a deterministic fallback. The design note says specialized swarms are optional. No file names an 8-swarm hive or adds one beside the core. |
| P4 Sentinel Prime | none | NOT FOUND | The name does not appear in the repository. |
| P4 S5 adversarial verification gates | `core/verifier_main.py`; `core/verifier.py`; `tests/test_verifier.py` | NOT FOUND | An independent verifier rejects a worker self-report, a bad hash, and an artifact symlink. Nothing names that control S5. |
| P4 failed-hypothesis registry | `knowledge/FAILED_HYPOTHESES.jsonl`; `core/failed_hypotheses.py`; `tests/test_failed_hypotheses.py` | NOT FOUND | `F-YOURA-001` and `F-ARBOR-001` do not appear in the repo or docs. The new registry is empty. Their contents were not invented. The loader refuses edits, deletions, and a shortened tip. |
| P4 least-privilege connectors | `runtime/hermes-stdio-connector/lequtis_mcp_stdio.py`; `runtime/hermes-stdio-connector/host_preflight.py`; `knowledge/ACCESS_MATRIX.yaml`; `knowledge/ACCESS_MANIFEST.yaml` | VERIFIED | Default tools are read-only. `hermes_query` stays off unless `LEQUTIS_HERMES_QUERY=1`. `ACCESS_MATRIX.yaml` records `hermes_hostinger` as unknown. No live route was opened. Bridge Manager is not a named component. |
| Routing tier 0, d1-ultra decision gate | `knowledge/ROUTING_CONTRACT.json`; `core/routing_contract.py`; `tests/test_routing_contract.py` | VERIFIED | Vendor pages document the hosted model: https://www.liquid.ai/blog/d1-ultra and https://docs.liquid.ai/lfm/models/d1 . `https://huggingface.co/api/models/LiquidAI/d1-ultra` returned HTTP 401, so a public weight repo is UNVERIFIED. The contract does not require local weights. This repo does not call the model. |
| Routing tier 1, LFM3-1.7B edge | same contract files | VERIFIED | https://huggingface.co/LiquidAI/LFM3-1.7B states a 256K context. The card's evaluation note says 262144 tokens. No runtime call exists here. |
| Routing tier 1, LFM2.5-2.6B edge | same contract files | VERIFIED | https://huggingface.co/LiquidAI/LFM2.5-2.6B states context length 131072, not 256K. https://docs.liquid.ai/lfm/help/deprecations lists it as deprecated in favor of LFM3-1.7B. The contract records both facts. No runtime call exists here. |
| Routing tier 2, Muse-Glimmer-30B agentic executor | same contract files | VERIFIED | https://huggingface.co/meta-models/Muse-Glimmer-30B . The card states context 131072+. No runtime call exists here. |
| Routing tier 3, Muse-Spark-Open-816B | none under that exact id | UNVERIFIED | `https://huggingface.co/meta-models/Muse-Spark-Open-816B` and the matching API URL returned HTTP 401. That is not a public model card and not a 404, so it is not recorded as absent. The contract does not name this id. |
| Routing tier 3, published Muse Spark Open checkpoint | same contract files, model `meta-models/Muse-Spark-Open-816B-A42B` | VERIFIED | https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B and https://huggingface.co/api/models/meta-models/Muse-Spark-Open-816B-A42B . API fields observed: `private: false`, `gated: manual`, safetensors total `822036529664`. The contract names this id only. No runtime call exists here. |
| ARS-V1 blind first pass | none under that name | NOT FOUND | `core/verifier_main.py` does not read `claimed_verdict`. The repository does not name a blind first pass or ARS-V1. |
| ARS-V1 append-only failure memory | `knowledge/FAILED_HYPOTHESES.jsonl` (empty); event rows in `core/lequtis.py` | NOT FOUND | Failed tasks append events. That is not a named ARS-V1 failure memory. The new registry has no seeded failures. |
| ARS-V1 claim provenance via source hashes | `database/schema.sql` `knowledge_items.content_hash`; `core/verifier_main.py` artifact SHA-256 | VERIFIED | Hashes are stored for knowledge items and execution artifacts. |
| ARS-V1 DEER binary rubric | none | NOT FOUND | No file names DEER or a binary rubric grader. The routing contract does not add one. |
| ARS-V1 idempotency and concurrency | `core/lequtis.py` `record_goal` (`BEGIN IMMEDIATE`, unique `idempotency_key`); `database/schema.sql`; `tests/test_idempotency.py`; `evidence/readiness-2026-11-10/` | VERIFIED | Disposable replay of key `readiness-2026-11-10` kept 1 agenda row, 1 succeeded execution, and 20 events, and the second `run-once` was `idle`. `test_idempotency.py`: 4 tests, OK, exit 0. |

## Ledger receipts

Directory: `evidence/readiness-2026-11-10/`. Every file carries `LOCAL PROOF, NOT LIVE VPS VERIFIED`.

The database lived in a temporary directory under `/tmp` and was deleted with it. `core/lequtis.py` bytes matched `HEAD` (`kernel_sha256` `fdbdc8b9c1b5446b5b94dce43eab0898cf2df47a03e1a299de14fd2ea9eab95c`). Before and after, the only file under `database/` was `schema.sql`. `state/` had no database file.

| Step | Result |
| --- | --- |
| `init` | exit 0 |
| `PRAGMA journal_mode` | `wal`; `-wal` sidecar existed after init |
| `goal --key readiness-2026-11-10 "remember: disposable readiness ledger fact"` | exit 0, `AGENDA ITEM CREATED` |
| `run-once` | `status: succeeded`; verifier `accepted`; `worker_self_report_consulted: false` |
| `verify` before tamper | `ok: true`, `count: 20` |
| replay same key and title | exit 0, `AGENDA ITEM EXISTS` |
| second `run-once` | `status: idle` |
| counts after replay | agenda 1, executions succeeded 1, events 20 |
| tamper seq 1 payload to `tampered` | row changed |
| `verify` after tamper | FAILED: `ok: false`, `broken_at: 1`, `reason: event_hash_mismatch`. Process exit stayed 0 |
| `verify-events` after tamper | FAILED: `valid: false`, `invalid_sequence: 1`, process exit 1 |

## Acceptance gauntlet

Run on 2026-11-10 from this work tree. Direct `python3` on every `tests/*.py`, then `tests/smoke.sh`, `doctor.sh`, and `python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v`.

Script checks (a line ending in `PASS`, excluding the final banner). Failures: 0.

| File | PASS lines | Exit |
| --- | --- | --- |
| `tests/autonomous_loop_test.py` | 7 | 0 |
| `tests/test_bridge.py` | 6 | 0 |
| `tests/test_hermes_route.py` | 4 | 0 |
| `tests/test_host_preflight.py` | 4 | 0 |
| `tests/test_skills_verifier_parity.py` | 6 | 0 |
| `tests/test_workers.py` | 5 | 0 |

Unittest modules (`Ran N tests` and a final `OK`). Failures: 0.

| File | Tests | Exit |
| --- | --- | --- |
| `tests/test_execution.py` | 5 | 0 |
| `tests/test_failed_hypotheses.py` | 2 | 0 |
| `tests/test_fence.py` | 1 | 0 |
| `tests/test_golden_master.py` | 4 | 0 |
| `tests/test_host_receipt.py` | 2 | 0 |
| `tests/test_idempotency.py` | 4 | 0 |
| `tests/test_routing_contract.py` | 2 | 0 |
| `tests/test_schema_guard.py` | 3 | 0 |
| `tests/test_verifier.py` | 3 | 0 |

Direct total: 32 script PASS lines and 26 unittest cases, 0 failures.

`unittest discover`: 26 `ok`, 0 `FAIL`, 0 `ERROR`, summary `Ran 26 tests` / `OK`, exit 0. Those 26 are the unittest modules above. The script modules do not add `TestCase` classes, so discover does not repeat their PASS lines.

`tests/smoke.sh`: exit 0, banner `LEQUTIS SMOKE TEST: PASS`.
`doctor.sh`: exit 0, banner `PASS: LeQutis kernel executable + autonomous loop verified.` It re-ran the autonomous-loop script (7 PASS lines) and the skills script (6 PASS lines).

## Open pull requests

Read on 2026-11-10 with `gh pr view`. GitHub reported each of #17, #19, #21, #22, and #25 as `OPEN` and `MERGEABLE`. That flag is a git merge check. None of these PRs were changed or merged. Current `main` already contains kernel-3 (`40de0c9`, schema guard, idempotency keys, independent verifier, fenced recovery).

| PR | What it adds | Overlap | Relation to this `main` | Recommendation |
| --- | --- | --- | --- | --- |
| [#17](https://github.com/Darkpecas/lequtis-os/pull/17) | Opt-in canonical write in `runtime/hermes-stdio-connector/canonical_write.py`, plus `verified_completion.py` and stdio tools. Draft. | Same write-gate concern as #19 and #25. All three edit `lequtis_mcp_stdio.py`. #17 and #19 both add `runtime/hermes-stdio-connector/canonical_write.py` and `tests/test_canonical_write.py`. | Git-mergeable. The writer does not check `schema_revision`, `journal_mode`, or a database symlink (those strings are absent from that file). It writes tasks, events, and memory beside `run_once`. | Do not merge together with #19 or #25. |
| [#19](https://github.com/Darkpecas/lequtis-os/pull/19) | Smaller opt-in writer at the same runtime path. Rejects a symlink at `$LEQUTIS_STATE/lequtis.db`. Inserts action `record_observation` and status `recorded_unverified`. | Overlaps #17 and #25. | Git-mergeable. It does not consult `REQUIRED_COLUMNS` or `schema_revision`. `record_observation` is outside `ACTIONS`. A different `LEQUTIS_DB` path is not the path it checks. | Close if #25 is kept. |
| [#22](https://github.com/Darkpecas/lequtis-os/pull/22) | Symlink rejection on #17's writer, with a regression test. | Stacked on #17. Base branch is `feature/sovereign-canonical-write-gate`, not `main`. | The symlink check applies only after #17. #25 already rejects `L.DB.is_symlink()` before open. Main already rejects artifact symlinks in `core/verifier_main.py` and `O_NOFOLLOW` writes in `core/lequtis.py`; it does not reject a symlinked database on the stdio write path, because that path is not on `main`. | Merge only after #17, and only if #17 is the chosen writer. Close it if #17 is closed. |
| [#25](https://github.com/Darkpecas/lequtis-os/pull/25) | `core/canonical_write.py`: intake stays `awaiting_approval`, opens `mode=rw` so it will not create a database, requires WAL, `REQUIRED_COLUMNS`, and `schema_revision == L.SCHEMA_REVISION`, and rejects a symlinked `L.DB`. | Overlaps #17, #19, and the symlink goal of #22, at a different module path. Still edits the stdio adapter, so it will not combine cleanly with #17 or #19. | Git-mergeable onto current kernel-3, and it calls the kernel's own column set and revision. This is the write gate that matches `main` as it is now. | Keep this one if a canonical WAL intake is merged. Land it alone. |
| [#21](https://github.com/Darkpecas/lequtis-os/pull/21) | Disposable CI workflow, `integrations/hermes_receipt_gate.py`, and `tests/test_hermes_receipt_contract.py`. | No shared paths with #17, #19, #22, #25, or current `main`. | Git-mergeable. It does not add a write path. Its own text says a passing run is not Hermes or Hostinger proof. | Review on its own, in either order relative to #25. Do not treat it as closing the live loop. |

Recommended order: review #25 and merge it alone if the intake is accepted; close #17, #19, and #22 as overlapping writers (re-propose `verified_completion.py` later only as its own review); review #21 separately. This branch does not depend on those merges.
