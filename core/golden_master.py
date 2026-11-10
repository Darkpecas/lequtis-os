#!/usr/bin/env python3
"""Seal and verify a SHA-256 manifest of tracked kernel files.

The seal covers git-tracked files under ``core/`` and ``database/schema.sql``.
It does not include itself. Experiments pass ``--root`` pointing at a clone.
An existing seal is never overwritten.

LOCAL PROOF, NOT LIVE VPS VERIFIED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA = "lequtis-golden-master-v1"
EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"
KERNEL_PATHS = ("core", "database/schema.sql")


class GoldenMasterError(Exception):
    """The seal could not be written or the clone is not a git work tree."""


def _canonical(files: list[dict[str, Any]]) -> str:
    return json.dumps(files, sort_keys=True, separators=(",", ":"))


def manifest_sha256(files: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical(files).encode("utf-8")).hexdigest()


def tracked_kernel_files(root: Path) -> list[str]:
    """Return repo-relative paths of tracked kernel files, sorted."""
    if not (root / ".git").exists():
        raise GoldenMasterError("root is not a git work tree: " + str(root))
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", *KERNEL_PATHS],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GoldenMasterError(detail or "git ls-files failed")
    names = [item.decode("utf-8") for item in proc.stdout.split(b"\0") if item]
    return sorted(names)


def build_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    files: list[dict[str, Any]] = []
    for rel in tracked_kernel_files(root):
        path = root / rel
        if path.is_symlink():
            raise GoldenMasterError("refusing to seal a symlink: " + rel)
        if not path.is_file():
            raise GoldenMasterError("tracked kernel path is not a file: " + rel)
        data = path.read_bytes()
        files.append(
            {
                "bytes": len(data),
                "path": rel,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    if not files:
        raise GoldenMasterError("no tracked kernel files under " + ", ".join(KERNEL_PATHS))
    return {
        "algorithm": "sha256",
        "evidence_label": EVIDENCE_LABEL,
        "files": files,
        "kernel_paths": list(KERNEL_PATHS),
        "manifest_sha256": manifest_sha256(files),
        "schema": SCHEMA,
    }


def seal(root: Path, out: Path) -> dict[str, Any]:
    """Write a new seal. Refuse if ``out`` already exists."""
    if out.exists() or out.is_symlink():
        raise GoldenMasterError("refusing to overwrite existing seal: " + str(out))
    document = build_manifest(root)
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(out, flags, 0o444)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise GoldenMasterError("seal write failed")
            view = view[written:]
    except Exception:
        os.close(fd)
        out.unlink(missing_ok=True)
        raise
    os.close(fd)
    os.chmod(out, 0o444)
    return document


def verify(root: Path, seal_path: Path) -> dict[str, Any]:
    """Recompute the clone manifest and compare it to the seal."""
    if seal_path.is_symlink() or not seal_path.is_file():
        return {
            "ok": False,
            "reason": "seal_missing",
            "evidence_label": EVIDENCE_LABEL,
        }
    try:
        sealed = json.loads(seal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "reason": "seal_unreadable",
            "detail": type(exc).__name__,
            "evidence_label": EVIDENCE_LABEL,
        }
    try:
        current = build_manifest(root)
    except GoldenMasterError as exc:
        return {
            "ok": False,
            "reason": "manifest_failed",
            "detail": str(exc),
            "evidence_label": EVIDENCE_LABEL,
        }
    sealed_files = sealed.get("files")
    if (
        sealed.get("schema") != SCHEMA
        or sealed.get("algorithm") != "sha256"
        or not isinstance(sealed_files, list)
        or sealed.get("manifest_sha256") != manifest_sha256(sealed_files)
        or sealed_files != current["files"]
        or sealed.get("manifest_sha256") != current["manifest_sha256"]
    ):
        return {
            "ok": False,
            "reason": "manifest_mismatch",
            "expected": sealed.get("manifest_sha256"),
            "actual": current["manifest_sha256"],
            "evidence_label": EVIDENCE_LABEL,
        }
    return {
        "ok": True,
        "files": len(current["files"]),
        "manifest_sha256": current["manifest_sha256"],
        "evidence_label": EVIDENCE_LABEL,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    seal_cmd = sub.add_parser("seal", help="write a new seal; refuse if it exists")
    seal_cmd.add_argument("--root", required=True, type=Path)
    seal_cmd.add_argument("--out", required=True, type=Path)

    verify_cmd = sub.add_parser("verify", help="check a clone against a seal")
    verify_cmd.add_argument("--root", required=True, type=Path)
    verify_cmd.add_argument("--seal", required=True, type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "seal":
            document = seal(args.root, args.out)
            json.dump(
                {
                    "ok": True,
                    "out": str(args.out),
                    "manifest_sha256": document["manifest_sha256"],
                    "files": len(document["files"]),
                    "evidence_label": EVIDENCE_LABEL,
                },
                sys.stdout,
                indent=2,
                sort_keys=True,
            )
            sys.stdout.write("\n")
            return 0
        result = verify(args.root, args.seal)
    except GoldenMasterError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 2
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
