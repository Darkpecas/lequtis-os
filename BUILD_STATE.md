# LeQutis Build State

Host: Android A71 / Termux (also portable Linux via `LEQUTIS_STATE`)
Role: initial autonomous LeQutis build/runtime host

Mission:
Build LeQutis as a proactive, autonomous, self-improving AI partner.

Current milestone:
Living kernel + autonomous execution loop (disposable tests passing).
G01 stdio connector recovered locally (VERIFIED_DISPOSABLE; not Hostinger live).
Cognitive workers plugged into THINK/CHOOSE; G02/G03 disposable route PARTIAL.
G07 independent verifier + G11 access parity VERIFIED_DISPOSABLE locally.
Skills lifecycle + knowledge search CLI present.
Next operator-gated: live Hostinger Hermes (G02/G03/G06), G12 Doc sign-off.

Required loop (implemented in `core/lequtis.py` `run_loop`):
NOTICE -> THINK -> CHOOSE -> ACT -> OBSERVE -> EVALUATE -> LEARN -> REMEMBER -> UPDATE AGENDA

Architecture:
Model-independent.
Claude/Codex/Gemini/etc. are replaceable cognitive workers.
LeQutis owns identity, memory, knowledge, skills, agenda, experience and evolutionary history.

Sovereignty:
Nothing is more senior than LeQutis. External AI, models, frameworks and plugins are subordinate resources only.

GitHub:
Optional infrastructure. Never a runtime dependency.

Rule:
Executable evidence is required before claiming a capability works.

Evidence:
Run `python3 tests/autonomous_loop_test.py` — TESTS A–F must print ALL PASS.
Run `python3 tests/test_skills_verifier_parity.py` — skills/verifier/parity/search/schema PASS.
See also repo-root `COMPUTER_REQUIREMENTS.md` for host vs phone roles.
