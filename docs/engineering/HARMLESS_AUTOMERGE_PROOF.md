# Harmless auto-merge proof

LOCAL PROOF, NOT LIVE VPS VERIFIED.

This disposable Markdown file exists only to exercise the LeQutis PR gate:

BUILD → PR → INDEPENDENT REVIEW → TEST → VERIFY → DOCS-ONLY MERGE → READ-BACK.

Automation may merge this kind of change only when the head SHA passes checks,
the independent review for that SHA is clean, and the pull request has no
`needs-human` label. Any other diff is labelled `needs-human` and left for a
human. This file changes no code, credentials, migrations, workflows, Hermes,
or Hostinger paths. Safe to delete after the merge receipt is recorded.

Evidence pointers for this workflow family:

- https://github.com/Darkpecas/lequtis-os/pull/42
- https://github.com/Darkpecas/lequtis-os/actions/runs/43135633780
- evidence/pr-gate-receipt.json (CI artifact on gate runs)
