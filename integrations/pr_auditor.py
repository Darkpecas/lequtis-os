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
    ("/secrets/", "credentials"),
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

_STRING_LITERAL = re.compile(r"(['\"`])(?:\\.|(?!\1).)*\1")
_SECRET_NAME = re.compile(r"(SECRET|TOKEN|PASSWORD|API_KEY)")
_SECRET_LINE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$"
)


def added_lines(diff_text: str) -> list[str]:
    """Return newly added file content lines (without the leading '+')."""
    out: list[str] = []
    for line in (diff_text or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            out.append(line[1:])
    return out


def _without_string_literals(line: str) -> str:
    """Remove quoted/backtick literals so docs and marker lists are not flagged."""
    return _STRING_LITERAL.sub("", line)


def _is_doc_or_marker_definition(line: str, pattern: re.Pattern[str]) -> bool:
    """True when a destructive match is documentation or a marker list, not code."""
    if re.search(r"(?i)\b(DESTRUCTIVE[_A-Z0-9]*|NEEDLES|MARKERS|BLOCK_RULES)\s*=", line):
        return True
    if re.match(r"^\s*[\'\"`].*[\'\"`],?\s*$", line):
        return True
    without = _without_string_literals(line)
    if pattern.search(without):
        return False
    # Match lived only inside quotes/backticks. Still flag shell/SQL wrappers.
    if re.search(r"(?i)\b(bash|sh|zsh|cmd|powershell|subprocess|os\.system|popen|exec|sql)\b", without):
        return False
    return True


def _destructive_hits(line: str) -> list[str]:
    hits: list[str] = []
    for label, pattern in DESTRUCTIVE_NEEDLES:
        if not pattern.search(line):
            continue
        if _is_doc_or_marker_definition(line, pattern):
            continue
        hits.append(label)
    return hits


def _looks_like_secret_assignment(line: str) -> bool:
    """True only for literal credential assignments, not code/docs/Actions refs."""
    match = _SECRET_LINE.match(line)
    if not match:
        return False
    name, value = match.group(1), match.group(2).strip()
    if not _SECRET_NAME.search(name):
        return False
    # GitHub Actions expressions and function calls are not pasted secrets.
    if value.startswith("${{") or value.startswith("$("):
        return False
    if re.match(r"^[A-Za-z_][A-Za-z0-9_\.]*\(", value):
        return False
    if value in {'""', "''", "``", "None", "null", "true", "false", "{}", "[]"}:
        return False
    if (value.startswith("'") or value.startswith('"') or value.startswith("`")) and len(
        value
    ) > 3:
        inner = value[1:-1] if len(value) >= 2 else ""
        if inner.startswith("${{") or inner in {"", "...", "redacted", "<redacted>"}:
            return False
        return True
    # Opaque unquoted token long enough to be a pasted secret.
    return bool(re.match(r"^[A-Za-z0-9_\-+/=]{16,}$", value))


def _claim_body(body: str) -> str:
    """Strip the standard evidence label so it does not trip VERIFIED detection."""
    text = body or ""
    text = text.replace(EVIDENCE_LABEL, "")
    text = re.sub(r"\bNOT\s+(?:LIVE\s+)?(?:VPS\s+)?VERIFIED\b", "", text, flags=re.I)
    return text


def _has_evidence_pointer(body: str) -> bool:
    text = body or ""
    return (
        "https://github.com/" in text
        or "evidence/" in text
        or "actions/runs/" in text
    )


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
        if low.endswith(".key") or low.endswith(".pem"):
            findings.append({"code": "credentials", "detail": path})
            continue
        if low.endswith(".env") or low.endswith(".env.local") or "/.env." in low:
            findings.append({"code": "credentials", "detail": path})
            continue
        for needle, code in BLOCK_PATH_NEEDLES:
            if needle in low:
                findings.append({"code": code, "detail": path})
                break

    for line in added:
        for label in _destructive_hits(line):
            findings.append({"code": "destructive_operation", "detail": label})
        if _looks_like_secret_assignment(line):
            findings.append(
                {
                    "code": "credentials",
                    "detail": "secret-like assignment on an added line",
                }
            )

    claim_body = _claim_body(body)
    has_evidence = _has_evidence_pointer(body)
    unverified_claim = bool(re.search(r"\bVERIFIED\b", claim_body)) and not has_evidence
    if unverified_claim:
        findings.append(
            {
                "code": "unverified_completion_claim",
                "detail": "VERIFIED without github URL or evidence/ path",
            }
        )

    # Uppercase status tokens only. Prose like "Completes" / "merged" does not match.
    claims_complete = bool(re.search(r"\b(COMPLETE|DONE|SHIPPED)\b", claim_body))
    if claims_complete and not has_evidence:
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
