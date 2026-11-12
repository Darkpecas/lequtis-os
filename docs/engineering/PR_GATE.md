# PR gate

LOCAL PROOF, NOT LIVE VPS VERIFIED.

LeQutis remains the authority. This gate is a subordinate check. It does not call Hermes, Telegram, or Hostinger and it does not provision new infrastructure. The existing Codex GitHub review is the separate AI reviewer. This workflow only reads that review; it does not replace it.

`.github/workflows/lequtis-pr-gate.yml` runs on pull requests:

1. Run the unit suite. On failure, run it once more and record both attempts.
2. Wait up to four minutes for a Codex review.
3. `integrations/pr_gate.py` decides. Auto-merge is allowed only when the diff is non-empty, not already on the base, docs-only Markdown, tests passed, and Codex reported no finding.
4. Credentials, `database/migrations/`, `.github/`, Hermes or Hostinger paths, and destructive diff text are refused.
5. A PR body that says VERIFIED without a GitHub URL or an `evidence/` path is refused.

`Darkpecas/.git22` pull request 4 was not readable from this environment. The public page and the GitHub API both returned 404. No commits were recovered. An empty file diff with commits still listed is the case this gate calls `empty_pr`.
