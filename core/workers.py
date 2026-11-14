#!/usr/bin/env python3
"""
Replaceable cognitive workers for THINK / CHOOSE.

LeQutis remains sovereign. Workers propose and rank; they never own
identity, memory, agenda, or ACT. Unknown / unsafe proposals fall back
to the deterministic policy so disposable tests stay stable.

Env:
  LEQUTIS_WORKER=deterministic|script|openai   (default: deterministic)
  LEQUTIS_WORKER_SCRIPT=/path/to/worker.py     (stdin JSON → stdout JSON)
  LEQUTIS_WORKER_URL=https://.../v1/chat/completions
  LEQUTIS_WORKER_MODEL=...
  LEQUTIS_WORKER_API_KEY=...                   (optional; never logged)
  LEQUTIS_WORKER_TIMEOUT_SEC=20
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from typing import Any, Protocol

SAFE_ACTIONS = frozenset(
    {"inspect_status", "store_note", "ping", "deliberate_fail"}
)
SAFE_KINDS = frozenset({"recover", "resume", "goal", "idle"})


class CognitiveWorker(Protocol):
    name: str

    def propose(self, noticed: dict[str, Any]) -> list[dict[str, Any]] | None:
        """THINK proposals, or None to defer to deterministic."""

    def select(self, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        """CHOOSE among candidates, or None to defer to deterministic."""


def _kind_order(kind: str) -> int:
    return {"recover": 0, "resume": 1, "goal": 2, "idle": 3}.get(kind, 9)


def deterministic_propose(noticed: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for task in noticed.get("unfinished_tasks") or []:
        if task["status"] == "failed":
            candidates.append(
                {
                    "kind": "recover",
                    "task_id": task["id"],
                    "action": "inspect_status",
                    "agenda_id": None,
                    "reason": "recover_failed_task",
                    "idempotency_key": f"recover:{task['id']}",
                    "payload": {},
                }
            )
        elif task["status"] in ("pending", "running"):
            candidates.append(
                {
                    "kind": "resume",
                    "task_id": task["id"],
                    "action": task["action"],
                    "agenda_id": None,
                    "reason": "resume_unfinished",
                    "idempotency_key": task["idempotency_key"],
                    "payload": {},
                }
            )

    for goal in noticed.get("open_goals") or []:
        title = goal["title"].lower()
        if "fail" in title or "recovery" in title:
            action = "deliberate_fail"
            payload: dict[str, Any] = {}
        elif "note" in title or "remember" in title or "memory" in title:
            action = "store_note"
            payload = {"note": f"Loop progress on: {goal['title']}"}
        else:
            action = "inspect_status"
            payload = {}
        candidates.append(
            {
                "kind": "goal",
                "task_id": None,
                "action": action,
                "agenda_id": goal["id"],
                "reason": "advance_open_goal",
                "idempotency_key": f"goal:{goal['id']}:{action}",
                "payload": payload,
                "title": goal["title"],
            }
        )

    if not candidates:
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).isoformat()
        candidates.append(
            {
                "kind": "idle",
                "task_id": None,
                "action": "ping",
                "agenda_id": None,
                "reason": "no_open_work",
                "idempotency_key": f"idle-ping:{ts[:13]}",
                "payload": {"echo": "idle"},
                "title": "idle heartbeat",
            }
        )
    return candidates


def deterministic_select(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(candidates, key=lambda c: _kind_order(c.get("kind", "")))[0]


def sanitize_candidate(raw: dict[str, Any], noticed: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action") or "")
    kind = str(raw.get("kind") or "goal")
    if action not in SAFE_ACTIONS or kind not in SAFE_KINDS:
        return None
    noticed_tasks = {
        str(t.get("id")): t for t in noticed.get("unfinished_tasks") or []
    }
    requested_task_id = str(raw.get("task_id") or "")
    if kind == "resume" and requested_task_id not in noticed_tasks:
        return None
    resume_task = noticed_tasks.get(requested_task_id) if kind == "resume" else None
    if resume_task and action != resume_task.get("action"):
        return None
    out = {
        "kind": kind,
        "task_id": raw.get("task_id"),
        "action": action,
        "agenda_id": raw.get("agenda_id"),
        "reason": str(raw.get("reason") or f"worker:{kind}"),
        "idempotency_key": (
            str(resume_task.get("idempotency_key"))
            if resume_task
            else str(
                raw.get("idempotency_key")
                or f"worker:{kind}:{action}:{raw.get('agenda_id') or raw.get('task_id') or 'x'}"
            )
        ),
        "payload": raw.get("payload") if isinstance(raw.get("payload"), dict) else {},
    }
    if raw.get("title"):
        out["title"] = str(raw["title"])
    # Prefer known agenda/task ids from noticed when provided.
    goal_ids = {g["id"] for g in noticed.get("open_goals") or []}
    task_ids = {t["id"] for t in noticed.get("unfinished_tasks") or []}
    if out["agenda_id"] and out["agenda_id"] not in goal_ids:
        out["agenda_id"] = None
    if out["task_id"] and out["task_id"] not in task_ids:
        out["task_id"] = None
    return out


def sanitize_proposals(
    proposals: list[Any], noticed: dict[str, Any]
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in proposals or []:
        c = sanitize_candidate(item, noticed)
        if c:
            cleaned.append(c)
    return cleaned


class DeterministicWorker:
    name = "deterministic"

    def propose(self, noticed: dict[str, Any]) -> list[dict[str, Any]] | None:
        return deterministic_propose(noticed)

    def select(self, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        return deterministic_select(candidates)


class ScriptWorker:
    """External JSON worker: stdin request → stdout {candidates|choice}."""

    name = "script"

    def __init__(self, script: str, timeout: float = 20.0) -> None:
        self.script = script
        self.timeout = timeout

    def _call(self, phase: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        req = json.dumps({"phase": phase, **payload}, sort_keys=True).encode()
        try:
            proc = subprocess.run(
                [os.environ.get("LEQUTIS_WORKER_PYTHON", "python3"), self.script],
                input=req,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        try:
            return json.loads(proc.stdout.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return None

    def propose(self, noticed: dict[str, Any]) -> list[dict[str, Any]] | None:
        data = self._call("think", {"noticed": noticed})
        if not data or "candidates" not in data:
            return None
        cleaned = sanitize_proposals(data["candidates"], noticed)
        return cleaned or None

    def select(self, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        data = self._call("choose", {"candidates": candidates})
        if not data or "choice" not in data:
            return None
        # Choice must be one of the offered candidates (by idempotency_key).
        choice = data["choice"]
        if not isinstance(choice, dict):
            return None
        key = choice.get("idempotency_key")
        for c in candidates:
            if c.get("idempotency_key") == key:
                return c
        # Or exact action+kind match among candidates
        for c in candidates:
            if c.get("action") == choice.get("action") and c.get("kind") == choice.get(
                "kind"
            ):
                return c
        return None


class OpenAICompatibleWorker:
    """Optional HTTP chat-completions worker. Failures → deterministic fallback."""

    name = "openai"

    def __init__(
        self,
        url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.url = url
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def _chat(self, system: str, user: str) -> dict[str, Any] | None:
        from credit_manager import CreditManager

        manager = CreditManager()
        reservation = manager.reserve_request(
            "openai-compatible", self.model, len(user)
        )
        if reservation is None:
            return None
        request_id = reservation["request_id"]
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": reservation["max_output_tokens"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — provider failures use deterministic fallback
            manager.finish_request(
                request_id,
                "openai-compatible",
                self.model,
                "request_failed",
                error_type=type(exc).__name__,
            )
            return None
        try:
            content = raw["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            manager.finish_request(
                request_id,
                "openai-compatible",
                self.model,
                "invalid_response",
                usage=raw.get("usage") if isinstance(raw, dict) else None,
            )
            return None
        if not isinstance(parsed, dict):
            manager.finish_request(
                request_id,
                "openai-compatible",
                self.model,
                "invalid_response",
                usage=raw.get("usage") if isinstance(raw, dict) else None,
            )
            return None
        recorded = manager.finish_request(
            request_id,
            "openai-compatible",
            self.model,
            "response_received",
            usage=raw.get("usage") if isinstance(raw, dict) else None,
        )
        return parsed if recorded else None

    def propose(self, noticed: dict[str, Any]) -> list[dict[str, Any]] | None:
        system = (
            "You are a replaceable LeQutis cognitive worker. Propose candidates "
            "as JSON {\"candidates\":[...]} using ONLY actions "
            f"{sorted(SAFE_ACTIONS)} and kinds {sorted(SAFE_KINDS)}. "
            "Do not invent system commands."
        )
        data = self._chat(system, json.dumps({"noticed": noticed}, sort_keys=True))
        if not data:
            return None
        cleaned = sanitize_proposals(data.get("candidates") or [], noticed)
        return cleaned or None

    def select(self, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        system = (
            "Select exactly one candidate. Reply JSON {\"choice\":{...}} using an "
            "idempotency_key from the provided candidates. Prefer recover > resume > goal > idle."
        )
        data = self._chat(system, json.dumps({"candidates": candidates}, sort_keys=True))
        if not data or not isinstance(data.get("choice"), dict):
            return None
        key = data["choice"].get("idempotency_key")
        for c in candidates:
            if c.get("idempotency_key") == key:
                return c
        return None


def get_worker() -> CognitiveWorker:
    kind = (os.environ.get("LEQUTIS_WORKER") or "deterministic").strip().lower()
    timeout = float(os.environ.get("LEQUTIS_WORKER_TIMEOUT_SEC") or "20")
    if kind == "script":
        script = os.environ.get("LEQUTIS_WORKER_SCRIPT") or ""
        if script:
            return ScriptWorker(script, timeout=timeout)
    if kind in ("openai", "http", "llm"):
        url = os.environ.get("LEQUTIS_WORKER_URL") or ""
        model = os.environ.get("LEQUTIS_WORKER_MODEL") or "gpt-4o-mini"
        if url:
            return OpenAICompatibleWorker(
                url=url,
                model=model,
                api_key=os.environ.get("LEQUTIS_WORKER_API_KEY"),
                timeout=timeout,
            )
    return DeterministicWorker()
