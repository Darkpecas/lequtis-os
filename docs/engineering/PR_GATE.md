# PR gate

LOCAL PROOF, NOT LIVE VPS VERIFIED.

LeQutis remains the authority. This gate is a subordinate GitHub Actions check.
It does not call Hermes, Telegram, or Hostinger and it does not provision new
infrastructure. Existing Hostinger Hermes and Telegram remain the live control
plane when authorized; this workflow only emits assimilable receipts.

## Flow

An automated merge in this workflow is allowed only for documentation, and only after `integrations/engineering_gate.py authorize-merge` verifies the same head SHA. Documentation means `*.md` under `docs/` or a README. It does not include executables, workflows, config, `GOLDEN_MASTER.json`, or anything under `infra/`, `.github/`, `core/`, `integrations/`, or `tests/`. The command also requires passing checks, a clean `github-actions[bot]` review for that SHA, and a fetched label list that does not contain `needs-human`. If any of those cannot be verified, the workflow does not merge. A missing `LEQUTIS_REVIEWER_API_KEY` fails the free Gemini review (`gemini-3.8-flash`) closed, so this workflow does not merge. `.github/workflows/lequtis-engineering-gate.yml` applies the same rule and the denylist, including `infra/terraform/`, and posts the engineering receipt. The workflow does not pass `--auto` and does not remove `needs-human`.

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
6. Automation may merge only when `authorize-merge` verifies a documentation
   diff, passing checks on that head SHA, a clean independent review for that
   SHA, and no `needs-human` label. The squash merge uses `--match-head-commit`.
   Every other diff is labelled `needs-human` and is not merged by this workflow.

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
