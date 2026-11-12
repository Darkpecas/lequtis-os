# PR gate

LOCAL PROOF, NOT LIVE VPS VERIFIED.

LeQutis remains the authority. This gate is a subordinate GitHub Actions check.
It does not call Hermes, Telegram, or Hostinger and it does not provision new
infrastructure. Existing Hostinger Hermes and Telegram remain the live control
plane when authorized; this workflow only emits assimilable receipts.

Auto-merge is off by default. The receipt still records `merge_allowed`. The
workflow calls `gh pr merge` only when the repository variable
`LEQUTIS_AUTOMERGE_ENABLED` is `true`. See [AUTOMERGE.md](AUTOMERGE.md).

## Flow

When auto-merge is enabled, this workflow also requires the free Gemini review (`gemini-3.8-flash`) for the same head SHA. A missing `LEQUTIS_REVIEWER_API_KEY` fails that review closed. With the default (auto-merge off), the review is still collected and the workflow does not merge. `.github/workflows/lequtis-engineering-gate.yml` applies the denylist, including `infra/terraform/`, and posts the engineering receipt.

`.github/workflows/lequtis-pr-gate.yml` runs on pull requests:

1. Run the unit suite. On failure, run it once more and record both attempts.
2. Wait for the disposable evidence `verify` check (with a bounded soft fallback).
3. Wait briefly for the separate Codex/ChatGPT review when present.
4. Run `integrations/pr_auditor.py` — an independent deterministic auditor,
   separate from the implementing agent.
5. `integrations/pr_gate.py` decides and writes:
   - `evidence/pr-gate-receipt.json`
   - `evidence/pr-auditor-receipt.json`
   - `evidence/engineering-workflow-receipt.json` (task_id + correlation_id)
6. The receipt sets `merge_allowed` only when the diff is non-empty, not already
   on the base, docs-only Markdown under `docs/`, tests passed, required checks
   passed, and independent review is `pass` (Codex when present, otherwise
   auditor). That flag does not merge the pull request. See
   [AUTOMERGE.md](AUTOMERGE.md).

## Hard blocks (never auto-merged)

- Credentials / secret-like assignments
- `database/migrations/`
- `.github/` workflow infrastructure
- Hermes / Hostinger paths
- Destructive *added* diff lines (`DROP TABLE`, delete APIs, `rm -rf /`)
- Empty diffs (commits with zero net files)
- Duplicate stable patch-ids already on the base
- `VERIFIED` / completion claims without a GitHub URL or `evidence/` pointer

## Architecture mapping

```
LeQutis (authority)
  → Oracle / TBQ (human Doc sign-off remains G12; not replaced)
  → Hermes (existing Hostinger workforce; not called from this workflow)
  → Builder Swarm (external agents are subordinate implementers)
  → Verifier / Auditor (pr_auditor + kernel verifier + Codex when present)
```

Engineering receipts use `task_id=eng-pr-<n>` and
`correlation_id=pr-<n>-<head12>` so a later Hermes/TBQ step can assimilate them
without treating GitHub as a runtime dependency.

## `.git22` PR #4

`Darkpecas/.git22` pull request 4 was not readable from this environment. The
public page and the GitHub API both returned 404. No commits were recovered.
Canonical `Darkpecas/lequtis-os` already contains the merged port from
`.git22` PR #5 via lequtis-os PR #4. An empty file diff with commits still
listed is the case this gate calls `empty_pr`.
