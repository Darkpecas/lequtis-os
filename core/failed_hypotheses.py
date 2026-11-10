#!/usr/bin/env python3
"""Append-only loader for knowledge/FAILED_HYPOTHESES.jsonl.

Past lines are hash-chained. The loader has no edit or delete operation.
A proposed body that changes or drops an existing line is refused.
Truncation of the tail is refused when the caller still holds the previous tip.

LOCAL PROOF, NOT LIVE VPS VERIFIED.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

GENESIS = "GENESIS"
EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"
FIELDS = ("id", "recorded", "statement", "source")
ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")


class RegistryError(Exception):
    """An edit, deletion, or broken chain was refused."""


def registry_path(root: Path | None = None) -> Path:
    base = root if root is not None else Path(__file__).resolve().parents[1]
    return base / "knowledge" / "FAILED_HYPOTHESES.jsonl"


def _canonical(body: dict[str, str]) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _entry_hash(prev_hash: str, body: dict[str, str]) -> str:
    raw = prev_hash + "|" + _canonical(body)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _check_body(record: dict[str, Any]) -> dict[str, str]:
    if set(record) != set(FIELDS):
        raise RegistryError("record must contain only id, recorded, statement, source")
    cleaned: dict[str, str] = {}
    for key in FIELDS:
        value = record[key]
        if not isinstance(value, str) or not value.strip():
            raise RegistryError(key + " must be a non-empty string")
        cleaned[key] = value
    if ID_RE.fullmatch(cleaned["id"]) is None:
        raise RegistryError("id is not a hypothesis identifier")
    return cleaned


def parse_registry(raw: bytes) -> list[dict[str, Any]]:
    """Verify a byte image. An empty image is a valid empty registry."""
    if raw == b"":
        return []
    if not raw.endswith(b"\n") or b"\n\n" in raw:
        raise RegistryError("registry lines are not intact")
    text = raw.decode("utf-8")
    records: list[dict[str, Any]] = []
    previous = GENESIS
    for number, line in enumerate(text.splitlines(), 1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RegistryError(f"line {number} is not json") from exc
        if not isinstance(obj, dict):
            raise RegistryError(f"line {number} is not an object")
        try:
            body = {key: obj[key] for key in FIELDS}
        except KeyError as exc:
            raise RegistryError(f"line {number} is missing {exc.args[0]}") from exc
        if set(obj) != set(FIELDS) | {"prev_hash", "entry_hash"}:
            raise RegistryError(f"line {number} has unexpected fields")
        _check_body(body)
        digest = _entry_hash(previous, body)
        if obj.get("prev_hash") != previous or obj.get("entry_hash") != digest:
            raise RegistryError(f"chain broken at line {number}")
        records.append(obj)
        previous = digest
    return records


def assert_extension(before: bytes, after: bytes) -> None:
    """Refuse any body that is not the previous bytes plus new complete lines."""
    if not after.startswith(before):
        raise RegistryError("edits and deletions of past entries are refused")
    if before and not before.endswith(b"\n"):
        raise RegistryError("existing registry is not line-terminated")
    extra = after[len(before):]
    if extra and (not extra.endswith(b"\n") or b"\n\n" in extra):
        raise RegistryError("appended records must be complete lines")
    parse_registry(after)


def tip_of(records: list[dict[str, Any]]) -> str:
    if not records:
        return GENESIS
    return str(records[-1]["entry_hash"])


def load(path: Path, expected_tip: str | None = None) -> list[dict[str, Any]]:
    raw = path.read_bytes() if path.exists() else b""
    if path.exists() and path.is_symlink():
        raise RegistryError("refusing to read a symlinked registry")
    records = parse_registry(raw)
    if expected_tip is not None and expected_tip != tip_of(records):
        raise RegistryError("tip mismatch; deletion or substitution refused")
    return records


def append(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Append one record. Hashes are assigned here and cannot be supplied."""
    if "prev_hash" in record or "entry_hash" in record:
        raise RegistryError("hashes are assigned by the registry")
    body = _check_body(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise RegistryError("refusing to append through a symlink")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o644)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        before = b"".join(chunks)
        records = parse_registry(before)
        if any(item["id"] == body["id"] for item in records):
            raise RegistryError("duplicate hypothesis id")
        previous = tip_of(records)
        stored = {
            **body,
            "entry_hash": _entry_hash(previous, body),
            "prev_hash": previous,
        }
        line = (_canonical(stored) + "\n").encode("utf-8")
        os.lseek(fd, 0, os.SEEK_END)
        os.write(fd, line)
        os.fsync(fd)
    except Exception:
        raise
    finally:
        os.close(fd)
    return stored


def delete(path: Path, entry_id: str) -> None:
    """Deletions are refused. The path is not opened for writing."""
    raise RegistryError("deletions are refused: " + entry_id)


def replace(path: Path, entry_id: str, record: dict[str, Any]) -> None:
    """Edits of past entries are refused. The path is not opened for writing."""
    raise RegistryError("edits are refused: " + entry_id)
