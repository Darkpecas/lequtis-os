# LeQutis Sovereign Live Loop — Dedicated Completion Strategy

**Date:** 2026-11-08  
**Owner/sovereign authority:** LeQutis  
**Execution environment:** EXISTING Hostinger Hermes (do not provision a new VPS)  
**Primary control surface:** iPhone → existing authorized gateway / Telegram when verified  
**Release gate:** [Issue #20](https://github.com/Darkpecas/lequtis-os/issues/20)  
**Status:** STRATEGY STAGED, LIVE ACCEPTANCE NOT VERIFIED. No production change or host invocation is implied.

## 0. Purpose: one complete system, not many disconnected projects

Demonstrate: **NOTICE → THINK → CHOOSE → ACT → OBSERVE → EVALUATE → LEARN → REMEMBER → UPDATE AGENDA**, backed by one auditable canonical state and a real Hermes-mediated action. Persist authorized intent before dispatch. Capture an observation without confusing it for proof. Independently validate the effect before marking the task complete or committing learned conclusions. Resume from persistent state after interruption.

### Source-of-truth precedence
1. Directly observed live host and canonical DB, tied to a revision and timestamp.
2. Exact checked-out repository source and independently rerun tests.
3. CI outcomes on pinned commit (DISPOSABLE scope only).
4. Existing documentation, artifacts and historical reports.
5. Hypotheses, simulation and memory.

Repository snapshot at strategy authoring: `main=e86aad3e9cd27965a285852da0c3162ce8978e2d`. MUST re-pin before test or deployment. No static assertion about present Hostinger state.

## 1. Existing assets and their limits

- `core/lequtis.py`: sovereign kernel with task, memory, agenda, event ledger and loop primitives; existing SQLite WAL, event-chain verification.
- `runtime/hermes-stdio-connector/lequtis_mcp_stdio.py`: read-only commands plus opt-in Hermes query on `main`; legacy MCP version boundary. A file in repo is not evidence it is installed on host.
- `runtime/hermes-stdio-connector/host_preflight.py`: local, read-only handshake/core/DB/Hermes presence probe; explicitly `live_host=False`.
- `runtime/hermes-stdio-connector/host_receipt.py`: local read-only receipt; not a remote execution attestation.
- PR #17: canonical write candidate including intent/receipt, atomic WAL transactions, event-chain validation, replay rejection, disabled-by-default, adversarial tests. **Preferred review baseline, not pre-approved merge.**
- PR #19: distinct competing writer contract; compare safeguards, do not merge both or create a third writer.
- PR #18: policy candidate; not complete authenticated multi-tool enforcement.
- PR #16: staged research packets, NOT dispatched work.
- Brahma Evo independent skill admission: historical disposable tests only; external source/licensing restriction must be respected.
- CfC, Mamba, STAR, HAC: research experiments only, not prerequisites to the first live loop.

## 2. Explicit boundary and authority model

LeQutis retains sovereign authority. Oracle advises; TBQ explores and proposes; Doc recovers dropped work, enforces evidence continuity; Hermes orchestrates; Builder Swarm executes bounded delegated actions; Verifier/Auditor independently attests. A persona title or a receipt field does NOT authenticate a real principal or imply that these roles actually ran.

Trust boundary A: iPhone/Telegram or any caller → authenticated gateway. Verify which identity actually initiated the request and bind it to a delegated task, scope, expiry and nonce. Never treat an environment variable alone as authentication.

Trust boundary B: authorized gateway → local stdio MCP process. Confirm ownership, protocol version negotiation, process identity, launch command and least-privilege filesystem access. Reject unauthenticated remote MCP exposure. Keep writer disabled until gates pass.

Trust boundary C: LeQutis intent → Hermes action. Authorize an allowlisted harmless action, with monotonic task state and a durable outbox/dispatch identifier. Never assume exactly-once remote side effects from SQLite idempotency alone.

Trust boundary D: Hermes observation → independent verification. A return code, text response or worker-generated receipt alone is not verified external success. Collect independent observation where feasible, tie it to the actual action, and record limitations.

Trust boundary E: verifier → canonical memory/agenda. Only evidence-supported evaluation changes verified outcome and durable learning. Unknown/failed/ambiguous remain explicit.

## 3. Canonical record and transitions

Each operation must have:
- `correlation_id` (entire sovereign cycle), `task_id`, `idempotency_key`, `attempt_id`, `action_id`.
- `actor_principal`, `delegation_scope`, `policy_revision`, `repo_commit`, `host_instance` (prefer stable pseudonymous identifier, no secrets).
- `intent_hash`, `receipt_hash`, `verification_hash`, `event_seq`, `event_hash`, UTC timestamps and clearly identified clock/source.
- `verification_level`: `unverified`, `local_disposable`, `ci_disposable`, `host_observed`, `independently_verified_live`.
- `status`: proposed, authorized, persisted_pending, dispatched, outcome_unknown, observed_unverified, evaluated, verified, rejected, failed, interrupted, recovered, closed.

**State invariant:** no transition to `verified` from executor-provided success alone. No `learned_fact` memory from `observed_unverified`. No automatic re-dispatch of `outcome_unknown` for non-idempotent effects.

Recommended transactional sequence (apply to existing kernel schema without destructive migration):
1. Validate identity, authorization, policy, payload size and idempotency.
2. `BEGIN IMMEDIATE`: check prior event chain; insert pending intent and hash-chained event; commit.
3. Dispatch with the same correlation/key; store dispatch attempt evidence. Treat crash-after-dispatch as ambiguous.
4. Capture receipt as unverified observation, with its origin and digest.
5. Independent verifier reads the same DB + independently observed result; evaluates, signs/binds verifier identity via an approved mechanism.
6. Atomically record verdict, learned memory (only when supported), agenda update and event evidence. Do not overclaim atomicity across SQLite and external systems.
7. Fresh-process or fresh-session readback: inspect task, event chain, memory, agenda and last known action, reconcile with external system before any retry.

## 4. Completion critical path (strict gates)

### G0 — Pin, reconcile, freeze
- Pin exact HEAD of main and #17, #19, #18.
- Diff #17 versus #19: schemas, event hash contract, receipt interpretation, access checks, exceptions, rollback and replay behavior.
- Adopt one writer interface only; preserve the other as a documented rejected/superseded alternative.
- Verify CI on the exact prospective integration commit; no production merge solely because disposable tests pass.
**Exit:** versioned comparison, chosen implementation, associated SHA, green deterministic tests, open risks documented.

### G1 — Read-only existing host discovery
Authorized operator on EXISTING VPS only; do not enable writes:
- Confirm current Hostinger connection method, process owner/UID, path, running Hermes version and executable, service management, installed MCP connector/version and protocol negotiation.
- Inventory real canonical DB path, permissions, schema, WAL checkpoint state, event chain integrity and backup/restore procedures.
- Run existing `host_receipt.py` and `host_preflight.py --json` only in intended, authorized checkout, sanitizing paths and secrets. These alone do NOT prove live loop.
**Exit:** authenticated host-bound observation, exact source/protocol versions, and independent read-only DB evidence.
**Stop:** missing identity, mismatched DB, corrupt chain, exposed endpoint, or unknown owner.

### G2 — Harden and approve the adapter
- Authentication upstream of stdio must be demonstrated, not asserted by booleans such as `LEQUTIS_TRUSTED_LOCAL_TRANSPORT`.
- Restrict allowlisted action, scope, resource access; bind identity and key to intent.
- Keep `LEQUTIS_CANONICAL_WRITE` disabled by default; require explicit state path and existing DB.
- Confirm chain verification before writes, atomic transaction rollback and bounded payloads.
- Perform disposal-copy migration/compatibility tests using the EXACT pinned kernel, then restore tests; no real DB writes.
**Exit:** independent code review, threat-model evidence, green adversarial CI, tested backup/rollback, host access proof.

### G3 — One harmless live cycle
- Explicitly authorize one deterministic read-only action (`inspect_status` or equivalent confirmed safe action) with unique correlation ID and idempotency key.
- Record canonical pending intent BEFORE dispatch.
- Dispatch through actual existing Hermes → actual MCP adapter; verify supported MCP version.
- Independently correlate observable output, executor attempt and receipt hash with same task.
- Evaluate; persist supported memory and agenda updates, retaining honest uncertainty; verify original event chain.
**Exit:** independent readback of all nine loop phases with real host provenance; any missing phase = NOT PASS.

### G4 — Recovery and adversarial acceptance
- Retried identical key, conflicting key, concurrent writes, missing/invalid principal, unauthorized scope, malformed input, oversized payload.
- Crash before dispatch; crash after dispatch before receipt; duplicate external response; lost verifier receipt; corrupt/tampered event chain; memory/agenda partial write; DB busy; rollback/backup restore.
- For ambiguous external results, reconcile before retry. Never claim exactly-once effect without external idempotency or reconciliation evidence.
- Restart Hermes and the adapter only under approved maintenance control, then fresh-session readback and resume from agenda.
**Exit:** all tests recorded with timestamps, actual host identity, failure injection results, expected versus observed and independent verifier attestation.

### G5 — Release and operation
- Doc checks unresolved/dropped work; TBQ assesses harvestable improvements; Verifier signs off independently. No invented consultation transcript.
- Confirm iPhone/Telegram operator controls allow status, pause, resume, evidence review and safe approval; demonstrate permissions and revocation.
- Only then merge chosen PR, deploy via least-privilege existing host route, confirm rollback, and mark release gate #20 complete.
**Exit:** reproducible live acceptance bundle, rollback drill, open-source security/privacy review, linked exact deployed commit, documented ongoing monitor.

## 5. Test matrix — what is proof and what is not

| Test | Environment | Pass criterion | Verification class |
| --- | --- | --- | --- |
| Writer idempotency, chain validation | Disposable SQLite | one intent/event, exact replay, no conflicting retry | local_disposable |
| GitHub Actions | PR SHA | deterministic suite green, pinned source | ci_disposable |
| Host read-only preflight | Authorized VPS | real principal, known runtime/DB, valid chain | host_observed |
| Live Hermes execution | Existing VPS | correlation and independent observation of actual action | host_observed |
| Learn/remember/agenda | Same live canonical DB | gated evaluation + durable readback | independently_verified_live only after verifier |
| Restart + ambiguity recovery | Existing VPS | no blind replay, reconciled receipt, persisted agenda | independently_verified_live |
| Revocation and rollback | Existing VPS | revoked identity rejected; safe restore verified | independently_verified_live |

No aggregate PASS if even one mandatory live gate is unknown.

## 6. Resilience decision table

| Fault | Required reaction |
| --- | --- |
| Intent commit fails | Do not dispatch; record failure outside canonical DB without claiming ledger write |
| Dispatch times out | `outcome_unknown`; query/reconcile executor; don't retry side effects blindly |
| Receipt is self-reported | `observed_unverified`; independent check required |
| Event chain corrupted | Reject writes and activation; preserve forensic snapshot |
| Duplicate same key / same content | Return original outcome and provenance; don't dispatch |
| Duplicate same key / changed content | Conflict, no mutation |
| Authentication, policy, or revocation failure | Deny before ACT and audit denial in trustworthy channel |
| DB busy / WAL contention | bounded retry only after operation safety assessment |
| Crash during transaction | rollback or recover via SQLite; verify chain after process restart |
| Memory update unsupported | leave learning incomplete, do not mark loop completed |
| Live host inaccessible | keep launch blocked; use disposable tests, no simulated live evidence |

## 7. Stop conditions and rollback

- STOP if source revision, host identity, DB schema, permissions, chain tip or authorized actor are ambiguous.
- STOP if adapter advertises unsupported MCP version; no protocol compatibility claim without handshake.
- STOP if observed action cannot be correlated independently.
- STOP if any write path promotes unverified observations to trusted memory or completion.
- Stop and roll back on live regression, preserving original DB backup and audit receipt. Never delete forensic evidence to make a test pass.

## 8. Evidence bundle contract

Publish sanitized signed/attested records with:
`run_id, run_start_utc, git_main_sha, candidate_sha, deployed_sha, host_pseudonym, principal_id, permissions_fingerprint, mcp_version, db_schema_fingerprint, intent_id, dispatch_attempts, receipt_id, output_digest, verifier_id, verdict, event_chain_before, event_chain_after, fresh_readback, agenda_effect, recovery_test_results, rollback_test_results, remaining_gaps`.

Exclude tokens, private keys, raw personal data and full database files. A hash of an untrusted blob is integrity evidence, not independently authenticated origin.

## 9. Workstream ownership and change-control

- **LeQutis:** final sovereign state/promotion authority.
- **Hermes:** bounded orchestration and execution; never self-certifies outcomes.
- **Verifier/Auditor:** independent result and record checks; no runtime authority to invent approvals.
- **Doc:** one release issue #20, dropped-task recovery, evidence completeness, blockers.
- **TBQ/Oracle:** research and challenge assumptions; proposals remain candidates until accepted.
- **Builder Swarm:** implement tests/repairs in isolated branches; no live privileges by default.

Only ONE canonical write contract and ONE acceptance scoreboard. Any experimental work must trace to a failing acceptance gate or be explicitly deferred.

## 10. Next deterministic action

1. Finish branch-scoped PR #17/#19 comparison and adversarial coverage.
2. Recover authorized connection to existing Hostinger Hermes with read-only inventory; do NOT substitute another VPS.
3. Run G1 → G2 → G3 → G4 → G5, capture evidence at each gate.
4. Close #20 only after independently verified live readback and recovery.

**Not in scope for first finish:** architecture redesign, new VPS, new console, Brahma source import, simulated persona consultations, unfounded CfC/Mamba/STAR/HAC adoption. These are independent candidates for post-acceptance evolution.
