#!/usr/bin/env python3
"""Independent PR auditor — separate process from the implementing agent.

This auditor does not call a model, Hostinger, Hermes, or Telegram. It inspects
the proposed diff and PR body against fail-closed policy. Its verdict is a
local policy review, not live-infrastructure proof.

Codex/ChatGPT review remains an optional second independent AI reviewer when
present. This module always runs so empty, duplicate, credential, destructive,
and unverified-claim cases are never left unchecked when the AI bot is absent.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"

# Path substrings that never auto-merge and always raise findings.
BLOCK_PATH_NEEDLES = (
    (".env", "credentials"),
    ("credential", "credentials"),
    ("secret", "credentials"),
    ("password", "credentials"),
    (".pem", "credentials"),
    ("database/migrations/", "schema_migration"),
    (".github/", "workflow_infrastructure"),
    ("runtime/hermes", "infrastructure"),
    ("hostinger", "infrastructure"),
)

DESTRUCTIVE_NEEDLES = (
    ("DROP TABLE", re.compile(r"\bDROP\s+TABLE\b", re.I)),
    ("DROP DATABASE", re.compile(r"\bDROP\s+DATABASE\b", re.I)),
    ("hosting_websites_delete", re.compile(r"hosting_websites_delete")),
    ("vps_virtual-machines_recreate", re.compile(r"vps_virtual-machines_recreate")),
    ("rm -rf /", re.compile(r"\brm\s+-rf\s+/")),
)

SECRET_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_KEY)[A-Z0-9_]*\s*=\s*['\"]?[^'\"\s]+",
)

_STRING_LITERAL = re.compile(r"(['\"])(?:\\.|(?!\1).)*\1")


def added_lines(diff_text: str) -> list[str]:
    """Return newly added file content lines (without the leading '+')."""
    out: list[str] = []
    for line in (diff_text or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            out.append(line[1:])
    return out


def _without_string_literals(line: str) -> str:
    """Remove quoted literals so marker lists in source are not false positives."""
    return _STRING_LITERAL.sub("", line)


def audit(
    *,
    files: list[str],
    diff_text: str = "",
    body: str = "",
    duplicate: bool = False,
) -> dict[str, Any]:
    """Return an independent audit verdict.

    status is pass | findings. findings is a list of machine-readable codes.
    """
    findings: list[dict[str, str]] = []
    added = added_lines(diff_text)

    if not files:
        findings.append({"code": "empty_pr", "detail": "zero net changed files"})

    if duplicate:
        findings.append(
            {"code": "duplicate_work", "detail": "stable patch-id already on base"}
        )

    for path in files:
        low = path.lower()
        if low.endswith(".key"):
            findings.append({"code": "credentials", "detail": path})
            continue
        for needle, code in BLOCK_PATH_NEEDLES:
            if needle in low:
                findings.append({"code": code, "detail": path})
                break

    for line in added:
        stripped = _without_string_literals(line)
        for label, pattern in DESTRUCTIVE_NEEDLES:
            if pattern.search(stripped):
                findings.append({"code": "destructive_operation", "detail": label})
        if SECRET_ASSIGNMENT.search(stripped):
            findings.append(
                {
                    "code": "credentials",
                    "detail": "secret-like assignment on an added line",
                }
            )

    unverified_claim = bool(re.search(r"\bVERIFIED\b", body or "")) and not (
        "https://github.com/" in (body or "") or "evidence/" in (body or "")
    )
    if unverified_claim:
        findings.append(
            {
                "code": "unverified_completion_claim",
                "detail": "VERIFIED without github URL or evidence/ path",
            }
        )

    # Acceptance criteria must name at least one concrete check when claiming done.
    claims_complete = bool(
        re.search(r"\b(COMPLETE|DONE|MERGED|SHIPPED)\b", body or "", re.I)
    )
    has_evidence_pointer = (
        "https://github.com/" in (body or "")
        or "evidence/" in (body or "")
        or "actions/runs/" in (body or "")
    )
    if claims_complete and not has_evidence_pointer:
        findings.append(
            {
                "code": "acceptance_without_evidence",
                "detail": "completion claim without evidence pointer",
            }
        )

    # Deduplicate by code+detail
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for item in findings:
        key = (item["code"], item["detail"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    status = "pass" if not unique else "findings"
    return {
        "schema": "lequtis.pr_auditor.v1",
        "evidence_label": EVIDENCE_LABEL,
        "reviewer": "pr_auditor",
        "independent_of_implementer": True,
        "status": status,
        "findings": unique,
        "files_reviewed": list(files),
        "live_hermes": False,
        "live_hostinger": False,
    }


def resolve_independent_review(
    *,
    codex_status: str,
    auditor: dict[str, Any],
) -> dict[str, Any]:
    """Combine Codex (when present) with the always-on deterministic auditor.

    Codex findings always win (block). Codex pass requires auditor pass too.
    When Codex is missing, the auditor alone supplies the independent review.
    """
    if codex_status not in {"pass", "findings", "missing"}:
        raise ValueError("invalid codex_status")
    auditor_status = auditor.get("status")
    if auditor_status == "findings":
        return {
            "ai_review": "findings",
            "review_source": "auditor" if codex_status == "missing" else "codex+auditor",
            "codex_status": codex_status,
            "auditor_status": auditor_status,
        }
    if codex_status == "findings":
        return {
            "ai_review": "findings",
            "review_source": "codex",
            "codex_status": codex_status,
            "auditor_status": auditor_status,
        }
    if codex_status == "pass":
        return {
            "ai_review": "pass",
            "review_source": "codex+auditor",
            "codex_status": codex_status,
            "auditor_status": auditor_status,
        }
    # Codex missing — auditor is the independent reviewer.
    return {
        "ai_review": "pass" if auditor_status == "pass" else "findings",
        "review_source": "auditor_fallback",
        "codex_status": codex_status,
        "auditor_status": auditor_status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files-json", help="JSON list of changed files")
    parser.add_argument("--diff-file")
    parser.add_argument("--body-file")
    parser.add_argument("--duplicate", choices=("true", "false"), default="false")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    files = json.loads(args.files_json) if args.files_json else []
    diff_text = open(args.diff_file, encoding="utf-8").read() if args.diff_file else ""
    body = open(args.body_file, encoding="utf-8").read() if args.body_file else ""
    verdict = audit(
        files=files,
        diff_text=diff_text,
        body=body,
        duplicate=args.duplicate == "true",
    )
    text = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
    sys.stdout.write(text)
    return 0 if verdict["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
