# PR gate

LOCAL PROOF, NOT LIVE VPS VERIFIED.

LeQutis remains the authority. This gate is a subordinate check. It does not
call Hermes, Telegram, or Hostinger and it does not provision new
infrastructure. External agents (Cursor, Codex, GitHub Actions) are workers.

`.github/workflows/lequtis-pr-gate.yml` runs on pull requests:

1. Run the unit suite. On failure, run it once more and record both attempts.
2. Run `integrations/pr_static_auditor.py` (independent of the implementing
   agent; deterministic; not a model).
3. Wait up to four minutes for a Codex review of the **current head SHA**
   (separate AI reviewer; historical reviews of older commits do not count).
4. `integrations/pr_gate.py` decides. Auto-merge is allowed only when the diff
   is non-empty, not already on the base, docs-only Markdown, tests passed,
   static audit passed, and Codex reported no finding. Rename detection is
   disabled so a dangerous path moved into `docs/` still fails.
5. `integrations/engineering_workflow.py` writes one receipt linking
   task → PR → review → tests → verify → merge decision.
6. Credentials, `database/migrations/`, `.github/`, Hermes or Hostinger paths,
   and destructive markers on **added** diff lines are refused.
7. A PR body that says VERIFIED without a GitHub URL or an `evidence/` path is
   refused.
8. Merge uses `gh pr merge --match-head-commit` and a per-PR concurrency group
   so a newer tip cannot inherit an older green decision.

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
