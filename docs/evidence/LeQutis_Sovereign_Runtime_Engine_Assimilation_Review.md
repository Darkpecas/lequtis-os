# Assimilation review: Sovereign Runtime Engine

**Disposition:** `SELECTIVE_HARVEST` — source reviewed; runtime implementation not adopted.  
**Review date:** 2026-11-10  
**Candidate:** attached `LeQutis_Sovereign_Runtime_Engine.py`  
**Candidate SHA-256:** `b7f19eeb7bde39fc5f0698665a78270d185ee1ad2ab317aa1ef31e0013f16a79`  
**Canonical baseline:** `Darkpecas/lequtis-os`, main at `425a2f32f3ddf762f6371e8508f8a78e290d4663`

## Evidence boundary

The attached 197-line Python file was read and parsed with Python's AST parser (`AST_PARSE_PASS`). It was not imported or executed; its entry point creates a SQLite database, enables WAL, and writes a JSONL file. No live LeQutis database, Termux checkout, or Hostinger Hermes service was accessed. The canonical repository files were inspected through GitHub at the baseline commit above. The repository's existing acceptance record is documentation, not a test run from this review.

## Comparison with the canonical runtime

The current kernel already owns a single SQLite WAL event ledger. `core/lequtis.py` configures WAL and full synchronous writes, appends events to the canonical `events` table, hashes the previous hash, timestamp, event type and payload, and verifies the chain independently. The same schema already has canonical memory, loop-run, skills, task and agenda records. This is the authority boundary described by the repository's README and architecture.

The candidate instead creates a parallel `LeQutisEventStore` schema and a second JSONL log. It does not adapt to the existing schema, loop, event API, admission lifecycle, or verifier. Adding it as a runtime would create a second memory and audit authority.

## Findings

1. **The claimed adversarial consensus is not implemented.** The docstring promises a Jaccard overlap threshold of 0.60, but the function computes no overlap. Approval only requires zero truthy `contradiction_detected` flags and at least one item in `evidence_hashes`; it does not validate hashes, provenance, independent swarm roles, or a quorum. A single proposal with an arbitrary non-empty evidence string can pass.

2. **The event hash omits fields the verifier reads as metadata.** The hash covers serialized event data, previous hash, version and timestamp, but excludes event type, aggregate ID, agent ID and event ID. Altering those excluded columns would not be detected by `verify_integrity`.

3. **The two persistence writes can diverge.** The SQLite insert and JSONL append are separate storage operations without an outbox/reconciliation protocol. A partial file write or database commit failure can leave only one side recorded.

4. **The state projection is unfinished.** `AgentMemoryState` is created but never populated or queried. The candidate has no loop transitions, replay/recovery behavior, idempotency contract, or independent verifier integration.

5. **Reuse provenance is incomplete.** No licence declaration or upstream provenance accompanies the attachment. This review records findings and principles in original prose and does not copy executable source into LeQutis.

## Assimilation decision

- **Reject** adding these classes, tables, or JSONL ledger to the sovereign runtime.
- **Harvest** the general requirement that any future consensus decision be tied to inspectable, claim-level evidence and verified independently. LeQutis already has the canonical event chain and candidate-bound skill admission path to host such work.
- **Do not adopt** the S5 threshold or its approval result. If consensus becomes a real requirement, specify the proposal schema, evidence provenance, role/quorum rules and contradiction semantics first, then implement against the canonical ledger with adversarial tests.
- **Preserve** this review as an evidence-pack record. The documented `python3 core/lequtis.py assimilate` command can index Markdown under `docs/evidence/` into the selected local runtime state; that command was not run here, so no runtime memory update is claimed.

This is a selective research/evidence assimilation, not a runtime integration or live-loop acceptance.
