# Recovery after ACT — verification receipt

10 November 2026. Task: LQ-RECOVERY-AFTER-ACT-20261110.

LOCAL PROOF, NOT LIVE VPS VERIFIED.

## Outcome

Recovered the existing cancellation implementation in PR #29, head
`4fa29cd1f9118f1993cb3b36e5b46cb91da49961`, rather than recreate it.
Current main was `e3f3d7ff8e5d6a9db189dd99a90d4504b9efa50b`.
Authenticated connector principal: Darkpecas, user ID 44348609.
Repository: Darkpecas/lequtis-os, repository ID 1337559246.

A new integration regression kills a real run-once process with SIGKILL after
ACT and LEARN, before the terminal result commits. On the original PR code,
recover + retry creates two experience rows for the same agenda item. The
semantic row is already reused. The failing reproduction is retained.

The repair derives the experience memory ID from its agenda ID, refuses a
content/kind conflict, and commits insertion/reuse plus its audit event in one
SQLite transaction. Existing records are preserved; no schema change or
historical deduplication is performed. GOLDEN_MASTER.json is resealed for this
intentional kernel change; the prior seal is preserved alongside this receipt.

## Checks and observations

| Check | Observed result |
| --- | --- |
| Main baseline unittest discovery | PASS: 26 tests |
| Original PR #29 unittest discovery | PASS: 45 tests |
| New real-kill regression before repair | FAIL: duplicate experience row |
| Same regression after repair | PASS: same semantic and experience IDs/content after retry |
| Repaired unittest discovery | PASS: 46 tests |
| Killed worker lease | PASS: live holder retained; after kill old token rejected as stale_fence |
| Late result after cancellation | PASS: terminal result rejected and remains null |
| Duplicate proposal delivery | PASS: second commit rejected as already_committed |
| Existing standalone script suites, smoke and doctor | PASS on final runs |
| Golden master verification; git diff --check | PASS |

Commands: `python3 -W error::ResourceWarning -m unittest discover -s tests -p
'test_*.py' -v`; `python3 -W error::ResourceWarning
tests/test_recovery_after_act.py`. Standalone commands and return codes are
recorded in script-results.json and script-reruns.json. Raw stdout/stderr are
retained in the adjacent logs.

Two first standalone invocations failed because the verification runner set
LEQUTIS_DB globally while those scripts select their own temporary database
via LEQUTIS_STATE. Removing that runner override made both pass. This did not
require product code changes. The initial regression draft also incorrectly
parsed plain-text goal output as JSON; its initial error log is retained,
followed by the corrected failing reproduction.

## Boundaries and remaining work

- This tests disposable local databases and subprocesses. Hostinger/Hermes was
  not contacted and no production state was migrated or modified.
- Cancellation fences terminal result acceptance. It does not reverse memory
  or artifact effects that already happened before cancellation. It is
  cooperative, not a guarantee that every running worker instantly stops.
- The exact crash regression covers local memory effects. It does not prove
  exactly-once delivery to external systems.
- Recovery remains explicit recover then retry; unattended recovery is not
  established by this result.
- The swarm harness uses synthetic packets and mock workers; no claim about
  model swarm accuracy or performance follows.
- The fix prevents new duplicate experience IDs on retry. Pre-existing
  random-ID experience records require separate reconciliation if necessary.
- Review and merge the cancellation work and this repair before any explicitly
  authorized deployment; verify the intended live route independently.
