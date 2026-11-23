# LeQutis assimilation digest — 2026-11-23

Scope: six LeQutis Google Docs read on 2026-11-23 (project index, master SOP, progress review, Brahma Evo register, sovereignty rule, Curator record). Source documents are the owner's Drive docs; this digest transcribes their claims and labels them. It does not independently re-verify VPS state, GitHub state or runtime logs.

Labels: VERIFIED = observed directly in a source doc with a receipt. UNVERIFIED = claimed, not observed. OPEN = not done. BROKEN = found failing.

## 1. Authority rule (non-negotiable)

- LeQutis is sovereign. No external AI, model, framework, plugin or service may outrank, supersede or replace it (Sovereignty Rule, 2026-11-08).
- Brahma Evo is a research candidate only. Its licence (Source-Available Personal Use v2.0) forbids redistribution, commercial incorporation and cloud hosting. No code import, no Hostinger deployment.
- Auto-executing model-generated code, unpinned installs, TLS bypass and open-by-default gateways are rejected patterns.

## 2. Where the runtime stands (per Progress Review, 17 Nov)

- VERIFIED: kernel `Darkpecas/lequtis-os` deployed at `/opt/lequtis` on the Hostinger VPS, main `90ac0a6` (PR #30 merged). Doctor PASS, 99/99 tests, golden master OK.
- VERIFIED: Hermes gateway (hermes-agent 0.23.1) running under systemd with a watchdog. Telegram and WhatsApp answer. Free models only, $0 spend.
- VERIFIED: loop proofs `loop-proof-20261117-01` and `-02` survived gateway and MCP restarts with fresh-process read-back.
- VERIFIED: `lequtis-mcp.service` repaired (mcp pinned 1.30.0, loopback, read-only).
- OPEN: G06 phone loop (one Telegram message from Alan, written and read back).
- OPEN: approve/dispatch tool. Intake rows sit in `awaiting_approval` by design.
- OPEN: PRs #31, #34, #49, #53, #54, #55 (#54 is the zero-default credit guard, needed before any hosted-model worker).
- BROKEN: SOP autosync (`lequtis_sop_autosync_v2.5.py`) has no scheduler on the VPS. Last snapshot 12 Nov.
- OPEN: ET / LN creative-sleep persona files not recovered. Hash originals before any LN sleep experiment.

## 3. Ten-chat gates (Ten-Chat Ledger, 16 Nov)

G00 host identity and G01 deployment are effectively met by the VPS deployment. G02/G03 (authenticated transport, canonical write) are covered by the loop proofs. G04 (independent proof), G05 (resilience), G06 (phone loop) and G07 (Doc/TBQ closure) remain OPEN. The Doc obligation ledger (69 items) is unreconciled.

## 4. Brahma Evo register (8–10 Nov)

- Skill admission gate: a stdlib-only additive module with tests was built locally (R3: 12/12 unit tests, 9/9 disposable E2E). It was tested against a reconstructed kernel fixture, not the exact upstream checkout. Receipt authenticity is explicitly UNVERIFIED.
- Public repo main was checked at `425a2f3`: CI run #41 green for the disposable scope. Vercel status was FAILURE (rate limit) on that commit.
- Known test debt: `tests/test_execution.py` fails against current contracts (5 tests: 2 failures, 3 errors) and is not run in CI. Do not claim all tests pass.
- Known warning debt: SQLite connections leak in legacy code (ResourceWarning). Visible in local unittest runs here.
- Decision D06: live bridge activation deferred until a callable authorised connector and a benign read-only handshake are proven.

## 5. Curator and other agents

- Curator (YouTube harvest agent, archive record 16 Nov): on-request only. Current runtime status UNVERIFIED.
- The Borg Queen (TBQ) is a Hermes skill, advisory only. No live TBQ gate signature exists. Her original Gem/GPT instruction text is missing.
- Master Panel dossiers (25 experts) are documents only. No persona transcript may be presented as a genuine consultation.

## 6. Gaps in this assimilation

- I cannot converse with ChatGPT, Gemini, Grok or other LLMs from this session. No connector exposes their chats. The Gemini MCP connector provides market data only.
- Notion has no LeQutis content.
- Zip attachments in Drive (prior-conversation recovery, Grok transfer, research arrays) were not opened. Their contents are unverified.
- Gmail, Calendar and iCloud were not searched.

## 7. Next steps (from the source docs, in priority order)

1. Alan sends one Telegram message (closes G06).
2. Merge #31 then #34; re-run CI on the merged head.
3. Merge #54 before any hosted-model worker is enabled.
4. Schedule the SOP autosync on the VPS as a systemd timer.
5. Build the approve/dispatch tool so `awaiting_approval` items can move.
6. Fix the `tests/test_execution.py` contract drift and the sqlite connection leaks.
7. Run G05 resilience tests, then G07 Doc/TBQ closure.
8. Alan's own items: spend limit to 0, GitHub lock, rotate the Telegram token and OpenRouter key.

## 8. Decisions waiting on Alan

- Reseal the file changed by the LQ-16 `core/lequtis.py` fix?
- Commit author name and email before any Builder push.
- TBQ triple-gate key: stay at tier 2? Is "The Figure In Question" still an alias?
- FreeLLMAPI: evaluate only; do not deploy until upstream issue #1890 is fixed.
