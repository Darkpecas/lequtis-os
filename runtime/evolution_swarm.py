#!/usr/bin/env python3
"""Read-only change triage for a future LeQutis evolution assistant.

This is a local deterministic prototype, not an autonomous AI or a live guard.
It compares a pinned Git commit with the current checkout and reports changes
for independent review. It never decides whether a change is safe.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def classify(path: str) -> list[str]:
    areas = []
    if path.startswith(("core/", "database/")):
        areas.append("kernel_and_state")
    if path.startswith(("runtime/", "run.sh")):
        areas.append("runtime_and_integration")
    if path.startswith(("tests/", "eval/")):
        areas.append("verification")
    if path.startswith(("knowledge/", "docs/")) or path in ("README.md", "AGENTS.md"):
        areas.append("identity_and_documentation")
    return areas or ["other"]


def scan(root: Path, baseline: str) -> dict:
    # Resolve first: output records the immutable commit, not a moving branch.
    base = git(root, "rev-parse", "--verify", f"{baseline}^{{commit}}").decode().strip()
    head = git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    committed = git(root, "diff", "--name-only", "-z", base, head, "--").split(b"\0")
    worktree = git(root, "diff", "--name-only", "-z", "HEAD", "--").split(b"\0")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    changes: dict[str, set[str]] = {}
    for scope, items in (("committed", committed), ("worktree", worktree), ("untracked", untracked)):
        for raw in items:
            if raw:
                changes.setdefault(raw.decode("utf-8", errors="surrogateescape"), set()).add(scope)
    findings = [{"path": path, "scopes": sorted(scopes), "review_areas": classify(path)}
                for path, scopes in sorted(changes.items())]
    return {"baseline_commit": base, "head_commit": head,
            "status": "review_required" if findings else "no_file_changes_detected",
            "findings": findings, "verdict": "not_assessed",
            "limitations": ["File changes are review signals, not proof of semantic drift or safety.",
                            "Ignored files, runtime state and live services are not inspected.",
                            "No tests are run and no changes are approved or applied."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--baseline", required=True, help="trusted Git commit to compare")
    args = parser.parse_args()
    try:
        print(json.dumps(scan(args.repo, args.baseline), indent=2, ensure_ascii=True))
    except (OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "blocked", "reason": type(exc).__name__, "verdict": "not_assessed"}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
