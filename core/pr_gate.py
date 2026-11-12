#!/usr/bin/env python3
"""Independent PR verifier for LeQutis.

The implementing agent is not the authority. This module is the
Verifier/Auditor: it judges a pull request from its diff, commits, and
check runs, and it records which evidence class each conclusion belongs to.

Static validation, local execution, and live end-to-end read-back are
separate. One must not be reported as another.

External reviewers, including any model, are subordinate. This repository
does not provision Hostinger, Hermes, or Telegram routes.

LOCAL PROOF, NOT LIVE VPS VERIFIED.
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
from pathlib import Path
from typing import Any, Callable

EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"
READBACK_LABEL = "GITHUB MAIN READ-BACK, NOT LIVE VPS VERIFIED"
SCHEMA = "lequtis-pr-gate-v1"
ACCEPTANCE_NAME = "PR_GATE_ACCEPTANCE.json"
SELF_CHECK_NAMES = {"merge", "readback"}
REPAIR_MAX_ATTEMPTS = 2
CHAIN = [
    "LeQutis",
    "Oracle/TBQ",
    "Hermes",
    "Builder Swarm",
    "Verifier/Auditor",
]

LIVE_CLAIM = re.compile(
    r"(?<!NOT )LIVE[ _-]?(?:VPS|HOSTINGER|HERMES)[ _-]?VERIFIED",
    re.IGNORECASE,
)
TASK_ID = re.compile(r"(?im)^task-id:\s*(\S+)")
SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
)
DESTRUCTIVE_NEEDLES = (
    "rm -rf " + "/",
    "DROP " + "DATABASE",
    "DROP " + "TABLE",
    "git push " + "--force",
    "git push " + "-f",
)
INFRA_NEEDLE = "pull_request" + "_target"
POLICY_PATHS = {
    "core/pr_gate.py",
    ".github/workflows/pr-gate.yml",
    "knowledge/PR_GATE_ACCEPTANCE.json",
}
CREDENTIAL_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
}
TRANSIENT_MARKERS = (
    "Temporary failure in name resolution",
    "Could not resolve host",
    "Connection timed out",
    "TLS handshake timeout",
    "The runner has received a shutdown signal",
    "dial tcp: lookup",
)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_acceptance(root: Path | None = None) -> dict[str, Any]:
    path = (root or _root()) / "knowledge" / ACCEPTANCE_NAME
    if not path.is_file():
        raise FileNotFoundError(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "lequtis-pr-gate-acceptance-v1":
        raise ValueError("acceptance schema mismatch")
    if int(data.get("repair", {}).get("max_attempts", 0)) != REPAIR_MAX_ATTEMPTS:
        raise ValueError("repair bound drifted from the verifier")
    return data


def added_lines(diff: str) -> list[str]:
    lines: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            lines.append(line[1:])
    return lines


def _finding(
    code: str,
    summary: str,
    *,
    fails_check: bool,
    repair: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "summary": summary,
        "stage": "static_validation",
        "blocking": True,
        "fails_check": fails_check,
        "repair": repair,
    }


def _credential_path(path: str) -> bool:
    name = Path(path).name
    if name in CREDENTIAL_NAMES or name.startswith(".env"):
        return True
    return name.endswith((".pem", ".p12", ".key"))


def _task_id(report: dict[str, Any]) -> str:
    match = TASK_ID.search(report.get("body") or "")
    if match:
        return match.group(1)
    number = report.get("number")
    if number:
        return f"pr-{number}"
    return report.get("head_sha") or "unknown"


def static_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Judge the diff without running the suite and without calling a model."""
    findings: list[dict[str, Any]] = []
    commits = list(report.get("commits") or [])
    files = list(report.get("files") or [])
    diff = report.get("diff") or ""
    body = report.get("body") or ""
    paths = [str(item.get("path") or "") for item in files]

    if report.get("acceptance_missing"):
        findings.append(
            _finding(
                "acceptance_contract_missing",
                "knowledge/PR_GATE_ACCEPTANCE.json is missing or invalid.",
                fails_check=True,
            )
        )

    if commits and not files:
        findings.append(
            _finding(
                "empty_net_diff",
                f"{len(commits)} commits and zero net changed files. "
                "GitHub's file list is the diff against the base. "
                "No implementation is recovered from an empty net diff.",
                fails_check=True,
                repair=None,
            )
        )
    elif files and sum(int(item.get("additions") or 0) + int(item.get("deletions") or 0) for item in files) == 0:
        findings.append(
            _finding(
                "empty_net_diff",
                "Changed-file entries contain no added or removed lines.",
                fails_check=True,
            )
        )

    duplicate_of = report.get("duplicate_of")
    if duplicate_of:
        findings.append(
            _finding(
                "duplicate",
                f"Net diff matches open PR #{duplicate_of}.",
                fails_check=True,
            )
        )

    if LIVE_CLAIM.search(body):
        findings.append(
            _finding(
                "unverified_completion_claim",
                "The PR body claims a live Hostinger, Hermes, or VPS verification. "
                "This gate does not accept that claim from prose.",
                fails_check=True,
            )
        )

    for path in paths:
        if _credential_path(path):
            findings.append(
                _finding(
                    "credentials",
                    f"Refusing auto-merge of credential path {path}.",
                    fails_check=True,
                )
            )
        if path.startswith("database/migrations/") or path == "database/schema.sql":
            findings.append(
                _finding(
                    "production_migration",
                    f"Schema or migration change {path} is not auto-merged.",
                    fails_check=True,
                )
            )
        if path in POLICY_PATHS:
            findings.append(
                _finding(
                    "gate_policy_change",
                    f"{path} changes the merge gate. Auto-merge will not land its own policy.",
                    fails_check=False,
                )
            )

    for line in added_lines(diff):
        if any(pattern.search(line) for pattern in SECRET_PATTERNS):
            findings.append(
                _finding(
                    "credentials",
                    "Added line matches a credential pattern.",
                    fails_check=True,
                )
            )
            break
    blob = "\n".join(added_lines(diff))
    for needle in DESTRUCTIVE_NEEDLES:
        if needle in blob:
            findings.append(
                _finding(
                    "destructive",
                    "Added diff contains a destructive command.",
                    fails_check=True,
                )
            )
            break
    if INFRA_NEEDLE in blob:
        findings.append(
            _finding(
                "unverified_infrastructure",
                "A pull_request" + "_target workflow is not accepted on the auto-merge path.",
                fails_check=True,
            )
        )
    if re.search(r"LEQUTIS_HERMES_ROUTE['\"\]]*\s*(?:=|:)+\s*['\"]live['\"]", blob):
        findings.append(
            _finding(
                "unverified_infrastructure",
                "A diff that turns the Hermes route live is not auto-merged.",
                fails_check=True,
            )
        )

    if report.get("draft"):
        findings.append(
            _finding(
                "draft",
                "Draft pull requests are not auto-merged.",
                fails_check=False,
            )
        )
    if report.get("same_repo") is False:
        findings.append(
            _finding(
                "fork_pr",
                "Fork pull requests are not auto-merged.",
                fails_check=False,
            )
        )
    if report.get("diff_truncated"):
        findings.append(
            _finding(
                "diff_truncated",
                "The diff exceeded the review cap. Auto-merge fails closed.",
                fails_check=True,
            )
        )
    return findings


