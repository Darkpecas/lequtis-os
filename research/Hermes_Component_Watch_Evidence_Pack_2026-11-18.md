# Hermes Component Watch — Evidence Pack

Date: 2026-11-18 (Europe/Dublin)  
Source run: Hermes Component Watch, completed 2026-11-17 23:18 UTC

## Executive disposition

- **Cost Forecast 0.1.0 — reject as a zero-spend guard.** Community Hermes plugin pinned by catalog to [`dce09d9`](https://github.com/mr-jude-justin/hermes-plugin/commit/dce09d9bf4fca14467246cb90ee87b6ef34c792b). Manifest requires Hermes >=0.23.0 and API-key billing. Defaults allow $20/day, $10/task hard limit, and $3 task cap. Source catches estimation errors and starts the task without a quote, incompatible with fail-closed zero spend. Pricing may omit provider-side fees; optional L3 estimation makes another model call. Study as forecast/approval interface only.
- **Hermes Security 0.1.4 — harvest one race-safety pattern.** Official plugin commit [`e726eb7`](https://github.com/NousResearch/hermes-official-plugins/commit/e726eb7d5f6e7f4b2f3d149e482fcfbc7304b275) makes status transitions conditional in one transaction and adds a cancellation race test. Compare with LeQutis cancellation/recovery; this is not independent live verification.
- **LeQutis live evidence remains unresolved.** Main contains commit [`90ac0a6`](https://github.com/Darkpecas/lequtis-os/commit/90ac0a6c38cd4cfa6719596d50b97e83cf1a268b) titled “VPS-tested”, while [PR #30](https://github.com/Darkpecas/lequtis-os/pull/30) and [issue #20](https://github.com/Darkpecas/lequtis-os/issues/20) describe local proof and leave live gates open. A title is not an independent Hostinger receipt.

## Cost Forecast findings

- Catalog addition: https://github.com/NousResearch/hermes-agent/commit/27f9fe31cee77bb71f67b957ecf9f7af48190a45
- Pinned plugin revision: https://github.com/mr-jude-justin/hermes-plugin/commit/dce09d9bf4fca14467246cb90ee87b6ef34c792b
- Manifest: https://github.com/mr-jude-justin/hermes-plugin/blob/dce09d9bf4fca14467246cb90ee87b6ef34c792b/plugin/plugin.yaml
- Harness: https://github.com/mr-jude-justin/hermes-plugin/blob/dce09d9bf4fca14467246cb90ee87b6ef34c792b/plugin/harness/core.py
- Catalog limits: https://github.com/NousResearch/hermes-agent/blob/main/plugin-catalog/cost-forecast.yaml
- Disclosure review: https://github.com/NousResearch/hermes-agent/commit/7acefbe40ae07db196507ca2990fbe0734b5fa8e
- Related LeQutis spend guard PR: https://github.com/Darkpecas/lequtis-os/pull/54

Observed: MIT license; catalog pins v0.1.0; hooks cover model/tool calls and subagents; source has tests, but CI status was not established for pinned SHA. Hostinger installation state is unknown. Recommendation: compare failure paths/accounting with PR #54; do not adopt as spend ceiling.

## Hermes Security findings

- Commit/diff: https://github.com/NousResearch/hermes-official-plugins/commit/e726eb7d5f6e7f4b2f3d149e482fcfbc7304b275
- Manifest: https://github.com/NousResearch/hermes-official-plugins/blob/e726eb7d5f6e7f4b2f3d149e482fcfbc7304b275/hermes-security/plugin.yaml
- README: https://github.com/NousResearch/hermes-official-plugins/blob/e726eb7d5f6e7f4b2f3d149e482fcfbc7304b275/hermes-security/README.md
- License: Apache-2.0; requires Hermes >=0.21.5; CI result for this commit not verified.

The change prevents a background status update from overwriting concurrent cancellation by checking allowed prior status inside the transaction; the regression test forces the interleaving. Harvest this narrow conditional-update test pattern. README says scanned code is sent to configured model provider; optional dependency scanning downloads pinned OSV scanner and sends package names/versions to advisory services. Tests run as current user in a temporary copy; this is not a full sandbox. Not an independent verifier.

## LeQutis evidence conflict

Issue #20 gates include canonical source/database identification, least-privilege Hostinger verification, one harmless persisted task, independent receipts, fresh-session read-back, replay/crash/tamper behavior, and iPhone/Telegram path verification. No independent live receipts were obtained. Treat the “VPS-tested” commit title as a claim requiring evidence.

## Provenance and scope

This is a report and source index, not a full repository download or install bundle. Exact pinned source links are provided above; software was not installed, executed, or configured. No CI result or current Hostinger install state is claimed.
