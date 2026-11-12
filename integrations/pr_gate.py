#!/usr/bin/env python3
"""Deterministic PR gate. This process is not the implementing agent.

It does not call a model, Hostinger, Hermes, or Telegram. A passing result is
a local policy decision. It is not live-infrastructure proof.

Auto-merge is allowed only for a non-empty, non-duplicate docs-only change
when tests passed, required CI checks passed, and the independent review
status is "pass". Credentials, schema migrations, workflows, Hermes/Hostinger
paths, and destructive *added* diff lines are refused.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.pr_auditor import (  # noqa: E402
    audit,
    resolve_independent_review,
)
from integrations.pr_workflow_receipt import build_receipt  # noqa: E402

EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"
HARMLESS_PREFIX = "docs/"


def decide(
    *,
    files: list[str],
    diff_text: str = "",
    body: str = "",
    tests_passed: bool,
    ai_review: str | None = None,
    duplicate: bool,
    test_attempts: int = 1,
    codex_status: str = "missing",
    required_checks_passed: bool = True,
    auditor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the merge decision.

    Prefer passing ``codex_status`` + letting the auditor resolve the review.
    Legacy callers may still pass ``ai_review`` directly.
    """
    auditor_verdict = auditor or audit(
        files=files, diff_text=diff_text, body=body, duplicate=duplicate
    )
    if ai_review is None:
        resolved = resolve_independent_review(
            codex_status=codex_status, auditor=auditor_verdict
        )
        ai_review = resolved["ai_review"]
        review_source = resolved["review_source"]
    else:
        review_source = "legacy_ai_review"
        resolved = {
            "ai_review": ai_review,
            "review_source": review_source,
            "codex_status": codex_status,
            "auditor_status": auditor_verdict.get("status"),
        }

    empty = len(files) == 0
    finding_codes = {f.get("code") for f in auditor_verdict.get("findings") or []}
    blocked: dict[str, list[str]] = {}
    for finding in auditor_verdict.get("findings") or []:
        if finding.get("code") in {
            "credentials",
            "schema_migration",
            "workflow_infrastructure",
            "infrastructure",
        }:
            blocked.setdefault(finding.get("detail", "?"), []).append(finding["code"])
    destructive = [
        f.get("detail", "")
        for f in auditor_verdict.get("findings") or []
        if f.get("code") == "destructive_operation"
    ]
    harmless = (
        bool(files)
        and all(path.startswith(HARMLESS_PREFIX) and path.endswith(".md") for path in files)
        and "credentials" not in finding_codes
        and "schema_migration" not in finding_codes
        and "workflow_infrastructure" not in finding_codes
        and "infrastructure" not in finding_codes
        and "destructive_operation" not in finding_codes
    )
    unverified_claim = "unverified_completion_claim" in finding_codes

    blocking: list[str] = []
    if empty or "empty_pr" in finding_codes:
        blocking.append("empty_pr")
    if duplicate or "duplicate_work" in finding_codes:
        blocking.append("duplicate_work")
    if blocked or destructive:
        blocking.append("blocked_change")
    if not tests_passed:
        blocking.append("tests_failed")
    if not required_checks_passed:
        blocking.append("required_checks_failed")
    if ai_review != "pass":
        blocking.append("independent_review_" + str(ai_review))
    if unverified_claim:
        blocking.append("unverified_completion_claim")
    if "acceptance_without_evidence" in finding_codes:
        blocking.append("acceptance_without_evidence")
    if not harmless:
        blocking.append("not_harmless")

    # Deduplicate while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for item in blocking:
        if item not in seen:
            seen.add(item)
            ordered.append(item)

    return {
        "evidence_label": EVIDENCE_LABEL,
        "live_hermes": False,
        "live_hostinger": False,
        "live_telegram": False,
        "empty": empty,
        "duplicate": duplicate,
        "files": files,
        "blocked": blocked,
        "destructive": destructive,
        "harmless": harmless,
        "tests_passed": tests_passed,
        "test_attempts": test_attempts,
        "required_checks_passed": required_checks_passed,
        "ai_review": ai_review,
        "review_source": review_source,
        "codex_status": resolved.get("codex_status", codex_status),
        "auditor_status": resolved.get("auditor_status", auditor_verdict.get("status")),
        "auditor_findings": auditor_verdict.get("findings") or [],
        "unverified_claim": unverified_claim,
        "blocking": ordered,
        "merge_allowed": not ordered,
        "repair": {
            "attempted": test_attempts > 1,
            "kind": "rerun_tests" if test_attempts > 1 else "none",
            "max_attempts": 2,
        },
    }


