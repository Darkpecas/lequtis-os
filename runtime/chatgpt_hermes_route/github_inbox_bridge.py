#!/usr/bin/env python3
"""Durable, least-privilege GitHub -> Hermes inbox bridge. Stdlib only.

Pulls explicitly marked GitHub issue comments and writes idempotent JSON
requests into an existing local Hermes/LeQutis inbox. Does NOT execute text.
The Hermes-side dispatcher must authenticate, approve and process separately.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
import urllib.error

MARKER = "/hermes-intake"
MAX_BODY = 16000

def parse_comment(comment, allowed_login):
    if comment.get("user", {}).get("login", "").casefold() != allowed_login.casefold():
        return None
    body = comment.get("body") or ""
    if not body.startswith(MARKER + "\n") or len(body) > MAX_BODY:
        return None
    payload = body[len(MARKER) + 1:].strip()
    if not payload:
        return None
    return {"comment_id": int(comment["id"]), "source_url": comment.get("html_url"),
            "author": allowed_login, "created_at": comment.get("created_at"),
            "instruction": payload, "status": "awaiting_approval",
            "instruction_sha256": hashlib.sha256(payload.encode()).hexdigest()}

def write_intake(inbox, item):
    inbox = Path(inbox)
    if not inbox.is_dir() or inbox.is_symlink():
        raise RuntimeError("inbox_must_preexist_as_real_directory")
    target = inbox / ("github-issue-" + str(item["comment_id"]) + ".json")
    raw = (json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n").encode()
    try:
        fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != raw:
            raise RuntimeError("existing_intake_conflict")
        return False
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    return True

def fetch_comments(repo, issue, token):
    url = "https://api.github.com/repos/" + repo + "/issues/" + str(issue) + "/comments?per_page=100"
    req = urllib.request.Request(url, headers={"Accept":"application/vnd.github+json",
        "Authorization":"Bearer " + token, "User-Agent":"lequtis-hermes-inbox/1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)

def main():
    repo = os.environ.get("LEQUTIS_BRIDGE_REPO", "Darkpecas/lequtis-os")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise RuntimeError("invalid_repository")
    token = os.environ.get("LEQUTIS_GITHUB_READ_TOKEN")
    login = os.environ.get("LEQUTIS_BRIDGE_ALLOWED_LOGIN")
    inbox = os.environ.get("LEQUTIS_BRIDGE_INBOX")
    if not token or not login or not inbox or not re.fullmatch(r"[A-Za-z0-9-]+", login):
        raise RuntimeError("token_allowed_login_and_inbox_required")
    issue = int(os.environ.get("LEQUTIS_BRIDGE_ISSUE", "20"))
    interval = max(30, int(os.environ.get("LEQUTIS_BRIDGE_POLL_SECONDS", "90")))
    while True:
        try:
            count = 0
            for comment in fetch_comments(repo, issue, token):
                item = parse_comment(comment, login)
                if item and write_intake(inbox, item):
                    count += 1
            print(json.dumps({"ok": True, "new_intakes": count, "execution": False}), flush=True)
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            print(json.dumps({"ok": False, "reason": type(exc).__name__}), file=sys.stderr, flush=True)
        if "--once" in sys.argv:
            break
        time.sleep(interval)

if __name__ == "__main__":
    main()
