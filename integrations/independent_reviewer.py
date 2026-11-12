#!/usr/bin/env python3
"""Subordinate reviewer. It sees a diff and acceptance criteria, nothing else.

LeQutis remains the authority. This process posts a COMMENT review. It does
not approve, and it has no repository write path. A missing
LEQUTIS_REVIEWER_API_KEY fails closed and does not call a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

SCHEMA = "lequtis.independent_review.v1"
SECRET_NAME = "LEQUTIS_REVIEWER_API_KEY"
DEFAULT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"
MAX_DIFF = 120000
PACKET_KEYS = frozenset({"acceptance_criteria", "diff"})
FAIL_CLOSED = (
    "INDEPENDENT REVIEW FAIL-CLOSED: required Actions secret "
    "LEQUTIS_REVIEWER_API_KEY is absent. Auto-merge is blocked."
)
SYSTEM = (
    "You are a subordinate code reviewer for LeQutis. You are not the merge "
    "authority. You will receive only a unified diff and the acceptance "
    "criteria. Reply with one JSON object and no other text: "
    '{"verdict":"pass"|"block","in_scope":true|false,'
    '"findings":[{"severity":"blocking"|"note","summary":"..."}]} . '
    "Pass only when the diff is in scope for those criteria and shows no "
    "secret material, destructive operation, or unsupported completion claim."
)

Transport = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


def build_packet(diff: str, acceptance_criteria: str) -> dict[str, str]:
    if not isinstance(diff, str) or not isinstance(acceptance_criteria, str):
        raise TypeError("packet fields must be strings")
    shown, _truncated = _bound_diff(diff)
    return {"acceptance_criteria": acceptance_criteria, "diff": shown}


def render_prompt(packet: Mapping[str, str]) -> str:
    if set(packet) != PACKET_KEYS:
        raise ValueError("reviewer packet must contain only the diff and acceptance criteria")
    criteria = packet["acceptance_criteria"].strip() or "(none)"
    return "DIFF:\n" + packet["diff"] + "\nACCEPTANCE CRITERIA:\n" + criteria + "\n"


def outbound_messages(packet: Mapping[str, str]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": render_prompt(packet)},
    ]


def _bound_diff(diff: str) -> tuple[str, bool]:
    if len(diff) <= MAX_DIFF:
        return diff, False
    return diff[:MAX_DIFF] + "\n[truncated]\n", True


def _finding(severity: str, summary: str) -> dict[str, str]:
    return {"severity": severity, "summary": summary[:500]}


def _base_result(diff: str, truncated: bool) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "verdict": "block",
        "in_scope": False,
        "findings": [],
        "secret": {SECRET_NAME: "present" if os.environ.get(SECRET_NAME) else "absent"},
        "diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        "truncated": truncated,
        "packet_keys": sorted(PACKET_KEYS),
    }


def _parse_model_json(content: str) -> dict[str, Any]:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model output has no JSON object")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model output is not an object")
    return parsed


def _from_model(parsed: dict[str, Any]) -> tuple[str, bool, list[dict[str, str]]]:
    verdict = parsed.get("verdict")
    in_scope = parsed.get("in_scope")
    raw = parsed.get("findings") or []
    findings: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw[:20]:
            if not isinstance(item, dict):
                continue
            severity = item.get("severity")
            summary = item.get("summary")
            if severity not in ("blocking", "note") or not isinstance(summary, str):
                continue
            findings.append(_finding(severity, summary))
    if verdict not in ("pass", "block") or not isinstance(in_scope, bool):
        findings.append(_finding("blocking", "reviewer output was not a pass/block verdict"))
        return "fail_closed", False, findings
    if verdict == "pass" and not in_scope:
        findings.append(_finding("blocking", "reviewer did not judge the diff in scope"))
        return "block", False, findings
    return verdict, in_scope, findings


def review(
    diff: str,
    acceptance_criteria: str,
    *,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Return a verdict. Does not read anything except the two arguments."""
    packet = build_packet(diff, acceptance_criteria)
    _shown, truncated = _bound_diff(diff)
    result = _base_result(diff, truncated)
    if not diff.strip():
        result["findings"].append(_finding("blocking", "net diff is empty"))
        result["verdict"] = "block"
    if truncated:
        result["findings"].append(_finding("blocking", "diff truncated before review"))
        result["verdict"] = "block"
    if not os.environ.get(SECRET_NAME):
        result["verdict"] = "fail_closed"
        result["in_scope"] = False
        result["findings"].insert(0, _finding("blocking", FAIL_CLOSED))
        return result
    if result["verdict"] == "block" and (not diff.strip() or truncated):
        return result
    caller = transport or default_transport
    try:
        payload = {
            "model": os.environ.get("LEQUTIS_REVIEWER_MODEL") or DEFAULT_MODEL,
            "temperature": 0,
            "messages": outbound_messages(packet),
        }
        response = caller(
            os.environ.get("LEQUTIS_REVIEWER_API_URL") or DEFAULT_URL,
            payload,
            {},
        )
        content = response["choices"][0]["message"]["content"]
        verdict, in_scope, findings = _from_model(_parse_model_json(content))
    except Exception as exc:  # noqa: BLE001 - fail closed on any model failure
        result["verdict"] = "fail_closed"
        result["in_scope"] = False
        result["findings"].append(_finding("blocking", "reviewer_api_error: " + type(exc).__name__))
        return result
    result["verdict"] = verdict
    result["in_scope"] = in_scope
    result["findings"].extend(findings)
    if truncated or not diff.strip():
        result["verdict"] = "block"
        result["in_scope"] = False
    return result


