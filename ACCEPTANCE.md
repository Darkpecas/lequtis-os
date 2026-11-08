# Acceptance evidence — autonomous loop

Date: 2026-11-08

## Command

```sh
python3 tests/autonomous_loop_test.py
python3 tests/test_skills_verifier_parity.py
```

## Results

| Test | Result |
| --- | --- |
| A happy path GOAL→…→AUDIT | PASS |
| B failure + recoverable agenda | PASS |
| C restart + idempotent replay | PASS |
| D event-chain integrity | PASS |
| CLI disposable subprocess | PASS |
| E sources/assimilate | PASS |
| F inbox + gate seed | PASS |
| Skills lifecycle + independent verifier + access parity + search + schema | PASS |

## G01 stdio connector (2026-11-08 follow-up)

```sh
python3 tests/test_bridge.py
python3 tests/test_host_preflight.py
python3 runtime/hermes-stdio-connector/host_preflight.py --allow-missing-hermes --json
```

Local disposable recovery of the System Access Manager stdio contract:
read-only `lequtis_status` / `lequtis_verify_events` / `hermes_probe`,
opt-in `hermes_query`, preflight exits 0/2/3. Gate G01 →
`VERIFIED_DISPOSABLE` only.

## Cognitive workers + G02/G03 disposable (same day)

```sh
python3 tests/test_workers.py
python3 tests/test_hermes_route.py
python3 runtime/chatgpt_hermes_route/route.py
```

- THINK/CHOOSE accept replaceable workers (`LEQUTIS_WORKER=deterministic|script|openai`).
- ACT remains the safe registered action set only.
- G02/G03 → `PARTIAL` (disposable authorize + probe receipts). Live Hostinger still needs operator tunnel env.
- Beast LIVE path beyond mock: `LoopbackMcuTransport` + `pump_mcu_io` unit-tested (no hardware).

## G07 / G11 local completion (same day)

```sh
python3 tests/test_skills_verifier_parity.py
python3 core/lequtis.py parity
python3 core/lequtis.py verify-independent <correlation_id>
```

- Skills lifecycle API (`PROPOSED→SANDBOXED→ENABLED→RETIRED`) rejects
  promotion without structured, candidate-bound test and admission receipts.
- Receipt validation checks recorded status, candidate/version, artifact hash,
  and test-receipt linkage; it does not execute code or authenticate issuers.
- Independent verifier rejects self-report alone (G07 → `VERIFIED_DISPOSABLE`).
- ACCESS/SOURCES/gates ID parity checker (G11 → `VERIFIED_DISPOSABLE`).
- Knowledge `search` CLI + schema.sql drift guard.

## Known limitations

- Live OpenAI/provider keys are optional; default worker is deterministic.
- Hermes / Hostinger live bridge is not connected; stdio adapter is local only.
- Plugins remain packages-not-runtime until an authorized execution route
  is verified.
- Production Termux DB must not be migrated until Alan reviews this evidence.
- Canonical `Darkpecas/lequtis-os` push still requires Alan (agent 403).
- G06 / G12 remain OPEN until live Hermes + Doc/TBQ sign-off.