def git_files(base: str, head: str, cwd: str | None = None) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def git_diff(base: str, head: str, cwd: str | None = None) -> str:
    proc = subprocess.run(
        ["git", "diff", f"{base}...{head}"],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    return proc.stdout


def git_duplicate(base: str, head: str, cwd: str | None = None) -> bool:
    """True when this diff's stable patch-id already exists on base."""
    current = subprocess.run(
        ["git", "diff", f"{base}...{head}"],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )
    if current.returncode != 0 or not current.stdout.strip():
        return False
    ident = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=current.stdout,
        text=True,
        capture_output=True,
        check=False,
    )
    if ident.returncode != 0 or not ident.stdout.strip():
        return False
    current_id = ident.stdout.split()[0]
    log = subprocess.run(
        ["git", "log", base, "-n", "80", "-p", "--pretty=format:commit %H"],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )
    if log.returncode != 0 or not log.stdout.strip():
        return False
    scanned = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=log.stdout,
        text=True,
        capture_output=True,
        check=False,
    )
    if scanned.returncode != 0:
        return False
    return any(
        line.split()[0] == current_id
        for line in scanned.stdout.splitlines()
        if line.strip()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--body-file")
    parser.add_argument("--tests-passed", required=True, choices=("true", "false"))
    parser.add_argument(
        "--codex-status",
        choices=("pass", "findings", "missing"),
        default="missing",
    )
    parser.add_argument(
        "--ai-review",
        choices=("pass", "findings", "missing"),
        help="Legacy override; prefer --codex-status",
    )
    parser.add_argument("--test-attempts", type=int, default=1)
    parser.add_argument(
        "--required-checks-passed", choices=("true", "false"), default="true"
    )
    parser.add_argument("--pr-number", default="0")
    parser.add_argument("--head-sha", help="PR head commit SHA for receipt identity")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--out")
    parser.add_argument("--receipt-out")
    parser.add_argument("--auditor-out")
    args = parser.parse_args(argv)
    body = ""
    if args.body_file:
        body = open(args.body_file, encoding="utf-8").read()
    files = git_files(args.base, args.head)
    diff = git_diff(args.base, args.head)
    duplicate = git_duplicate(args.base, args.head)
    auditor_verdict = audit(
        files=files, diff_text=diff, body=body, duplicate=duplicate
    )
    if args.auditor_out:
        open(args.auditor_out, "w", encoding="utf-8").write(
            json.dumps(auditor_verdict, indent=2, sort_keys=True) + "\n"
        )
    decide_kwargs: dict[str, Any] = {
        "files": files,
        "diff_text": diff,
        "body": body,
        "tests_passed": args.tests_passed == "true",
        "duplicate": duplicate,
        "test_attempts": args.test_attempts,
        "codex_status": args.codex_status,
        "required_checks_passed": args.required_checks_passed == "true",
        "auditor": auditor_verdict,
    }
    if args.ai_review is not None:
        decide_kwargs["ai_review"] = args.ai_review
    verdict = decide(**decide_kwargs)
    head_sha = args.head_sha or subprocess.run(
        ["git", "rev-parse", args.head],
        check=False,
        text=True,
        capture_output=True,
    ).stdout.strip() or args.head
    receipt = build_receipt(
        pr_number=args.pr_number,
        head_sha=head_sha,
        base_ref=args.base,
        gate_verdict=verdict,
        auditor=auditor_verdict,
        required_checks={"passed": args.required_checks_passed == "true"},
        run_url=args.run_url or None,
    )
    text = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
    if args.receipt_out:
        open(args.receipt_out, "w", encoding="utf-8").write(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        )
    sys.stdout.write(text)
    return 0 if verdict["merge_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
