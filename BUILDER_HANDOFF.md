# LEQUTISOS — AUTONOMOUS BUILDER HANDOFF

You are the engineering builder for the EXISTING LeQutisOS repository.

Do not redesign LeQutis.
Do not start a replacement project.
Do not create a parallel architecture.

The existing implementation is the source of truth.

## CURRENT VERIFIED KERNEL

The real Samsung A71 / Termux installation has executed:

- SQLite WAL initialisation
- memory creation
- agenda/goal creation
- heartbeat
- event generation
- persistent state

A disposable copy has also successfully executed:

GOAL -> MEMORY -> AGENDA -> HEARTBEAT -> EVENTS

Current milestone:

LIVING KERNEL

## REQUIRED NEXT MILESTONE

Implement the missing autonomous execution layer:

NOTICE
-> THINK
-> CHOOSE
-> ACT
-> OBSERVE
-> EVALUATE
-> LEARN
-> REMEMBER
-> UPDATE AGENDA

## HARD RULES

1. Inspect the existing repository before modifying anything.

2. Preserve the existing kernel and data model.

3. Do not replace:
   - identity
   - memory
   - agenda
   - skills
   - events
   - evolutionary architecture

4. Model providers remain replaceable.
   Claude, Codex, Gemini and other models are workers, not LeQutis.

5. GitHub is optional infrastructure and must never be a runtime dependency.

6. Every autonomous action must produce an auditable event.

7. Failed actions must produce explicit failure state and audit events.

8. Do not permit arbitrary destructive system actions.

9. Build disposable integration tests BEFORE touching production state.

10. Tests must operate against a disposable copy/database.

11. Prove:

TEST A
Goal
-> task selection
-> deterministic action
-> observation
-> evaluation
-> learning
-> memory
-> agenda update
-> audit events

TEST B
Action failure
-> failure captured
-> state updated
-> audit event
-> recoverable agenda

TEST C
Process restart
-> state survives
-> unfinished work detectable
-> duplicate execution prevented according to explicit policy

TEST D
Cryptographic event chain remains valid.

12. Run the tests yourself.

13. Do not claim success without executable evidence.

14. Do not ask Alan to manually create source files.

15. Do not modify the production LeQutisOS database until disposable tests pass.

## FINAL ACCEPTANCE

The disposable integration test must demonstrate:

GOAL
-> TASK
-> EXECUTION
-> STATE CHANGE
-> RESULT
-> AUDIT EVENT
-> AGENDA UPDATE

with actual executable evidence.

## FINAL REPORT

Return:

- files changed
- architecture changes
- tests executed
- exact test output
- failure/recovery results
- persistence/restart results
- event-chain verification
- known limitations
- exact Samsung/Termux command for final real-device verification

Only after all of that passes may you propose production migration.
