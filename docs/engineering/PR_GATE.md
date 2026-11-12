# PR gate

LOCAL PROOF, NOT LIVE VPS VERIFIED.

LeQutis remains the authority. This gate is a subordinate check. It does not
call Hermes, Telegram, or Hostinger and it does not provision new
infrastructure. External agents (Cursor, Codex, GitHub Actions) are workers.

`.github/workflows/lequtis-pr-gate.yml` runs on pull requests as two jobs:

1. **verify** (read-only): checkout with `persist-credentials: false`, run the
   unit suite once and retry once on failure. No repository write token.
2. **decide** (write): uses trusted policy scripts from `base_ref` when present
   (bootstrap from the PR tree only if main lacks the helpers). Runs the
   static auditor and Codex wait, then `pr_gate.py`. Auto-merge is allowed
   only for non-empty, non-duplicate, docs-only Markdown after tests + static
   audit + Codex pass. Rename detection is disabled. Merge uses
   `--match-head-commit` and a per-PR concurrency group.
3. Credentials, `database/migrations/`, `.github/`, Hermes or Hostinger paths,
   and destructive markers on **added** diff lines are refused.
4. A PR body that says VERIFIED without a GitHub URL or an `evidence/` path is
   refused.
5. Merge outcome updates preserve the original `correlation_id`.

## Investigation note

`Darkpecas/.git22` pull request 4 was not readable from this environment. The
public page and the GitHub API both returned 404. No commits were recovered.
An empty file diff with commits still listed is the case this gate calls
`empty_pr` (also seen on disposable Copilot "Initial plan" PRs such as #24 /
#33).

## Evidence classes (do not substitute)

| Class | What counts |
| --- | --- |
| Static validation | Unit tests for `pr_gate`, `pr_static_auditor`, `engineering_workflow` |
| Local execution | `python3 -m unittest discover -s tests -p 'test_*.py'` on a disposable checkout |
| Live end-to-end | GitHub Actions run URL + PR comment receipt + (for auto-merge) merge commit on `main` |

A green local unittest run is not a live auto-merge proof.
