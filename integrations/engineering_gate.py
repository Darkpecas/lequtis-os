#!/usr/bin/env python3
"""LeQutis engineering gate. External reviewers are subordinate.

Genuinely necessary means a non-empty net diff, no duplicate of existing code
or an open pull request, and a reviewer judgment that the diff is in scope for
the stated acceptance criteria. That is necessary for auto-merge and not
sufficient: the denylist, checks, and acceptance evidence can still hold it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

SCHEMA = "lequtis.engineering_receipt.v1"
RECEIPT_MARKER = "<!-- lequtis-engineering-receipt v1 -->"
REVIEW_MARKER = "lequtis-independent-review v1"
LABEL = "needs-human"
MAX_REPAIRS = 2
SECRET_NAMES = (
    "LEQUTIS_REVIEWER_API_KEY",
    "LEQUTIS_TUNNEL_ID",
    "LEQUTIS_TUNNEL_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)
REQUIRED_CHECKS = ("verify", "review")

PATH_RULES = (
    ("secret_material", re.compile(
        r"(^|/)\.env($|\.|/)|(^|/)[^/]*secret[^/]*$|(^|/)[^/]*credential[^/]*$|"
        r"(^|/)[^/]*password[^/]*$|\.pem$|\.key$|(^|/)id_rsa$",
        re.I,
    )),
    ("migration", re.compile(r"(^|/)migrations(/|$)|(^|/)[^/]*migration[^/]*$|database/schema\.sql$", re.I)),
    ("destructive_script", re.compile(r"(^|/)[^/]*destroy[^/]*$", re.I)),
    ("infrastructure", re.compile(r"(^|/)(infra|terraform|deploy)(/|$)|\.tf$|\.tfvars$", re.I)),
    ("unverified_infrastructure", re.compile(
        r"^\.github/|"
        r"^integrations/(pr_gate|engineering_gate|independent_reviewer|hermes_notify)\.py$|"
        r"^docs/engineering/(ENGINEERING_GATE|PR_GATE)\.md$|"
        r"^tests/test_(engineering_gate|independent_reviewer|pr_gate)\.py$"
    )),
)
KEYWORD_RULES = (
    ("destructive_sql", re.compile(r"\bDROP\s+(TABLE|DATABASE)\b", re.I)),
    ("destructive_shell", re.compile(r"\brm\s+-rf\b")),
    ("destructive_terraform", re.compile(r"\bterraform\s+destroy\b", re.I)),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)


def secret_presence(names: tuple[str, ...] = SECRET_NAMES) -> dict[str, str]:
    return {name: "present" if os.environ.get(name) else "absent" for name in names}


def scrub_text(text: str) -> str:
    cleaned = text or ""
    for name in SECRET_NAMES:
        value = os.environ.get(name) or ""
        if len(value) >= 8:
            cleaned = cleaned.replace(value, "<redacted>")
    return cleaned


def scrub_obj(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, list):
        return [scrub_obj(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub_obj(item) for key, item in value.items()}
    return value


def path_reasons(path: str) -> list[str]:
    reasons = []
    for reason, pattern in PATH_RULES:
        if pattern.search(path):
            reasons.append(reason)
    return reasons


def keyword_reasons(diff_text: str) -> list[str]:
    added = []
    for line in (diff_text or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    text = "\n".join(added)
    return [name for name, pattern in KEYWORD_RULES if pattern.search(text)]


def risk_report(files: list[str], diff_text: str = "") -> dict[str, Any]:
    matches = []
    for path in files:
        reasons = path_reasons(path)
        if reasons:
            matches.append({"path": path, "reasons": reasons})
    for reason in keyword_reasons(diff_text):
        matches.append({"path": "*", "reasons": [reason]})
    return {"needs_human": bool(matches), "matches": matches}


def parse_task(body: str) -> dict[str, Any]:
    text = body or ""
    task_id = None
    match = re.search(r"(?im)^task_id:\s*(\S+)\s*$", text)
    if match:
        task_id = match.group(1)
    if task_id is None:
        match = re.search(r"(?im)\b(?:fix(?:es)?|close[sd]?|resolve[sd]?)\s+#(\d+)\b", text)
        if match:
            task_id = "github-issue-" + match.group(1)
    criteria: list[dict[str, Any]] = []
    parts = re.split(r"(?im)^##\s+acceptance criteria\s*$", text, maxsplit=1)
    if len(parts) == 2:
        section = re.split(r"(?m)^##\s+", parts[1], maxsplit=1)[0]
        for raw in section.splitlines():
            line = raw.strip()
            if not line.startswith(("-", "*")):
                continue
            item = re.sub(r"^[-*]\s*", "", line).strip()
            unchecked = item.startswith("[ ]")
            item = re.sub(r"^\[[ xX]\]\s*", "", item).strip()
            if item:
                criteria.append({"text": item, "unchecked": unchecked})
    return {"task_id": task_id, "criteria": criteria}


def unverified_claim(body: str) -> bool:
    if not re.search(r"\bVERIFIED\b", body or ""):
        return False
    return "https://github.com/" not in (body or "") and "evidence/" not in (body or "")


def verify_acceptance(
    criteria: list[dict[str, Any]],
    files: list[str],
    *,
    risk_clear: bool,
    tests_passed: bool,
    review_passed: bool,
) -> list[dict[str, Any]]:
    docs_only = bool(files) and all(
        path.startswith("docs/") and path.endswith(".md") for path in files
    )
    results = []
    for item in criteria:
        criterion = item["text"]
        evidence: list[str] = []
        low = criterion.lower()
        for path in files:
            if path in criterion:
                evidence.append("path:" + path)
        if "docs-only" in low and docs_only:
            evidence.append("docs_only_paths")
        if ("no credential" in low or "no credentials" in low) and risk_clear:
            evidence.append("denylist_clear")
        if ("tests pass" in low or "unit tests" in low) and tests_passed:
            evidence.append("verify_check")
        if "independent review" in low and review_passed:
            evidence.append("review_check")
        met = bool(evidence) and not item.get("unchecked")
        if item.get("unchecked"):
            evidence = ["unchecked_box"]
            met = False
        results.append({"criterion": criterion, "met": met, "evidence": evidence})
    return results


def is_genuinely_necessary(files: list[str], duplicate: bool, review: dict[str, Any]) -> bool:
    """Non-empty net diff, not a duplicate, and the reviewer judged it in scope."""
    return (
        bool(files)
        and not duplicate
        and review.get("verdict") == "pass"
        and review.get("in_scope") is True
    )


def _done(check: dict[str, Any]) -> bool:
    status = check.get("status")
    if status in (None, "", "completed"):
        return bool(check.get("conclusion"))
    return False


def requires_sovereign_loop(files: list[str]) -> bool:
    return any(
        path.startswith("core/")
        or path.startswith("tests/")
        or path == ".github/workflows/lequtis-disposable-gate.yml"
        for path in files
    )


def summarize_checks(checks: list[dict[str, Any]], require_loop: bool = False) -> dict[str, Any]:
    by_name: dict[str, dict[str, Any]] = {}
    for item in checks:
        name = item.get("name")
        if not name:
            continue
        previous = by_name.get(str(name))
        if previous is None or str(item.get("started_at") or "") >= str(previous.get("started_at") or ""):
            by_name[str(name)] = item
    missing = []
    failed = []
    for name in REQUIRED_CHECKS:
        item = by_name.get(name)
        if item is None or not _done(item):
            missing.append(name)
        elif item.get("conclusion") != "success":
            failed.append(name)
    loop = by_name.get("sovereign-loop")
    loop_note = "not_scheduled"
    if loop is None:
        if require_loop:
            missing.append("sovereign-loop")
    elif not _done(loop):
        missing.append("sovereign-loop")
        loop_note = "running"
    elif loop.get("conclusion") in ("success", "skipped", "neutral"):
        loop_note = str(loop.get("conclusion"))
        if require_loop and loop.get("conclusion") != "success":
            failed.append("sovereign-loop")
    else:
        failed.append("sovereign-loop")
        loop_note = str(loop.get("conclusion"))
    normalized = []
    for name, item in sorted(by_name.items()):
        normalized.append({
            "name": name,
            "conclusion": item.get("conclusion") or "",
            "run_url": item.get("run_url") or item.get("html_url") or item.get("details_url") or "",
        })
    return {
        "passed": not missing and not failed,
        "missing": missing,
        "failed": failed,
        "sovereign_loop": loop_note,
        "checks": normalized,
    }


def parse_review_body(body: str) -> dict[str, Any] | None:
    if REVIEW_MARKER not in (body or ""):
        return None
    match = re.search(r"```json\n(.*?)\n```", body, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def select_review(bodies: list[str], head_sha: str) -> dict[str, Any] | None:
    chosen = None
    for body in bodies:
        parsed = parse_review_body(body)
        if parsed and parsed.get("head_sha") == head_sha:
            chosen = parsed
    return chosen


def repairs_from_commits(commits: list[dict[str, str]]) -> list[dict[str, Any]]:
    records = []
    for commit in commits:
        message = commit.get("message") or ""
        match = re.search(r"lequtis-repair\s+([12])/2", message)
        if not match:
            continue
        excerpt = ""
        for line in message.splitlines():
            if line.startswith("excerpt:"):
                excerpt = line.split(":", 1)[1].strip()
        records.append({
            "attempt": int(match.group(1)),
            "log_excerpt": excerpt[:500],
            "fix_commit": commit.get("sha"),
        })
    return records


def plan_repair(
    existing: list[dict[str, str]],
    log_text: str,
    files: dict[str, str],
) -> dict[str, Any]:
    prior = repairs_from_commits(existing)
    attempt = len(prior) + 1
    excerpt = scrub_text(log_text).strip()[:500]
    refused = {
        "allowed": False,
        "reason": "not_recoverable",
        "attempt": attempt,
        "log_excerpt": excerpt,
        "fix_commit": None,
        "files": {},
        "commit_message": "",
    }
    if len(prior) >= MAX_REPAIRS:
        refused["reason"] = "repair_budget_exhausted"
        refused["attempt"] = MAX_REPAIRS + 1
        return refused
    low = (log_text or "").lower()
    recoverable = "missing trailing newline" in low or "no newline at end of file" in low
    if not recoverable:
        return refused
    changes: dict[str, str] = {}
    for path, text in files.items():
        if path_reasons(path) or not isinstance(text, str) or "\0" in text:
            continue
        if text and not text.endswith("\n"):
            changes[path] = text + "\n"
    if not changes:
        return refused
    safe_excerpt = excerpt.replace("\n", " ")[:200]
    message = "fix: lequtis-repair " + str(attempt) + "/2\n\nexcerpt: " + safe_excerpt + "\n"
    return {
        "allowed": True,
        "reason": "missing_trailing_newline",
        "attempt": attempt,
        "log_excerpt": excerpt,
        "fix_commit": None,
        "files": changes,
        "commit_message": message,
    }


def confirm_read_back(pr_state: str, merge_commit_sha: str | None, on_default_branch: bool) -> dict[str, Any]:
    confirmed = pr_state == "MERGED" and bool(merge_commit_sha) and on_default_branch
    return {
        "confirmed": confirmed,
        "default_branch": "main",
        "observed_sha": merge_commit_sha if on_default_branch else None,
        "reason": "on_default_branch" if confirmed else "not_confirmed",
    }


def build_receipt(request: dict[str, Any]) -> dict[str, Any]:
    files = list(request.get("files") or [])
    review = dict(request.get("review") or {})
    review.setdefault("verdict", "missing")
    review.setdefault("in_scope", False)
    review.setdefault("findings", [])
    risk = risk_report(files, request.get("diff_text") or "")
    checks = summarize_checks(list(request.get("checks") or []), requires_sovereign_loop(files))
    tests_passed = any(
        item["name"] == "verify" and item["conclusion"] == "success" for item in checks["checks"]
    )
    review_passed = review.get("verdict") == "pass" and review.get("in_scope") is True
    parsed = parse_task(request.get("body") or "")
    acceptance = verify_acceptance(
        parsed["criteria"],
        files,
        risk_clear=not risk["needs_human"],
        tests_passed=tests_passed,
        review_passed=review_passed,
    )
    duplicate = bool(request.get("duplicate"))
    necessary = is_genuinely_necessary(files, duplicate, review)
    reasons: list[str] = []
    if not files:
        reasons.append("empty_pr")
    if duplicate:
        reasons.append("duplicate_work")
    if request.get("duplicate_scan") != "complete":
        reasons.append("duplicate_scan_incomplete")
    if risk["needs_human"]:
        reasons.append("needs_human")
    if not review_passed:
        reasons.append("independent_review_" + str(review.get("verdict") or "missing"))
    if any(item.get("severity") == "blocking" for item in review.get("findings") or []) and review_passed:
        reasons.append("blocking_findings")
    if not checks["passed"]:
        reasons.append("checks_failed")
    if not parsed["criteria"]:
        reasons.append("acceptance_criteria_missing")
    elif any(not item["met"] for item in acceptance):
        reasons.append("acceptance_unmet")
    if unverified_claim(request.get("body") or ""):
        reasons.append("unverified_completion_claim")
    if request.get("draft"):
        reasons.append("draft")
    if request.get("same_repo") is False:
        reasons.append("fork")
    ordered = list(dict.fromkeys(reasons))
    decision = "merge" if not ordered else "hold"
    repairs = list(request.get("repairs") or [])
    fix_count = len([item for item in repairs if item.get("fix_commit")])
    verify_failed = any(
        item["name"] == "verify" and item["conclusion"] == "failure" for item in checks["checks"]
    )
    repair_slot = (
        verify_failed
        and "needs_human" not in ordered
        and fix_count < MAX_REPAIRS
        and not request.get("draft")
        and request.get("same_repo") is not False
    )
    read_back = request.get("read_back") or {
        "confirmed": False,
        "default_branch": "main",
        "observed_sha": None,
        "reason": "not_merged",
    }
    return {
        "schema": SCHEMA,
        "authority": "lequtis",
        "reviewer_role": "subordinate",
        "evidence_label": "LOCAL PROOF, NOT LIVE VPS VERIFIED",
        "task_id": parsed["task_id"],
        "pr_url": request.get("pr_url"),
        "head_sha": request.get("head_sha"),
        "review": {
            "verdict": review.get("verdict"),
            "in_scope": review.get("in_scope"),
            "findings": review.get("findings") or [],
            "run_url": review.get("run_url") or "",
        },
        "checks": checks["checks"],
        "check_summary": {
            "passed": checks["passed"],
            "missing": checks["missing"],
            "failed": checks["failed"],
            "sovereign_loop": checks["sovereign_loop"],
        },
        "security": {
            "ok": not risk["needs_human"],
            "evidence": "path_and_keyword_denylist",
        },
        "regression": {
            "ok": tests_passed,
            "run_url": next((item["run_url"] for item in checks["checks"] if item["name"] == "verify"), ""),
        },
        "integration": {
            "ok": checks["sovereign_loop"] in ("success", "skipped", "neutral", "not_scheduled") and tests_passed,
            "sovereign_loop": checks["sovereign_loop"],
            "run_url": next((item["run_url"] for item in checks["checks"] if item["name"] == "sovereign-loop"), ""),
        },
        "acceptance": acceptance,
        "genuinely_necessary": necessary,
        "empty": not files,
        "duplicate": duplicate,
        "duplicate_of": request.get("duplicate_of"),
        "risk": risk,
        "repairs": repairs,
        "repair_budget": MAX_REPAIRS,
        "repair_slot": repair_slot,
        "merge_decision": decision,
        "merge_reason": "allowed" if decision == "merge" else "; ".join(ordered),
        "merge_commit_sha": request.get("merge_commit_sha"),
        "read_back": read_back,
        "notify": request.get("notify") or {"telegram_delivered": False, "degraded": True, "reason": "not_run"},
        "secrets": request.get("secrets") or {},
        "gate_run_url": request.get("gate_run_url") or "",
        "live_hermes": False,
        "live_hostinger": False,
    }


def apply_merge_result(
    receipt: dict[str, Any],
    returncode: int,
    stderr: str,
    read_back: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(receipt)
    updated["read_back"] = read_back
    if returncode != 0:
        updated["merge_decision"] = "hold"
        updated["merge_reason"] = "merge_command_failed: " + scrub_text(stderr).strip()[:300]
        updated["merge_commit_sha"] = None
        return updated
    updated["merge_commit_sha"] = read_back.get("observed_sha")
    if not read_back.get("confirmed"):
        updated["merge_reason"] = str(updated.get("merge_reason") or "allowed") + "; read_back_unconfirmed"
    return updated


def _git(cwd: str, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", cwd, *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def patch_id(diff: str) -> str | None:
    if not diff.strip():
        return None
    proc = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=diff,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.split()[0]


def find_duplicate_diff(current: str, others: list[tuple[str, str]]) -> str | None:
    current_id = patch_id(current)
    if not current_id:
        return None
    for url, diff in others:
        if patch_id(diff) == current_id:
            return url
    return None


def patch_already_on_base(diff: str, cwd: str, base: str) -> bool:
    current = patch_id(diff)
    if not current:
        return False
    log = _git(cwd, "log", base, "-n", "80", "-p", "--pretty=format:commit %H")
    if log.returncode != 0 or not log.stdout.strip():
        return False
    scanned = subprocess.run(
        ["git", "-C", cwd, "patch-id", "--stable"],
        input=log.stdout,
        text=True,
        capture_output=True,
        check=False,
    )
    if scanned.returncode != 0:
        return False
    return any(line.split()[0] == current for line in scanned.stdout.splitlines() if line.strip())


def commit_records(cwd: str, base: str, head: str) -> list[dict[str, str]]:
    log = _git(cwd, "log", "--format=%H%x1f%B%x1e", f"{base}..{head}")
    records = []
    if log.returncode != 0:
        return records
    for chunk in log.stdout.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        sha, _, message = chunk.partition("\x1f")
        records.append({"sha": sha.strip(), "message": message.strip()})
    return records


def _tracked_text(cwd: str, path: str) -> str | None:
    proc = _git(cwd, "show", "HEAD:" + path)
    if proc.returncode != 0:
        return None
    if "\0" in proc.stdout:
        return None
    return proc.stdout


def duplicate_blobs(cwd: str, files: list[str]) -> list[str]:
    listed = _git(cwd, "ls-files", "-z")
    if listed.returncode != 0:
        return []
    tracked = [item for item in listed.stdout.split("\0") if item]
    digests: dict[str, str] = {}
    for path in tracked:
        if path in files:
            continue
        text = _tracked_text(cwd, path)
        if text is None or len(text) < 40:
            continue
        digests.setdefault(hashlib.sha256(text.encode("utf-8")).hexdigest(), path)
    hits = []
    for path in files:
        text = _tracked_text(cwd, path)
        if text is None or len(text) < 40:
            continue
        other = digests.get(hashlib.sha256(text.encode("utf-8")).hexdigest())
        if other:
            hits.append(path)
    return hits


def git_context(cwd: str, base: str, head: str, other_diffs: list[tuple[str, str]], scan_complete: bool) -> dict[str, Any]:
    names = _git(cwd, "diff", "--name-only", f"{base}...{head}")
    if names.returncode != 0:
        raise RuntimeError(names.stderr.strip() or "git diff failed")
    files = [line for line in names.stdout.splitlines() if line.strip()]
    diff_proc = _git(cwd, "diff", f"{base}...{head}")
    if diff_proc.returncode != 0:
        raise RuntimeError(diff_proc.stderr.strip() or "git diff failed")
    diff = diff_proc.stdout
    duplicate_of = None
    duplicate = False
    if scan_complete and diff.strip():
        if patch_already_on_base(diff, cwd, base):
            duplicate = True
            duplicate_of = base
        open_match = find_duplicate_diff(diff, other_diffs)
        if open_match:
            duplicate = True
            duplicate_of = open_match
        blobs = duplicate_blobs(cwd, files)
        if blobs:
            duplicate = True
            duplicate_of = duplicate_of or ("blob:" + ",".join(blobs))
    changed: dict[str, str] = {}
    for path in files:
        text = _tracked_text(cwd, path)
        if text is not None:
            changed[path] = text
    return {
        "files": files,
        "diff_text": diff,
        "duplicate": duplicate,
        "duplicate_of": duplicate_of,
        "duplicate_scan": "complete" if scan_complete else "incomplete",
        "repairs": repairs_from_commits(commit_records(cwd, base, head)),
        "changed_files": changed,
    }


def _gh_json(args: list[str]) -> Any:
    proc = subprocess.run(["gh", *args], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "gh failed")
    return json.loads(proc.stdout)


def load_open_diffs(repo: str, pr: str) -> tuple[list[tuple[str, str]], bool]:
    try:
        items = _gh_json([
            "pr", "list", "--repo", repo, "--state", "open", "--limit", "20", "--json", "number,url",
        ])
    except (RuntimeError, json.JSONDecodeError):
        return [], False
    diffs: list[tuple[str, str]] = []
    for item in items:
        if str(item.get("number")) == str(pr):
            continue
        proc = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github.diff", f"repos/{repo}/pulls/{item['number']}"],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            return diffs, False
        diffs.append((item.get("url") or str(item.get("number")), proc.stdout[:200000]))
    return diffs, True


def fetch_check_runs(repo: str, sha: str) -> list[dict[str, Any]]:
    payload = _gh_json(["api", f"repos/{repo}/commits/{sha}/check-runs?per_page=100"])
    return list(payload.get("check_runs") or [])


def poll_checks(
    fetch: Callable[[], list[dict[str, Any]]],
    *,
    attempts: int = 24,
    sleep_seconds: float = 15,
    sleeper: Callable[[float], None] = time.sleep,
    require_loop: bool = False,
) -> dict[str, Any]:
    last: list[dict[str, Any]] = []
    for _ in range(attempts):
        last = fetch()
        summary = summarize_checks(last, require_loop)
        if not summary["missing"]:
            return {"complete": True, "checks": last, "summary": summary}
        if sleep_seconds:
            sleeper(sleep_seconds)
    return {"complete": False, "checks": last, "summary": summarize_checks(last, require_loop)}


def fetch_review_bodies(repo: str, pr: str) -> list[str]:
    reviews = _gh_json(["api", f"repos/{repo}/pulls/{pr}/reviews?per_page=100"])
    return [item.get("body") or "" for item in reviews]


def _token() -> str:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""


def _github(method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": "Bearer " + _token(),
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def sync_label(repo: str, pr: str, needed: bool) -> dict[str, Any]:
    if not _token():
        return {"ok": False, "error": "missing_token", "needed": needed}
    base = "https://api.github.com/repos/" + repo
    status, _body = _github("POST", base + "/labels", {
        "name": LABEL,
        "color": "b60205",
        "description": "Held for a human decision",
    })
    if status not in (201, 422):
        return {"ok": False, "error": "label_create_" + str(status), "needed": needed}
    if needed:
        status, _body = _github("POST", base + "/issues/" + str(pr) + "/labels", {"labels": [LABEL]})
        return {"ok": status in (200, 201), "action": "added", "status": status}
    status, _body = _github("DELETE", base + "/issues/" + str(pr) + "/labels/" + LABEL)
    return {"ok": status in (200, 204, 404), "action": "removed", "status": status}


def upsert_comment(repo: str, pr: str, body: str) -> dict[str, Any]:
    if not _token():
        return {"ok": False, "error": "missing_token"}
    base = "https://api.github.com/repos/" + repo
    status, raw = _github("GET", base + "/issues/" + str(pr) + "/comments?per_page=100")
    if status != 200:
        return {"ok": False, "error": "list_" + str(status)}
    comments = json.loads(raw)
    existing = next((item for item in comments if RECEIPT_MARKER in (item.get("body") or "")), None)
    if existing:
        status, _body = _github("PATCH", base + "/issues/comments/" + str(existing["id"]), {"body": body})
        return {"ok": status == 200, "action": "updated", "status": status}
    status, _body = _github("POST", base + "/issues/" + str(pr) + "/comments", {"body": body})
    return {"ok": status == 201, "action": "created", "status": status}


def receipt_comment(receipt: dict[str, Any]) -> str:
    return (
        RECEIPT_MARKER + "\n\n"
        "LeQutis engineering receipt. The reviewer is subordinate.\n\n"
        "merge_decision: " + str(receipt.get("merge_decision")) + "\n"
        "merge_reason: " + str(receipt.get("merge_reason")) + "\n"
        "genuinely_necessary: " + str(receipt.get("genuinely_necessary")) + "\n"
        "live_hermes: false\n"
        "live_hostinger: false\n\n"
        "```json\n" + json.dumps(receipt, indent=2, sort_keys=True) + "\n```\n"
    )


def evaluate(request: dict[str, Any]) -> dict[str, Any]:
    import hermes_notify

    incoming = dict(request)
    draft = build_receipt({**incoming, "notify": incoming.get("notify") or {"pending": True}})
    if "notify" not in incoming:
        summary = "LeQutis {decision} {url} {reason}".format(
            decision=draft["merge_decision"],
            url=draft.get("pr_url") or "",
            reason=draft.get("merge_reason") or "",
        )
        draft["notify"] = hermes_notify.deliver(summary)
    if "secrets" not in incoming:
        draft["secrets"] = secret_presence()
    flag = ((incoming.get("review") or {}).get("secret") or {}).get("LEQUTIS_REVIEWER_API_KEY")
    if flag in ("present", "absent"):
        draft["secrets"]["LEQUTIS_REVIEWER_API_KEY"] = flag
    return scrub_obj(draft)


def assemble_request(evidence: str) -> dict[str, Any]:
    folder = Path(evidence)
    ctx = json.loads((folder / "context.json").read_text(encoding="utf-8"))
    checks = json.loads((folder / "checks.json").read_text(encoding="utf-8"))
    review = json.loads((folder / "review.json").read_text(encoding="utf-8"))
    return {
        "files": ctx["files"],
        "diff_text": ctx["diff_text"],
        "body": (folder / "pr-body.md").read_text(encoding="utf-8"),
        "checks": checks.get("checks") or [],
        "review": review,
        "duplicate": ctx["duplicate"],
        "duplicate_of": ctx.get("duplicate_of"),
        "duplicate_scan": ctx["duplicate_scan"],
        "repairs": ctx["repairs"],
        "pr_url": os.environ.get("PR_URL"),
        "head_sha": os.environ.get("HEAD_SHA"),
        "draft": os.environ.get("DRAFT") == "true",
        "same_repo": os.environ.get("SAME_REPO") == "true",
        "gate_run_url": os.environ.get("RUN_URL") or "",
    }


def write_gate_outputs(receipt_path: str, output_path: str) -> None:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write("merge=" + ("true" if receipt["merge_decision"] == "merge" else "false") + "\n")
        handle.write("repair=" + ("true" if receipt.get("repair_slot") else "false") + "\n")


def prepare_repair_request(cwd: str, base: str) -> dict[str, Any]:
    names = _git(cwd, "diff", "--name-only", f"{base}...HEAD")
    if names.returncode != 0:
        raise RuntimeError(names.stderr.strip() or "git diff failed")
    changed: dict[str, str] = {}
    for path in [line for line in names.stdout.splitlines() if line.strip()]:
        if path_reasons(path):
            continue
        file = Path(cwd) / path
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        if "\0" in text:
            continue
        changed[path] = text
    commits = commit_records(cwd, base, "HEAD")
    return {"repairs": repairs_from_commits(commits), "changed_files": changed}


def apply_repair_plan(plan_path: str, message_path: str) -> int:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if not plan.get("allowed"):
        sys.stderr.write(str(plan.get("reason") or "not_recoverable") + "\n")
        return 2
    for path, text in plan["files"].items():
        Path(path).write_text(text, encoding="utf-8")
        sys.stdout.write(path + "\n")
    Path(message_path).write_text(plan["commit_message"], encoding="utf-8")
    return 0


def extract_criteria(body: str) -> str:
    parsed = parse_task(body)
    return "\n".join(item["text"] for item in parsed["criteria"]) + ("\n" if parsed["criteria"] else "")


def _write(path: str, payload: Any) -> None:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, sort_keys=True) + "\n"
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    pre = sub.add_parser("preflight")
    pre.add_argument("--out")

    extract = sub.add_parser("extract-criteria")
    extract.add_argument("--body-file", required=True)
    extract.add_argument("--out", required=True)

    context = sub.add_parser("context")
    context.add_argument("--base", required=True)
    context.add_argument("--head", default="HEAD")
    context.add_argument("--repo", required=True)
    context.add_argument("--pr", required=True)
    context.add_argument("--cwd", default=".")
    context.add_argument("--out", required=True)

    poll = sub.add_parser("poll")
    poll.add_argument("--repo", required=True)
    poll.add_argument("--sha", required=True)
    poll.add_argument("--attempts", type=int, default=24)
    poll.add_argument("--sleep", type=float, default=15)
    poll.add_argument("--require-loop", default="false", choices=("true", "false"))
    poll.add_argument("--out", required=True)

    collect = sub.add_parser("collect-review")
    collect.add_argument("--repo", required=True)
    collect.add_argument("--pr", required=True)
    collect.add_argument("--sha", required=True)
    collect.add_argument("--out", required=True)

    evaluate_cmd = sub.add_parser("evaluate")
    evaluate_cmd.add_argument("--request", required=True)
    evaluate_cmd.add_argument("--out", required=True)

    repair = sub.add_parser("plan-repair")
    repair.add_argument("--request", required=True)
    repair.add_argument("--log-file", required=True)
    repair.add_argument("--out", required=True)

    label = sub.add_parser("label")
    label.add_argument("--repo", required=True)
    label.add_argument("--pr", required=True)
    label.add_argument("--needed", required=True, choices=("true", "false"))

    comment = sub.add_parser("comment")
    comment.add_argument("--repo", required=True)
    comment.add_argument("--pr", required=True)
    comment.add_argument("--receipt", required=True)

    read_back = sub.add_parser("read-back")
    read_back.add_argument("--repo", required=True)
    read_back.add_argument("--pr", required=True)
    read_back.add_argument("--cwd", default=".")
    read_back.add_argument("--receipt", required=True)
    read_back.add_argument("--merge-exit", type=int, default=0)
    read_back.add_argument("--merge-stderr", default="")
    read_back.add_argument("--out", required=True)

    assemble = sub.add_parser("assemble")
    assemble.add_argument("--evidence", default="evidence")
    assemble.add_argument("--out", required=True)

    outputs = sub.add_parser("outputs")
    outputs.add_argument("--receipt", required=True)

    prepare = sub.add_parser("prepare-repair")
    prepare.add_argument("--base", required=True)
    prepare.add_argument("--cwd", default=".")
    prepare.add_argument("--out", required=True)

    apply = sub.add_parser("apply-repair")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--message", required=True)

    args = parser.parse_args(argv)
    if args.cmd == "preflight":
        payload = secret_presence()
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.out:
            _write(args.out, text)
        sys.stdout.write(text)
        return 0
    if args.cmd == "extract-criteria":
        body = Path(args.body_file).read_text(encoding="utf-8")
        _write(args.out, extract_criteria(body))
        return 0
    if args.cmd == "context":
        others, complete = load_open_diffs(args.repo, args.pr)
        payload = git_context(args.cwd, args.base, args.head, others, complete)
        _write(args.out, payload)
        return 0
    if args.cmd == "poll":
        try:
            outcome = poll_checks(
                lambda: fetch_check_runs(args.repo, args.sha),
                attempts=args.attempts,
                sleep_seconds=args.sleep,
                require_loop=args.require_loop == "true",
            )
        except Exception as exc:  # noqa: BLE001 - an unread check list is a hold, not a crash
            outcome = {"complete": False, "checks": [], "error": type(exc).__name__}
        _write(args.out, outcome)
        return 0
    if args.cmd == "collect-review":
        selected = None
        error = ""
        for _ in range(3):
            try:
                bodies = fetch_review_bodies(args.repo, args.pr)
            except RuntimeError as exc:
                error = str(exc)[:300]
                bodies = []
            selected = select_review(bodies, args.sha)
            if selected:
                break
            time.sleep(5)
        if not selected:
            selected = {
                "verdict": "missing",
                "in_scope": False,
                "findings": [{
                    "severity": "blocking",
                    "summary": error or "independent review for this head SHA is missing",
                }],
            }
        _write(args.out, selected)
        return 0
    if args.cmd == "evaluate":
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        receipt = evaluate(request)
        _write(args.out, receipt)
        sys.stdout.write(receipt["merge_decision"] + "\n")
        return 0
    if args.cmd == "plan-repair":
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        log_text = Path(args.log_file).read_text(encoding="utf-8", errors="replace")
        existing = [
            {"sha": item.get("fix_commit") or "", "message": "lequtis-repair " + str(item.get("attempt")) + "/2\nexcerpt: " + str(item.get("log_excerpt") or "")}
            for item in request.get("repairs") or []
            if item.get("fix_commit")
        ]
        plan = plan_repair(existing, log_text, request.get("changed_files") or {})
        _write(args.out, plan)
        return 0
    if args.cmd == "label":
        result = sync_label(args.repo, args.pr, args.needed == "true")
        sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
        return 0 if result.get("ok") else 1
    if args.cmd == "comment":
        receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
        result = upsert_comment(args.repo, args.pr, receipt_comment(receipt))
        sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
        return 0 if result.get("ok") else 1
    if args.cmd == "read-back":
        receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
        try:
            viewed = _gh_json(["pr", "view", str(args.pr), "--repo", args.repo, "--json", "state,mergeCommit"])
        except RuntimeError as exc:
            viewed = {"state": "UNKNOWN", "mergeCommit": None, "error": str(exc)}
        sha = (viewed.get("mergeCommit") or {}).get("oid") if isinstance(viewed.get("mergeCommit"), dict) else None
        on_branch = False
        if sha:
            _git(args.cwd, "fetch", "origin", "main")
            if _git(args.cwd, "cat-file", "-t", sha).returncode == 0:
                on_branch = _git(args.cwd, "merge-base", "--is-ancestor", sha, "origin/main").returncode == 0
        read = confirm_read_back(str(viewed.get("state") or ""), sha, on_branch)
        stderr = Path(args.merge_stderr).read_text(encoding="utf-8", errors="replace") if args.merge_stderr else ""
        updated = apply_merge_result(receipt, args.merge_exit, stderr, read)
        _write(args.out, updated)
        return 0
    if args.cmd == "assemble":
        _write(args.out, assemble_request(args.evidence))
        return 0
    if args.cmd == "outputs":
        write_gate_outputs(args.receipt, os.environ["GITHUB_OUTPUT"])
        receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
        sys.stdout.write(receipt["merge_decision"] + "\n" + receipt["merge_reason"] + "\n")
        return 0
    if args.cmd == "prepare-repair":
        _write(args.out, prepare_repair_request(args.cwd, args.base))
        return 0
    if args.cmd == "apply-repair":
        return apply_repair_plan(args.plan, args.message)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
