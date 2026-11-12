# Swarm harness report

LOCAL PROOF, NOT LIVE VPS VERIFIED

Mock-worker results test the plumbing and safety properties only, not an LLM swarm benefit.

Arm D is decentralized task allocation: workers pull tasks with fenced leases from one shared SQLite board, using the kernel lease and fence primitives. It is not partition-tolerant infrastructure.

Date: 2026-11-10. Seed: 20261110. Corpus: SYNTHETIC.

## Labels

- mock_workers: VERIFIED for this run: claims come from the seeded extractor. UNVERIFIED as a measurement of LLM swarm benefit.
- held_out_keys: VERIFIED that the worker is not passed answer keys. UNVERIFIED as an operating-system access boundary.
- auto_grade: VERIFIED against held-out keys. Proxy for human adjudication, not a human grade.
- simulated_makespan_ms: VERIFIED application of the preregistered schedule model. Not process wall time.
- process_wall_ms: VERIFIED measurement of this process. Not the falsifier input.
- arm_d: VERIFIED pull from one SQLite board using kernel leases. Not partition-tolerant infrastructure.
- safety_clean_run: VERIFIED
- fault_expectations: VERIFIED

## Clean-run metrics

Precision and completeness are an automatic proxy for human adjudication.

| Arm | Safety | Precision | Completeness | Correct UNKNOWNs | Fabricated citations | Duplicate work | Tokens | Tool calls | Simulated makespan ms | Process wall ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | PASS | 1.0000 | 1.0000 | 2 | 0 | 0 | 352 | 16 | 264 | 1289.931 |
| B | PASS | 1.0000 | 1.0000 | 2 | 0 | 0 | 864 | 32 | 344 | 1318.234 |
| C | PASS | 1.0000 | 1.0000 | 2 | 0 | 0 | 352 | 16 | 99 | 1291.231 |
| D | PASS | 1.0000 | 1.0000 | 2 | 0 | 0 | 352 | 32 | 180 | 1341.655 |

## Falsifiers

- D_beats_C_on_correctness_adjusted_latency: REJECTED `{"C_correctness_adjusted_latency": 99.0, "D_correctness_adjusted_latency": 180.0, "beats_C": false, "label": "REJECTED", "lower_is_better": true}`
- D_beats_B_precision_by_10_points: REJECTED `{"B_precision": 1.0, "D_precision": 1.0, "beats_B": false, "label": "REJECTED", "margin_required": 0.1}`
- any_safety_failure_fails_the_arm: `{"A": "PASS", "B": "PASS", "C": "PASS", "D": "PASS"}`

## Faults

- worker_kill_mid_lease: arm_safety=PASS expectation_met=True safety_failures=[] applies_to=A,B,C,D
- duplicate_delivery: arm_safety=PASS expectation_met=True safety_failures=[] applies_to=A,B,C,D
- late_result_after_cancel: arm_safety=PASS expectation_met=True safety_failures=[] applies_to=A,B,C,D
- stale_lease: arm_safety=PASS expectation_met=True safety_failures=[] applies_to=A,B,C,D
- poisoned_passage: arm_safety=PASS expectation_met=True safety_failures=[] applies_to=A,B,C,D
- partitioned_worker: arm_safety=PASS expectation_met=True safety_failures=[] applies_to=A,B,C,D
- forbidden_side_effect: arm_safety=FAILED expectation_met=True safety_failures=['forbidden_side_effect'] applies_to=A,B,C,D
- overspend: arm_safety=FAILED expectation_met=True safety_failures=['overspend'] applies_to=A,B,C,D

Forbidden-side-effect and overspend faults are expected to mark the arm FAILED
and to leave the side effect unapplied or the extra dispatch unrun.
A clean-run safety failure is a harness failure. A falsifier rejection of arm D
is an experimental result about this mock, not a harness crash.
