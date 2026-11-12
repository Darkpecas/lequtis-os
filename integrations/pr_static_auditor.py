#!/usr/bin/env python3
"""Independent static PR auditor.

This process is not the implementing agent and does not call a model.
It is a subordinate deterministic check for LeQutis. A pass is local proof
only: LOCAL PROOF, NOT LIVE VPS VERIFIED.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"

SECRET_PATTERNS = (
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)secret\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY"),
    re.compile(r"(?i)password\s*[:=]\s*['\"][^'\"]{8,}"),
)

ACCEPTANCE_MARKERS = (
    re.compile(r"(?i)\bacceptance\b"),
    re.compile(r"(?i)\bvalidated?\b"),
    re.compile(r"(?i)\btests?\b"),
    re.compile(r"(?i)\bevidence\b"),
)


def _added_lines_by_file(diff_text: str) -> dict[str, str]:
    """Map path -> concatenated added line text from a unified diff."""
    current = ""
    buckets: dict[str, list[str]] = {}
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            buckets.setdefault(current, [])
            continue
        if line.startswith("+") and not line.startswith("+++") and current:
            buckets.setdefault(current, []).append(line[1:])
    return {path: "\n".join(lines) for path, lines in buckets.items()}


def audit(
    *,
    files: list[str],
    diff_text: str = "",
    body: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Return static findings. status is pass or findings."""
    findings: list[dict[str, str]] = []
    if not files:
        findings.append(
            {
                "code": "empty_diff",
                "severity": "high",
                "message": "Pull request has commits or metadata but zero changed files.",
            }
        )
    # Only added lines outside tests/ count. Fixture source must not trip the gate.
    for path, added in _added_lines_by_file(diff_text).items():
        if path.startswith("tests/"):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(added):
                findings.append(
                    {
                        "code": "secret_like_diff",
                        "severity": "high",
                        "message": "Diff matches a secret-like pattern; refuse auto-merge.",
                    }
                )
                break
        else:
            continue
        break
    # Synthetic/unit-test callers may pass diff_text without +++ headers.
    if diff_text and not _added_lines_by_file(diff_text):
        added_only = "\n".join(
            line[1:]
            for line in diff_text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        for pattern in SECRET_PATTERNS:
            if pattern.search(added_only or diff_text):
                findings.append(
                    {
                        "code": "secret_like_diff",
                        "severity": "high",
                        "message": "Diff matches a secret-like pattern; refuse auto-merge.",
                    }
                )
                break
    body_text = body or ""
    if re.search(r"\bVERIFIED\b", body_text) and not (
        "https://github.com/" in body_text or "evidence/" in body_text
    ):
        findings.append(
            {
                "code": "unverified_claim",
                "severity": "medium",
                "message": "Body claims VERIFIED without a GitHub URL or evidence/ path.",
            }
        )
    claims_done = bool(
        re.search(r"(?i)\b(complete|done|finished|shipped)\b", title + "\n" + body_text)
    )
    has_acceptance = any(p.search(body_text) for p in ACCEPTANCE_MARKERS)
    if claims_done and files and not has_acceptance:
        findings.append(
            {
                "code": "missing_acceptance_evidence",
                "severity": "medium",
                "message": "Completion language without acceptance/tests/evidence markers.",
            }
        )
    if any(path.startswith("database/migrations/") for path in files):
        findings.append(
            {
                "code": "production_migration",
                "severity": "high",
                "message": "Schema migration paths require human merge authority.",
            }
        )
    if any(path.startswith(".github/") for path in files):
        findings.append(
            {
                "code": "workflow_change",
                "severity": "high",
                "message": "GitHub Actions / workflow changes are not auto-merged.",
            }
        )
    status = "pass" if not findings else "findings"
    return {
        "evidence_label": EVIDENCE_LABEL,
        "auditor": "lequtis-pr-static-auditor",
        "independent_of_implementer": True,
        "live_hermes": False,
        "live_hostinger": False,
        "live_telegram": False,
        "status": status,
        "findings": findings,
        "files_reviewed": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files-json", help="JSON array of changed paths")
    parser.add_argument("--diff-file")
    parser.add_argument("--body-file")
    parser.add_argument("--title", default="")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    files: list[str] = []
    if args.files_json:
        parsed = json.loads(args.files_json)
        if not isinstance(parsed, list):
            raise SystemExit("--files-json must be a JSON array")
        files = [str(item) for item in parsed]
    diff_text = open(args.diff_file, encoding="utf-8").read() if args.diff_file else ""
    body = open(args.body_file, encoding="utf-8").read() if args.body_file else ""
    verdict = audit(files=files, diff_text=diff_text, body=body, title=args.title)
    text = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
    sys.stdout.write(text)
    return 0 if verdict["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
