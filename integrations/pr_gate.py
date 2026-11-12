#!/usr/bin/env python3
"""Deterministic PR gate. This process is not the implementing agent.

It does not call a model, Hostinger, Hermes, or Telegram. A passing result is
a local policy decision. It is not live-infrastructure proof.

Auto-merge is allowed only for a non-empty, non-duplicate docs-only change
when tests passed and the independent review status is "pass". Credentials,
schema migrations, workflows, Hermes/Hostinger paths, and destructive diff
text are refused.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"

BLOCK_RULES = (
    ("credentials", (".env", "credential", "secret", "password", ".pem")),
    ("schema_migration", ("database/migrations/",)),
    ("workflow_infrastructure", (".github/",)),
    ("infrastructure", ("runtime/hermes", "hostinger")),
)

DESTRUCTIVE_MARKERS = (
    "DROP TABLE",
    "DROP DATABASE",
    "hosting_websites_delete",
    "vps_virtual-machines_recreate",
    "rm -rf /",
)

HARMLESS_PREFIX = "docs/"
CODEX_BOT = "chatgpt-codex-connector[bot]"
CODEX_STATE_MARKER = "codex-review-state:v1 "


def _login(item: dict[str, Any]) -> str:
    user = item.get("user") or {}
    return str(user.get("login") or "")


def codex_review_status(
    reviews: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
    head_sha: str,
) -> str:
    """Read Codex from pull reviews and from its issue-comment summary.

    Codex posts the completed summary on the issue thread, not as a pull
    review. A summary counts only when its commit SHA is this head.
    Findings outrank a pass.
    """
    findings = [
        item for item in review_comments
        if _login(item) == CODEX_BOT
        and item.get("commit_id") == head_sha
        and "codex-code-review-finding" in str(item.get("body") or "")
    ]
    if findings:
        return "findings"
    for item in issue_comments:
        if _login(item) != CODEX_BOT:
            continue
        status = _status_from_summary(str(item.get("body") or ""), head_sha)
        if status == "findings":
            return "findings"
        if status == "pass":
            return "pass"
    matched = [
        item for item in reviews
        if _login(item) == CODEX_BOT and item.get("commit_id") == head_sha
    ]
    if matched:
        return "pass"
    return "missing"


def _status_from_summary(body: str, head_sha: str) -> str:
    if CODEX_STATE_MARKER not in body:
        return "missing"
    start = body.index(CODEX_STATE_MARKER) + len(CODEX_STATE_MARKER)
    end = body.find("-->", start)
    raw = body[start:end].strip() if end != -1 else ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "missing"
    review = data.get("code_review") or {}
    if review.get("commit_sha") != head_sha or review.get("status") != "completed":
        return "missing"
    if review.get("has_any_findings") or review.get("has_unresolved_findings"):
        return "findings"
    return "pass"


def _blocked(path: str) -> list[str]:
    low = path.lower()
    reasons = []
    for reason, needles in BLOCK_RULES:
        if any(needle in low for needle in needles) or low.endswith(".key"):
            reasons.append(reason)
    return reasons


def decide(
    *,
    files: list[str],
    diff_text: str = "",
    body: str = "",
    tests_passed: bool,
    ai_review: str,
    duplicate: bool,
    test_attempts: int = 1,
) -> dict[str, Any]:
    """Return the merge decision. ai_review is pass, findings, or missing."""
    empty = len(files) == 0
    blocked: dict[str, list[str]] = {}
    for path in files:
        reasons = _blocked(path)
        if reasons:
            blocked[path] = reasons
    destructive = [marker for marker in DESTRUCTIVE_MARKERS if marker in diff_text]
    harmless = bool(files) and all(
        path.startswith(HARMLESS_PREFIX) and path.endswith(".md") for path in files
    ) and not blocked and not destructive
    unverified_claim = bool(re.search(r"\bVERIFIED\b", body or "")) and not (
        "https://github.com/" in (body or "") or "evidence/" in (body or "")
    )
    blocking: list[str] = []
    if empty:
        blocking.append("empty_pr")
    if duplicate:
        blocking.append("duplicate_work")
    if blocked or destructive:
        blocking.append("blocked_change")
    if not tests_passed:
        blocking.append("tests_failed")
    if ai_review != "pass":
        blocking.append("independent_review_" + ai_review)
    if unverified_claim:
        blocking.append("unverified_completion_claim")
    if not harmless:
        blocking.append("not_harmless")
    # not_harmless is expected for code PRs; do not also call them empty.
    merge_allowed = not blocking
    if not harmless and "not_harmless" in blocking and len(blocking) > 1:
        pass
    return {
        "evidence_label": EVIDENCE_LABEL,
        "live_hermes": False,
        "live_hostinger": False,
        "empty": empty,
        "duplicate": duplicate,
        "files": files,
        "blocked": blocked,
        "destructive": destructive,
        "harmless": harmless,
        "tests_passed": tests_passed,
        "test_attempts": test_attempts,
        "ai_review": ai_review,
        "unverified_claim": unverified_claim,
        "blocking": blocking,
        "merge_allowed": merge_allowed,
        "repair": {
            "attempted": test_attempts > 1,
            "kind": "rerun_tests" if test_attempts > 1 else "none",
            "max_attempts": 2,
        },
    }


def git_files(base: str, head: str, cwd: str | None = None) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        cwd=cwd, check=False, text=True, capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def git_diff(base: str, head: str) -> str:
    proc = subprocess.run(
        ["git", "diff", f"{base}...{head}"],
        check=False, text=True, capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    return proc.stdout


def git_duplicate(base: str, head: str) -> bool:
    """True when this diff's stable patch-id already exists on base."""
    current = subprocess.run(
        ["git", "diff", f"{base}...{head}"],
        check=False, text=True, capture_output=True,
    )
    if current.returncode != 0 or not current.stdout.strip():
        return False
    ident = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=current.stdout, text=True, capture_output=True, check=False,
    )
    if ident.returncode != 0 or not ident.stdout.strip():
        return False
    current_id = ident.stdout.split()[0]
    log = subprocess.run(
        ["git", "log", base, "-n", "80", "-p", "--pretty=format:commit %H"],
        check=False, text=True, capture_output=True,
    )
    if log.returncode != 0 or not log.stdout.strip():
        return False
    scanned = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=log.stdout, text=True, capture_output=True, check=False,
    )
    if scanned.returncode != 0:
        return False
    return any(line.split()[0] == current_id for line in scanned.stdout.splitlines() if line.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--body-file")
    parser.add_argument("--tests-passed", required=True, choices=("true", "false"))
    parser.add_argument("--ai-review", required=True, choices=("pass", "findings", "missing"))
    parser.add_argument("--test-attempts", type=int, default=1)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    body = ""
    if args.body_file:
        body = open(args.body_file, encoding="utf-8").read()
    files = git_files(args.base, args.head)
    diff = git_diff(args.base, args.head)
    verdict = decide(
        files=files,
        diff_text=diff,
        body=body,
        tests_passed=args.tests_passed == "true",
        ai_review=args.ai_review,
        duplicate=git_duplicate(args.base, args.head),
        test_attempts=args.test_attempts,
    )
    text = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
    sys.stdout.write(text)
    return 0 if verdict["merge_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