def default_transport(url: str, payload: dict[str, Any], _headers: dict[str, str]) -> dict[str, Any]:
    key = os.environ.get(SECRET_NAME) or ""
    body = json.dumps(payload).encode("utf-8")
    if key and key.encode("utf-8") in body:
        raise RuntimeError("refusing to send the reviewer key in the request body")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError("http_" + str(exc.code)) from exc


def comment_body(result: dict[str, Any], head_sha: str) -> str:
    public = {
        "diff_sha256": result["diff_sha256"],
        "findings": result["findings"],
        "head_sha": head_sha,
        "in_scope": result["in_scope"],
        "packet_keys": result["packet_keys"],
        "schema": result["schema"],
        "secret": result["secret"],
        "truncated": result["truncated"],
        "verdict": result["verdict"],
    }
    return (
        "<!-- lequtis-independent-review v1 -->\n\n"
        "Subordinate review for LeQutis. This comment is not a merge approval.\n\n"
        "```json\n" + json.dumps(public, indent=2, sort_keys=True) + "\n```\n"
    )


def post_review(repo: str, pr: str, head_sha: str, body: str, token: str) -> None:
    url = "https://api.github.com/repos/" + repo + "/pulls/" + str(pr) + "/reviews"
    payload = json.dumps({"commit_id": head_sha, "event": "COMMENT", "body": body}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff-file", required=True)
    parser.add_argument("--criteria-file", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--pr")
    parser.add_argument("--repo")
    parser.add_argument("--out")
    parser.add_argument("--post", action="store_true")
    args = parser.parse_args(argv)
    diff = open(args.diff_file, encoding="utf-8").read()
    criteria = open(args.criteria_file, encoding="utf-8").read()
    result = review(diff, criteria)
    result["head_sha"] = args.head_sha
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        out = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "w", encoding="utf-8").write(text)
    sys.stdout.write(text)
    if args.post:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        if not token or not args.repo or not args.pr:
            sys.stderr.write("review comment not posted: missing token, repo, or pr\n")
            return 1
        post_review(args.repo, args.pr, args.head_sha, comment_body(result, args.head_sha), token)
    passed = result["verdict"] == "pass" and result["in_scope"] is True
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
