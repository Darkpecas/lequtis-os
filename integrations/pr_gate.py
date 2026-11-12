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


def paths_from_name_status(lines: list[str]) -> list[str]:
    """Include both sides of a rename. `--name-only` hides the deleted path."""
    found: list[str] = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        found.extend(part for part in parts[1:] if part)
    return found


def destructive_markers(diff_text: str) -> list[str]:
    """Flag added operations, not the quoted denylist inside this module."""
    found: list[str] = []
    quoted = re.compile(r"""^\s*['"][^'"]+['"]\s*,?\s*$""")
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        content = line[1:]
        if quoted.match(content):
            continue
        for marker in DESTRUCTIVE_MARKERS:
            if marker in content and marker not in found:
                found.append(marker)
    return found


def review_status(reviews: list[dict[str, Any]], comments: list[dict[str, Any]], head_sha: str) -> str:
    """Codex counts only when its review or finding is for this head SHA."""
    reviewer = "chatgpt-codex-connector[bot]"

    def login(item: dict[str, Any]) -> str:
        user = item.get("user") or {}
        return str(user.get("login") or "")

    findings = [
        item for item in comments
        if login(item) == reviewer
        and item.get("commit_id") == head_sha
        and "codex-code-review-finding" in str(item.get("body") or "")
    ]
    if findings:
        return "findings"
    matched = [
        item for item in reviews
        if login(item) == reviewer and item.get("commit_id") == head_sha
    ]
    if matched:
        return "pass"
    return "missing"


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
    destructive = destructive_markers(diff_text)
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
        ["git", "diff", "--name-status", "--find-renames", f"{base}...{head}"],
        cwd=cwd, check=False, text=True, capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    return paths_from_name_status(proc.stdout.splitlines())


def git_diff(base: str, head: str) -> str:
    proc = subprocess.run(
        ["git", "diff", f"{base}...{head}"],
        check=False, text=True, capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    return proc.stdout


def _patch_id(diff: str) -> str:
    if not diff.strip():
        return ""
    ident = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=diff, text=True, capture_output=True, check=False,
    )
    if ident.returncode != 0 or not ident.stdout.strip():
        return ""
    return ident.stdout.split()[0]


def git_duplicate(base: str, head: str) -> bool:
    """True when this diff's patch-id equals one commit already on base.

    A diff without a commit header makes patch-id print an all-zero commit.
    That value is never treated as a match.
    """
    current = subprocess.run(
        ["git", "diff", f"{base}...{head}"],
        check=False, text=True, capture_output=True,
    )
    if current.returncode != 0:
        return False
    current_id = _patch_id(current.stdout)
    if not current_id:
        return False
    commits = subprocess.run(
        ["git", "rev-list", base, "-n", "40"],
        check=False, text=True, capture_output=True,
    )
    if commits.returncode != 0:
        return False
    for commit in commits.stdout.splitlines():
        if not commit or set(commit) == {"0"}:
            continue
        shown = subprocess.run(
            ["git", "show", "--format=", "--patch", commit],
            check=False, text=True, capture_output=True,
        )
        if shown.returncode != 0:
            continue
        if _patch_id(shown.stdout) == current_id:
            return True
    return False


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