def _check_state(item: dict[str, Any]) -> str:
    return str(item.get("state") or "").upper()


def _check_bucket(item: dict[str, Any]) -> str:
    return str(item.get("bucket") or "").lower()


def check_failed(item: dict[str, Any]) -> bool:
    return _check_state(item) in {"FAILURE", "FAILED", "CANCELLED", "TIMED_OUT"} or _check_bucket(item) in {
        "fail",
        "cancel",
    }


def check_success(item: dict[str, Any]) -> bool:
    return _check_state(item) in {"SUCCESS", "SKIPPED", "NEUTRAL"} or _check_bucket(item) in {
        "pass",
        "skip",
        "skipping",
    }


def interpret_checks(checks: list[dict[str, Any]]) -> str:
    """Return pass, fail, or wait. The merge job ignores its own check name."""
    relevant = [item for item in checks if item.get("name") not in SELF_CHECK_NAMES]
    if not relevant:
        return "wait"
    if any(check_failed(item) for item in relevant):
        return "fail"
    verify = [item for item in relevant if item.get("name") == "verify"]
    if not verify or not any(_check_state(item) == "SUCCESS" or _check_bucket(item) == "pass" for item in verify):
        return "wait"
    if any(not check_success(item) for item in relevant):
        return "wait"
    return "pass"


