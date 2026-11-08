#!/usr/bin/env python3
"""Independent verifier for one kernel execution.

LOCAL PROOF, NOT LIVE VPS VERIFIED.

The verdict is the file under the allowlisted artifact root. This process
does not read claimed_verdict or any worker self-report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"
ARTIFACT_NAME = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$"
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_allowlisted(root: Path, relpath: str) -> Path:
    if not isinstance(relpath, str) or ARTIFACT_NAME.fullmatch(relpath) is None:
        raise ValueError("artifact path is not allowlisted")
    base = root.resolve()
    link = base / relpath
    if link.is_symlink():
        raise ValueError("artifact path is a symlink")
    candidate = link.resolve()
    candidate.relative_to(base)
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--challenge", required=True)
    args = parser.parse_args(argv)
    db_path = Path(args.db)
    if not db_path.is_file():
        sys.stderr.write("database does not exist\n")
        return 2
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM executions WHERE id=?", (args.execution_id,)).fetchone()
        reasons: list[str] = []
        digest = None
        artifact_path = None
        verdict = "rejected"
        correlation = None if row is None else row["correlation_id"]
        if row is None:
            reasons.append("missing_execution")
        elif row["verifier_challenge"] != args.challenge:
            reasons.append("challenge_mismatch")
        elif row["status"] != "running":
            reasons.append("execution_not_running")
        else:
            try:
                path = resolve_allowlisted(Path(args.artifact_root), row["artifact_relpath"])
            except ValueError as exc:
                reasons.append("path_rejected")
                path = None
            if path is not None:
                artifact_path = str(path)
                if not path.is_file():
                    reasons.append("artifact_missing")
                else:
                    data = path.read_bytes()
                    digest = hashlib.sha256(data).hexdigest()
                    try:
                        parsed = json.loads(data.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        parsed = None
                    if digest != row["expected_sha256"]:
                        reasons.append("content_hash_mismatch")
                    if not isinstance(parsed, dict) or parsed.get("correlation_id") != row["correlation_id"]:
                        reasons.append("correlation_mismatch")
                    if not isinstance(parsed, dict) or parsed.get("evidence_label") != EVIDENCE_LABEL:
                        reasons.append("label_mismatch")
                    if not reasons:
                        verdict = "accepted"
        observation_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO verifier_observations
               (id,execution_id,correlation_id,artifact_path,content_sha256,verdict,reason,
                verifier_pid,worker_self_report_consulted,created)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (observation_id, args.execution_id, correlation, artifact_path, digest, verdict,
             "ok" if verdict == "accepted" else ",".join(reasons), os.getpid(), 0, now()),
        )
        db.execute("COMMIT")
    except Exception as exc:
        try:
            db.execute("ROLLBACK")
        except sqlite3.DatabaseError:
            pass
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 3
    finally:
        db.close()
    sys.stdout.write(json.dumps({
        "artifact_path": artifact_path,
        "content_sha256": digest,
        "correlation_id": correlation,
        "evidence_label": EVIDENCE_LABEL,
        "execution_id": args.execution_id,
        "observation_id": observation_id,
        "reason": "ok" if verdict == "accepted" else ",".join(reasons),
        "verdict": verdict,
        "verifier_pid": os.getpid(),
        "worker_self_report_consulted": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
