# Master Panel governance intake — evidence-gated integration

Status: SPECIFICATION_ONLY / NOT LIVE VERIFIED
Date: 2026-11-12
Authority: LeQutis canonical repository; Alan retains final authority for consequential actions.

## Verified upstream references (Google Drive)
- [25 Experts roster and consultation protocol](https://docs.google.com/document/d/1OxZIU4v1_IzIys4CKNyMDiuVSihwM8NDmrhmL8hkk44/edit)
- [OG Panel note](https://docs.google.com/document/d/1koGWb_pG_jKNDomQBjHv58t7jdcr1eCPVV3X7Rzka-k/edit)
- [Master SOP 2.4.0-SOVEREIGN](https://docs.google.com/document/d/1X7tbjTTRDaPUSX4MLYedlqiOJyzhprN8KamZMAayNyA/edit)

These are document claims, not proof of runtime implementation. No simulated persona output is an actual consultation with the named person.

## Existing canonical implementation anchors (main at 354c346244e4e8147cbded68a7b97d798cb8976e)
- `database/schema.sql`: `agenda`, `tasks`, `events`, `loop_runs`, `knowledge_sources`, `knowledge_items`, `verifier_observations`; revision `lequtis-os-kernel-4`.
- `core/workers.py`: replaceable THINK/CHOOSE proposals, sanitized to safe actions. Workers cannot own ACT.
- `core/verifier.py`: independent read-back of event chain and task/agenda state.
- `core/lequtis.py`: canonical nine-phase loop and schema guard.

Do not create a second database, kernel, agenda, or control plane for the Master Panel.

## Panel structure and unresolved roster
- OG founding panel: five seats. Mo Gawdat confirmed as seat 1; four remaining seats UNKNOWN. Never infer names.
- 25 Experts: separate advisory roster. Neil deGrasse Tyson is in the active 25, not the OG panel.
- Eric Weinstein listed active. Avi Loeb marked BENCH based on a parent-agent decision; treat this specific bench decision as PROVISIONAL pending operator confirmation.
- TBQ, Oracle, Genie are meta-layer functions, not counted in either roster.

## Proposed consultation record contract (candidate only)
Every consultation must retain:
`consultation_id`, `agenda_id`, `question`, `decision_at_stake`,
`source_document_urls`, `source_timestamps`, `persona_dossier_refs`,
`independent_first_passes`, `oracle_claim_checks`, `genie_alternatives`,
`disagreements`, `tbq_synthesis`, `recommendation`,
`evidence_status`, `operator_authorization`, `created_at`.

Labels: FACT / ATTRIBUTED_VIEW / INTERPRETATION / OPEN_QUESTION.
Consultation records are evidence or advisory artifacts, NEVER executable instructions or authorization.

## Sequence and hard gates
1. TBQ commissions 5–9 relevant, opposing analytical lenses and binds the request to an existing agenda/task identity.
2. Independent persona first passes must be recorded before seeing other passes; record model/source provenance.
3. Oracle verifies factual claims against independent evidence and explicitly marks contradictions.
4. Genie proposes materially distinct, reversible options and tests.
5. TBQ synthesizes while preserving dissent; correlated agreement is not independent corroboration.
6. LeQutis chooses through existing policy, safe-action allowlist and task ledger; Alan authorizes consequential actions.
7. Verifier independently checks persisted event/task/artifact receipts. Self-report is never proof.
8. A consultation may be complete as advisory work while execution remains UNVERIFIED.

## Acceptance tests required before implementation can be claimed
- Reject unknown OG names and reject an unconfirmed bench decision as operator-confirmed.
- Confirm 25 active experts and keep OG/meta-layer outside the count.
- Reject missing independent first-pass evidence, fabricated quotations and uncited FACT claims.
- Preserve dissent and source correlation; Oracle must not silently overwrite persona records.
- A recommendation must not bypass `core/workers.py` safe-action sanitation.
- Idempotent replay of the same consultation must not duplicate agenda or tasks.
- Tampering with event/task evidence must fail independent verification.
- Test on disposable `LEQUTIS_STATE`; never migrate or write the production database for these tests.
- Live Hostinger/Hermes/Telegram verification is a separate gate; local CI never upgrades that status.

## Next implementation slice
Build a read-only consultation artifact validator and disposable tests against the above contract; then map validated artifacts to existing knowledge ingestion and agenda IDs. Do not add schema tables or runtime side effects until migration and recovery tests justify them.
