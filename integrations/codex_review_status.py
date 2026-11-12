#!/usr/bin/env python3
"""Read independent Codex review status for the current PR head.

This is not the implementing agent. It only interprets GitHub API JSON already
fetched by the caller, or fetches via `gh api` when --fetch is set.

LOCAL PROOF, NOT LIVE VPS VERIFIED.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

BOT = "chatgpt-codex-connector[bot]"


def _api(path: str) -> Any:
    proc = subprocess.run(
        ["gh", "api", path],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def status_from_payloads(
    *,
    head_sha: str,
    issue_comments: list[dict[str, Any]] | None,
    pull_comments: list[dict[str, Any]] | None,
    reviews: list[dict[str, Any]] | None,
) -> str:
    """Return pass, findings, or missing for the given head SHA."""
    issue_comments = issue_comments or []
    pull_comments = pull_comments or []
    reviews = reviews or []
    summary_parts = [
        c.get("body") or ""
        for c in issue_comments
        if c.get("user", {}).get("login") == BOT and head_sha in (c.get("body") or "")
    ]
    finding_parts = [
        c.get("body") or ""
        for c in pull_comments
        if c.get("user", {}).get("login") == BOT
        and (c.get("original_commit_id") == head_sha or c.get("commit_id") == head_sha)
    ]
    review_count = sum(
        1
        for review in reviews
        if review.get("user", {}).get("login") == BOT and review.get("commit_id") == head_sha
    )
    all_text = "\n".join(summary_parts + finding_parts)
    summary = "\n".join(summary_parts)
    if "codex-code-review-finding" in all_text:
        return "findings"
    if (
        "codex-review-state:v1" in summary
        and f'"commit_sha":"{head_sha}"' in summary
        and '"status":"completed"' in summary
    ):
        return "findings" if '"has_any_findings":true' in summary else "pass"
    if review_count and "codex-code-review-finding" not in all_text:
        return "pass"
    return "missing"


def fetch_status(repo: str, pr: str, head_sha: str) -> str:
    return status_from_payloads(
        head_sha=head_sha,
        issue_comments=_api(f"repos/{repo}/issues/{pr}/comments"),
        pull_comments=_api(f"repos/{repo}/pulls/{pr}/comments"),
        reviews=_api(f"repos/{repo}/pulls/{pr}/reviews"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument(
        "--issue-comments-file",
        help="Optional JSON file for offline tests instead of gh api",
    )
    parser.add_argument("--pull-comments-file")
    parser.add_argument("--reviews-file")
    args = parser.parse_args(argv)
    if args.issue_comments_file or args.pull_comments_file or args.reviews_file:
        def load(path: str | None) -> list[dict[str, Any]]:
            if not path:
                return []
            data = json.loads(open(path, encoding="utf-8").read())
            return data if isinstance(data, list) else []

        result = status_from_payloads(
            head_sha=args.head_sha,
            issue_comments=load(args.issue_comments_file),
            pull_comments=load(args.pull_comments_file),
            reviews=load(args.reviews_file),
        )
    else:
        result = fetch_status(args.repo, args.pr, args.head_sha)
    sys.stdout.write(result + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