def is_transient_failure(log: str) -> bool:
    return any(marker in log for marker in TRANSIENT_MARKERS)


def run_suite(
    command: list[str],
    *,
    max_attempts: int = REPAIR_MAX_ATTEMPTS,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Run a suite, retrying only transient failures, never past the bound."""
    if max_attempts != REPAIR_MAX_ATTEMPTS:
        raise ValueError("repair attempts are fixed at the acceptance bound")
    attempts: list[dict[str, Any]] = []
    for number in range(1, max_attempts + 1):
        proc = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            check=False,
        )
        log = (proc.stdout or "") + (proc.stderr or "")
        transient = proc.returncode != 0 and is_transient_failure(log)
        attempts.append(
            {
                "attempt": number,
                "returncode": proc.returncode,
                "transient": transient,
                "repair": "rerun_transient_tests" if transient and number < max_attempts else None,
            }
        )
        if proc.returncode == 0:
            return {"ok": True, "attempts": attempts, "evidence_label": EVIDENCE_LABEL}
        if not transient:
            return {"ok": False, "attempts": attempts, "evidence_label": EVIDENCE_LABEL}
    return {"ok": False, "attempts": attempts, "evidence_label": EVIDENCE_LABEL}


def assess(report: dict[str, Any], *, for_merge: bool) -> dict[str, Any]:
    try:
        load_acceptance()
        report = dict(report)
    except (OSError, ValueError, json.JSONDecodeError):
        report = dict(report)
        report["acceptance_missing"] = True
    findings = static_findings(report)
    fails_check = any(item["fails_check"] for item in findings)
    tests_passed = report.get("tests_passed")
    local_status = "pending"
    if tests_passed is True:
        local_status = "pass"
    elif tests_passed is False:
        local_status = "fail"
        findings.append(
            _finding(
                "tests_failed",
                "Disposable local execution did not pass.",
                fails_check=True,
            )
        )
        fails_check = True

    checks_state = report.get("checks_state")
    if for_merge and checks_state == "fail":
        findings.append(
            _finding("ci_failed", "A required GitHub check failed.", fails_check=True)
        )
        fails_check = True
    if for_merge and checks_state == "wait":
        findings.append(
            _finding("checks_pending", "Required GitHub checks did not finish in time.", fails_check=True)
        )
        fails_check = True

    blocking_codes = {item["code"] for item in findings if item["blocking"]}
    can_merge = (
        for_merge
        and not fails_check
        and not blocking_codes
        and tests_passed is True
        and checks_state == "pass"
        and bool(report.get("files"))
        and report.get("same_repo") is not False
        and not report.get("draft")
    )
    static_status = "fail" if any(item["fails_check"] and item["stage"] == "static_validation" for item in findings) else "pass"
    if any(item["code"] == "acceptance_contract_missing" for item in findings):
        static_status = "fail"
    return {
        "schema": SCHEMA,
        "evidence_label": EVIDENCE_LABEL,
        "authority": "LeQutis verifier/auditor",
        "external_agents": "subordinate",
        "chain": list(CHAIN),
        "hermes": "existing stdio connector not invoked; no replacement route provisioned",
        "telegram": "no telegram route in this repository; no replacement provisioned",
        "hostinger": "not contacted by this gate",
        "task_id": _task_id(report),
        "number": report.get("number"),
        "head_sha": report.get("head_sha"),
        "base_sha": report.get("base_sha"),
        "stages": {
            "static_validation": {
                "class": "static_validation",
                "status": static_status,
            },
            "local_execution": {
                "class": "local_execution",
                "status": local_status,
                "note": "Disposable suite only. Not a live VPS or Hostinger proof.",
            },
            "live_end_to_end": {
                "class": "live_end_to_end",
                "status": "not_this_job",
                "scope": "github_main_readback_only_after_merge",
                "hostinger_hermes": "not_run",
                "telegram": "not_run",
                "note": "This job must not claim live end-to-end verification.",
            },
        },
        "findings": findings,
        "fails_check": fails_check,
        "decision": "merge" if can_merge else "hold",
        "repair": {
            "max_attempts": REPAIR_MAX_ATTEMPTS,
            "empty_net_diff": None,
            "allowed": ["rerun_transient_tests"],
        },
    }


def diff_hash(diff: str) -> str:
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def find_duplicate(diff: str, others: list[dict[str, Any]]) -> int | None:
    digest = diff_hash(diff)
    for item in others:
        if item.get("diff_hash") == digest and item.get("number"):
            return int(item["number"])
    return None


def _gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], text=True, capture_output=True, check=check)


def _event() -> dict[str, Any]:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _pr_view(number: int) -> dict[str, Any]:
    proc = _gh(
        [
            "pr",
            "view",
            str(number),
            "--json",
            "number,title,body,isDraft,commits,files,headRefOid,baseRefOid,headRepositoryOwner,headRepository,baseRefName",
        ]
    )
    return json.loads(proc.stdout)


def _pr_diff(number: int, limit: int = 1_000_000) -> tuple[str, bool]:
    proc = _gh(["pr", "diff", str(number)], check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "gh pr diff failed")
    text = proc.stdout
    if len(text.encode("utf-8")) > limit:
        return text.encode("utf-8")[:limit].decode("utf-8", errors="ignore"), True
    return text, False


def report_from_event(event: dict[str, Any] | None = None) -> dict[str, Any]:
    event = event if event is not None else _event()
    pr = event.get("pull_request") or {}
    number = int(pr.get("number") or 0)
    if not number:
        raise ValueError("not a pull_request event")
    viewed = _pr_view(number)
    diff, truncated = _pr_diff(number)
    files = [
        {
            "path": item.get("path"),
            "additions": item.get("additions") or 0,
            "deletions": item.get("deletions") or 0,
            "status": item.get("changeType") or item.get("status"),
        }
        for item in viewed.get("files") or []
    ]
    commits = [{"oid": item.get("oid"), "message": item.get("messageHeadline")} for item in viewed.get("commits") or []]
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
    base_repo = ((pr.get("base") or {}).get("repo") or {}).get("full_name")
    duplicate_of = None
    duplicate_scan = "not_run"
    try:
        others = _open_diff_hashes(number)
        duplicate_of = find_duplicate(diff, others)
        duplicate_scan = "complete"
    except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError):
        duplicate_scan = "unavailable"
    return {
        "number": number,
        "title": viewed.get("title") or pr.get("title") or "",
        "body": viewed.get("body") or pr.get("body") or "",
        "draft": bool(viewed.get("isDraft") if "isDraft" in viewed else pr.get("draft")),
        "commits": commits,
        "files": files,
        "diff": diff,
        "diff_truncated": truncated,
        "head_sha": viewed.get("headRefOid") or (pr.get("head") or {}).get("sha"),
        "base_sha": viewed.get("baseRefOid") or (pr.get("base") or {}).get("sha"),
        "same_repo": head_repo == base_repo if head_repo and base_repo else True,
        "duplicate_of": duplicate_of,
        "duplicate_scan": duplicate_scan,
        "tests_passed": None,
    }


def _open_diff_hashes(current: int) -> list[dict[str, Any]]:
    proc = _gh(
        ["pr", "list", "--state", "open", "--limit", "20", "--json", "number"],
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "gh pr list failed")
    rows = []
    for item in json.loads(proc.stdout):
        number = int(item["number"])
        if number == current:
            continue
        diff, _truncated = _pr_diff(number)
        rows.append({"number": number, "diff_hash": diff_hash(diff)})
    return rows


def _review_body(receipt: dict[str, Any]) -> str:
    lines = [
        "LeQutis verifier/auditor (independent of the implementing agent).",
        "",
        f"Task-Id: `{receipt['task_id']}`",
        f"Decision: **{receipt['decision']}**",
        f"Static validation: {receipt['stages']['static_validation']['status']}",
        f"Local execution: {receipt['stages']['local_execution']['status']}",
        "Live end-to-end: not_this_job (not claimed here).",
        "",
        EVIDENCE_LABEL,
        "",
    ]
    if receipt["findings"]:
        lines.append("Findings:")
        for item in receipt["findings"]:
            lines.append(f"- `{item['code']}`: {item['summary']}")
    else:
        lines.append("No static blocking findings.")
    lines.append("")
    lines.append("Hermes and Telegram were not called. No replacement infrastructure was provisioned.")
    return "\n".join(lines) + "\n"


def post_review(number: int, body: str) -> None:
    last_error = ""
    for _attempt in range(REPAIR_MAX_ATTEMPTS):
        proc = _gh(
            ["pr", "review", str(number), "--comment", "--body", body],
            check=False,
        )
        if proc.returncode == 0:
            return
        last_error = proc.stderr.strip() or proc.stdout.strip()
        time.sleep(2)
    raise RuntimeError(last_error or "gh pr review failed")


def fetch_checks(number: int) -> list[dict[str, Any]]:
    proc = _gh(
        ["pr", "checks", str(number), "--json", "name,state,bucket,workflow,link"],
        check=False,
    )
    if proc.returncode != 0:
        return []
    return json.loads(proc.stdout or "[]")


def wait_for_checks(
    fetch: Callable[[], list[dict[str, Any]]],
    *,
    timeout_s: float,
    sleep_s: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, list[dict[str, Any]]]:
    started = clock()
    latest: list[dict[str, Any]] = []
    while True:
        latest = fetch()
        state = interpret_checks(latest)
        if state in {"pass", "fail"}:
            return state, latest
        if clock() - started >= timeout_s:
            return "wait", latest
        sleep(sleep_s)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_assess(args: argparse.Namespace) -> int:
    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    receipt = assess(report, for_merge=args.for_merge)
    text = json.dumps(receipt, indent=2, sort_keys=True)
    if args.out:
        write_json(Path(args.out), receipt)
    else:
        sys.stdout.write(text + "\n")
    return 1 if receipt["fails_check"] else 0


def cmd_review(_args: argparse.Namespace) -> int:
    event = _event()
    if "pull_request" not in event:
        receipt = assess({"files": [{"path": "noop", "additions": 1, "deletions": 0}], "body": "", "commits": []}, for_merge=False)
        receipt["decision"] = "hold"
        receipt["stages"]["static_validation"]["status"] = "skipped"
        write_json(Path("evidence/pr-gate-review.json"), receipt)
        return 0
    report = report_from_event(event)
    receipt = assess(report, for_merge=False)
    write_json(Path("evidence/pr-gate-review.json"), receipt)
    post_review(int(report["number"]), _review_body(receipt))
    return 1 if receipt["fails_check"] else 0


def cmd_merge(args: argparse.Namespace) -> int:
    number = int(args.pr or (_event().get("pull_request") or {}).get("number") or 0)
    if not number:
        raise SystemExit("merge requires a pull request number")
    fake_event = {"pull_request": {"number": number, "head": {"repo": {}}, "base": {"repo": {}}}}
    # gh pr view supplies the authoritative fields; same_repo stays true unless the event says otherwise.
    report = report_from_event({"pull_request": {"number": number, **(_event().get("pull_request") or {})}})
    state, checks = wait_for_checks(
        lambda: fetch_checks(number),
        timeout_s=float(args.timeout),
        sleep_s=float(args.sleep),
    )
    report["tests_passed"] = state == "pass"
    report["checks_state"] = state
    report["checks"] = [
        {"name": item.get("name"), "state": item.get("state"), "link": item.get("link")}
        for item in checks
    ]
    receipt = assess(report, for_merge=True)
    receipt["checks"] = report["checks"]
    write_json(Path(args.out), receipt)
    if receipt["fails_check"]:
        return 1
    return 0


def cmd_run_suite(args: argparse.Namespace) -> int:
    command = list(args.suite_command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise SystemExit("run-suite requires a command")
    result = run_suite(command, cwd=_root())
    if args.out:
        write_json(Path(args.out), result)
    else:
        json.dump(result, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    return 0 if result["ok"] else 1


def cmd_classify(args: argparse.Namespace) -> int:
    log = sys.stdin.read() if args.log == "-" else Path(args.log).read_text(encoding="utf-8")
    transient = is_transient_failure(log)
    json.dump({"transient": transient, "max_attempts": REPAIR_MAX_ATTEMPTS}, sys.stdout)
    sys.stdout.write("\n")
    return 0 if transient else 1


def cmd_readback(_args: argparse.Namespace) -> int:
    """Record that this checkout is the commit GitHub just pushed. Not a VPS proof."""
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    names = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    payload = {
        "schema": SCHEMA,
        "stage": "live_end_to_end",
        "class": "live_end_to_end",
        "status": "passed",
        "scope": "github_main_readback",
        "head_sha": sha,
        "files": [line for line in names if line],
        "hostinger_hermes": "not_run",
        "telegram": "not_run",
        "evidence_label": READBACK_LABEL,
        "not_a_substitute_for": ["static_validation", "local_execution", "live_vps"],
    }
    write_json(Path("evidence/pr-gate-readback.json"), payload)
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def cmd_post_marker(args: argparse.Namespace) -> int:
    """Used by the merge job only after assess() returned decision=merge."""
    receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    if receipt.get("decision") != "merge":
        print("verifier held the merge")
        return 0
    number = int(receipt["number"])
    subject = f"lequtis-pr-gate auto-merge #{number}"
    body = (
        f"Task-Id: {receipt.get('task_id')}\n"
        f"Head: {receipt.get('head_sha')}\n"
        "Verifier decision: merge\n"
        f"{EVIDENCE_LABEL}\n"
    )
    proc = _gh(
        ["pr", "merge", str(number), "--merge", "--subject", subject, "--body", body],
        check=False,
    )
    print(proc.stdout)
    print(proc.stderr, file=sys.stderr)
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    assess_cmd = sub.add_parser("assess")
    assess_cmd.add_argument("--input", required=True)
    assess_cmd.add_argument("--out")
    assess_cmd.add_argument("--for-merge", action="store_true")
    assess_cmd.set_defaults(func=cmd_assess)

    review_cmd = sub.add_parser("review")
    review_cmd.set_defaults(func=cmd_review)

    merge_cmd = sub.add_parser("merge")
    merge_cmd.add_argument("--pr")
    merge_cmd.add_argument("--timeout", default="480")
    merge_cmd.add_argument("--sleep", default="15")
    merge_cmd.add_argument("--out", default="evidence/pr-gate-merge.json")
    merge_cmd.set_defaults(func=cmd_merge)

    suite_cmd = sub.add_parser("run-suite")
    suite_cmd.add_argument("--out")
    suite_cmd.add_argument("suite_command", nargs=argparse.REMAINDER)
    suite_cmd.set_defaults(func=cmd_run_suite)

    class_cmd = sub.add_parser("classify-failure")
    class_cmd.add_argument("--log", required=True)
    class_cmd.set_defaults(func=cmd_classify)

    read_cmd = sub.add_parser("readback")
    read_cmd.set_defaults(func=cmd_readback)

    marker_cmd = sub.add_parser("apply-merge")
    marker_cmd.add_argument("--receipt", required=True)
    marker_cmd.set_defaults(func=cmd_post_marker)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
