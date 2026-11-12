# Auto-merge

Auto-merge is off by default. Nothing in this repository merges a pull request unless a repository admin sets the Actions variable `LEQUTIS_AUTOMERGE_ENABLED` to the string `true`.

`merge_allowed` in the PR gate receipt and `merge_decision` in the engineering receipt stay as policy signals. Review, unit tests, the disposable `verify` check, and the independent review keep running and keep posting those results.

## Where the merge lives

Only these jobs call `gh pr merge`:

- `merge` in `.github/workflows/lequtis-pr-gate.yml`
- `merge` in `.github/workflows/lequtis-engineering-gate.yml`

Each job is skipped unless `vars.LEQUTIS_AUTOMERGE_ENABLED == 'true'`. The shell step also exits when that value is not `true`. Those merge jobs are the only ones with `contents: write` for merging, and that permission is not granted while the jobs are skipped. The repair job still has `contents: write` so it can push a fix commit. It does not merge. The jobs that post receipts keep `pull-requests: write` because GitHub uses that permission for pull-request comments. Those jobs do not call `gh pr merge`.

## Re-enable

In the repository settings, under Actions variables, set:

- Name: `LEQUTIS_AUTOMERGE_ENABLED`
- Value: `true`

Unset, empty, or any other value leaves merging off. Delete the variable, or set it to anything other than `true`, to turn auto-merge off again.

Repository rules that GitHub itself enforces still apply. This switch does not change branch protection.
