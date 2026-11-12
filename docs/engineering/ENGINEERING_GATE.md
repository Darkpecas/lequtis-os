# Engineering gate

> **SECURITY HOLD — 2026-11-12:** Automated merges and automated repair pushes are disabled in this repository's GitHub Actions workflows. The former auto-merge criteria below are retained as historical policy/decision evidence, **not as an operating merge authorization**. Assessment is read-only; receipts are uploaded as artifacts. Every merge requires an explicitly authorized manual action and separate review. Do not re-enable auto-merge or credentialed PR-head code until independent adversarial verification of a trusted base-controlled authority, symlink and file-mode checks, full check pagination, and reviewer provenance. This change does not verify live Hostinger/Hermes.


LeQutis decides. The independent reviewer, GitHub Actions, Hermes, and Telegram are subordinate resources. None of them is a merge authority. A review comment is not an approval.

LOCAL PROOF, NOT LIVE VPS VERIFIED. A green run does not prove live Hostinger or a live Hermes route.

## Genuinely necessary

Genuinely necessary means a non-empty net diff, no duplicate of existing code or an open pull request, and a reviewer judgment that the diff is in scope for the stated acceptance criteria.

1. The pull request has a non-empty net diff.
2. It has no duplicate of existing code or of an open pull request.
3. The independent reviewer judges the diff in scope for the stated acceptance criteria.

Genuinely necessary is required before auto-merge. It is not enough on its own. Auto-merge also needs the disposable test check, the independent review check, evidence for every acceptance criterion, no blocking findings, and a clear denylist. Repository rules that GitHub itself enforces still apply.

## Denylist

A match forces the `needs-human` label and blocks auto-merge.

Path classes: secret material (`.env`, secret, credential, password, `.pem`, `.key`, `id_rsa`), database migrations and `database/schema.sql`, destructive script names, and `infra/`, `terraform/`, `deploy/`, plus Terraform filenames.

Keyword classes, on added diff lines: a SQL drop of a table or database, a recursive forced shell removal, a Terraform destroy, or a private-key block.

Unverified infrastructure is held the same way: `.github/`, the gate modules, this document, `docs/engineering/PR_GATE.md`, and the gate tests. Those files decide merge behavior, so this gate does not merge its own policy.

## Independent review

`.github/workflows/lequtis-independent-review.yml` is a separate workflow. Its token can read the repository and post a pull-request comment. It cannot write code. The model payload contains the unified diff and the acceptance criteria extracted from the pull request body. The rest of the body is not sent.

The required Actions secret is `LEQUTIS_REVIEWER_API_KEY`. If that secret is absent, the review fails closed, the check fails, and the gate does not merge. The comment names that secret. The value is never printed.

The default provider is Google Gemini's free tier, not a paid API. `LEQUTIS_REVIEWER_API_KEY` is sent only as the `x-goog-api-key` header to `generativelanguage.googleapis.com`. The default model is `gemini-3.8-flash`, whose input and output Google lists as free of charge on the free tier. `gemini-2.0-flash` is not the default. A non-Gemini URL is refused unless `LEQUTIS_REVIEWER_ALLOW_PAID=1`.

## Acceptance evidence

The body needs `task_id:` (or a closing keyword with an issue number) and a heading `## Acceptance criteria` with one bullet per criterion. A criterion is met only from evidence the gate can point at:

- the bullet names a path that this pull request changes
- "docs-only" and every file is markdown under `docs/`
- "no credentials" and the denylist is clear
- "tests pass" and the `verify` check succeeded
- "independent review passes" and the reviewer returned pass, in scope

An unchecked box or the word VERIFIED without a GitHub URL or an `evidence/` path does not count.

## Repair

At most two automatic repair attempts. A repair is recorded with the failing log excerpt and the fix commit. The only automatic edit is a missing trailing newline on a changed text file that is not denylisted. Anything else is recorded as not recoverable and is not retried as a code change. The repair job is the only place this gate pushes a commit.

## Receipt

One JSON document, schema `lequtis.engineering_receipt.v1`, is uploaded as an artifact and written on the pull request. It carries the task id, pull request URL, head SHA, review verdict and findings, check name, conclusion, and run URL, merge decision and reason, merge commit SHA, and read-back against `main`. Repair records and the Hermes delivery result are in the same object.

## Hermes and Telegram

`integrations/hermes_notify.py` uses the existing disposable Hermes route. That route has no Telegram sender and no tunnel transport. Delivery degrades. The receipt says `telegram_delivered: false` and `live_host: false`.

Presence is recorded only as present or absent for `LEQUTIS_TUNNEL_ID`, `LEQUTIS_TUNNEL_API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID`. This repository does not reference a Telegram secret. No replacement bot is created.

## Preflight observed 2026-11-12

This token could not list Actions secret names or values (`GET /repos/Darkpecas/lequtis-os/actions/secrets` returned HTTP 403). Admin permission was false. `allow_auto_merge` was already true. Branch `main` was not protected, required status checks were off, and repository rulesets were empty. Enabling protection or required checks needs the repository admin, Alan Gibson (GitHub login Darkpecas). The workflow does not change those settings.

## `.git22` pull request 4

`Darkpecas/.git22` was not visible here. The public page, the REST repository call, GraphQL, and `git ls-remote` all returned not found. Public events and the visible repository list do not include it. No commit SHA and no diff were recovered, so none were ported. `Darkpecas/lequtis-os` pull request 4 is a different change: it ports `.git22` pull request 5 and is already on `main`.

An empty net diff with commits still listed is `empty_pr`. A local fixture of six commits that edit a file and restore it is in `tests/test_engineering_gate.py`. Those SHAs belong to the fixture, not to `.git22`.
