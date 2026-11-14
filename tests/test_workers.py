#!/usr/bin/env python3
"""Disposable tests: replaceable THINK/CHOOSE workers; ACT stays registered-safe."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"


def load_L(state: Path):
    os.environ["LEQUTIS_ROOT"] = str(ROOT)
    os.environ["LEQUTIS_STATE"] = str(state)
    os.environ.pop("LEQUTIS_WORKER", None)
    os.environ.pop("LEQUTIS_WORKER_SCRIPT", None)
    sys.path.insert(0, str(CORE))
    sys.modules.pop("lequtis", None)
    sys.modules.pop("workers", None)
    import lequtis as L  # noqa: WPS433

    L.ROOT = ROOT
    L.STATE = state
    L.DB = state / "lequtis.db"
    state.mkdir(parents=True, exist_ok=True)
    L.init()
    return L


def test_deterministic_default(state: Path) -> None:
    print("TEST WORKERS: deterministic default loop still completes")
    L = load_L(state)
    L.add_goal("Inspect kernel status via autonomous loop", priority=50)
    result = L.run_loop(correlation_id="worker-det")
    assert result["status"] == "completed", result
    assert result["evidence"]["phases"]["ACT"]["ok"] is True
    print("  PASS")


def test_script_worker_think_choose(state: Path) -> None:
    print("TEST WORKERS: script worker influences THINK/CHOOSE")
    L = load_L(state)
    script = state / "worker_script.py"
    script.write_text(
        """#!/usr/bin/env python3
import json, sys
req = json.load(sys.stdin)
if req["phase"] == "think":
    goals = req["noticed"].get("open_goals") or []
    g = goals[0] if goals else {"id": None, "title": "x"}
    print(json.dumps({
      "candidates": [{
        "kind": "goal",
        "action": "store_note",
        "agenda_id": g["id"],
        "title": g.get("title"),
        "reason": "script_prefers_note",
        "idempotency_key": f"goal:{g['id']}:store_note",
        "payload": {"note": "from-script-worker"}
      }]
    }))
elif req["phase"] == "choose":
    print(json.dumps({"choice": req["candidates"][0]}))
""",
        encoding="utf-8",
    )
    os.environ["LEQUTIS_WORKER"] = "script"
    os.environ["LEQUTIS_WORKER_SCRIPT"] = str(script)
    sys.modules.pop("workers", None)
    L.add_goal("Remember this note about workers", priority=50)
    result = L.run_loop(correlation_id="worker-script")
    assert result["status"] == "completed", result
    assert result["evidence"]["phases"]["CHOOSE"]["action"] == "store_note"
    # Ensure ACT stayed in registry (store_note).
    assert result["evidence"]["phases"]["ACT"]["ok"] is True
    print("  PASS")


def test_unsafe_worker_proposal_rejected(state: Path) -> None:
    print("TEST WORKERS: unsafe actions rejected → deterministic fallback")
    L = load_L(state)
    script = state / "bad_worker.py"
    script.write_text(
        """#!/usr/bin/env python3
import json, sys
req = json.load(sys.stdin)
if req["phase"] == "think":
    print(json.dumps({"candidates":[{
      "kind":"goal","action":"rm_rf_root","agenda_id":None,
      "idempotency_key":"evil","payload":{}
    }]}))
else:
    print(json.dumps({"choice": req["candidates"][0]}))
""",
        encoding="utf-8",
    )
    os.environ["LEQUTIS_WORKER"] = "script"
    os.environ["LEQUTIS_WORKER_SCRIPT"] = str(script)
    sys.modules.pop("workers", None)
    L.add_goal("Inspect kernel status via autonomous loop", priority=50)
    result = L.run_loop(correlation_id="worker-safe")
    assert result["status"] == "completed", result
    # Must not have executed unknown action.
    assert result["evidence"]["phases"]["CHOOSE"]["action"] in (
        "inspect_status",
        "store_note",
        "ping",
        "deliberate_fail",
    )
    print("  PASS")



def test_store_note_retry_does_not_duplicate_memory(state: Path) -> None:
    print("TEST WORKERS: task retry reuses the same note memory")
    L = load_L(state)
    agenda_id = L.add_goal("Remember a retry-safe note", priority=50)
    choice = {
        "kind": "goal",
        "action": "store_note",
        "agenda_id": agenda_id,
        "title": "Remember a retry-safe note",
        "reason": "idempotency test",
        "idempotency_key": f"goal:{agenda_id}:store_note",
        "payload": {"note": "one memory across retries"},
    }
    with L.connect() as db:
        db.execute(
            """CREATE TRIGGER fail_task_completion
               BEFORE UPDATE ON tasks WHEN NEW.status='completed'
               BEGIN SELECT RAISE(ABORT, 'injected post-action failure'); END"""
        )
    first = L.act(choice)
    assert first["ok"] is False, first
    with L.connect() as db:
        db.execute("DROP TRIGGER fail_task_completion")
    second = L.act(choice)
    assert second["ok"] is True, second
    with L.connect() as db:
        rows = db.execute(
            "SELECT id FROM memory WHERE content=?", ("one memory across retries",)
        ).fetchall()
    assert len(rows) == 1, rows
    print("  PASS")


def test_resume_keeps_existing_task_identity(state: Path) -> None:
    print("TEST WORKERS: resume keeps canonical task key and action")
    sys.path.insert(0, str(CORE))
    import workers

    noticed = {
        "unfinished_tasks": [{
            "id": "task-existing", "status": "pending",
            "action": "store_note", "idempotency_key": "canonical-key",
        }]
    }
    candidate = workers.sanitize_candidate(
        {"kind": "resume", "task_id": "task-existing",
         "action": "store_note", "idempotency_key": "", "payload": {}},
        noticed,
    )
    assert candidate is not None
    assert candidate["idempotency_key"] == "canonical-key"
    assert candidate["task_id"] == "task-existing"
    assert workers.sanitize_candidate(
        {"kind": "resume", "task_id": "task-existing",
         "action": "ping", "idempotency_key": "other"}, noticed,
    ) is None
    print("  PASS")


def test_credit_manager_default_blocks_provider_call(state: Path) -> None:
    print("TEST WORKERS: credit manager blocks HTTP by default")
    L = load_L(state)
    from credit_manager import CreditManager
    from workers import OpenAICompatibleWorker

    with patch.dict(os.environ, {
        "LEQUTIS_WORKER_MAX_REQUESTS_PER_DAY": "0",
        "LEQUTIS_WORKER_MAX_OUTPUT_TOKENS": "128",
        "LEQUTIS_WORKER_MAX_INPUT_CHARS": "8192",
    }):
        worker = OpenAICompatibleWorker("https://provider.invalid/chat", "test-model")
        with patch("workers.urllib.request.urlopen") as urlopen:
            assert worker._chat("system", "user") is None
            urlopen.assert_not_called()
        report = CreditManager().report()
        assert report["today"]["requests_reserved"] == 0, report
        assert report["today"]["requests_denied"] == 1, report
        assert L.verify_event_chain()["ok"] is True
    print("  PASS")


def test_credit_manager_reserves_and_accounts_atomically(state: Path) -> None:
    print("TEST WORKERS: bounded reservations and provider usage receipts")
    L = load_L(state)
    from credit_manager import CreditManager

    with patch.dict(os.environ, {
        "LEQUTIS_WORKER_MAX_REQUESTS_PER_DAY": "1",
        "LEQUTIS_WORKER_MAX_OUTPUT_TOKENS": "128",
        "LEQUTIS_WORKER_MAX_INPUT_CHARS": "8192",
    }):
        manager = CreditManager()
        first = manager.reserve_request("test-provider", "test-model", 100)
        assert first is not None
        second = manager.reserve_request("test-provider", "test-model", 100)
        assert second is None
        assert manager.finish_request(
            first["request_id"], "test-provider", "test-model",
            "response_received",
            usage={"prompt_tokens": 17, "completion_tokens": 23, "total_tokens": 40},
        ) is True
        report = manager.report()
        assert report["today"]["requests_reserved"] == 1, report
        assert report["today"]["requests_denied"] == 1, report
        assert report["observed_token_totals_all_time"] == {
            "provider_reported_prompt_tokens": 17,
            "provider_reported_completion_tokens": 23,
        }, report
        assert L.verify_event_chain()["ok"] is True
    print("  PASS")


def test_credit_manager_concurrent_calls_cannot_exceed_cap(state: Path) -> None:
    print("TEST WORKERS: concurrent provider reservations stay under cap")
    L = load_L(state)
    from credit_manager import CreditManager

    with patch.dict(os.environ, {
        "LEQUTIS_WORKER_MAX_REQUESTS_PER_DAY": "3",
        "LEQUTIS_WORKER_MAX_OUTPUT_TOKENS": "128",
        "LEQUTIS_WORKER_MAX_INPUT_CHARS": "8192",
    }):
        manager = CreditManager()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _index: manager.reserve_request(
                    "test-provider", "test-model", 100
                ),
                range(8),
            ))
        assert sum(item is not None for item in results) == 3, results
        report = manager.report()
        assert report["today"]["requests_reserved"] == 3, report
        assert report["today"]["requests_denied"] == 5, report
        assert L.verify_event_chain()["ok"] is True
    print("  PASS")


def test_credit_manager_http_worker_records_usage(state: Path) -> None:
    print("TEST WORKERS: HTTP request carries token cap and records usage")
    L = load_L(state)
    from credit_manager import CreditManager
    from workers import OpenAICompatibleWorker

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": '{"candidates": []}'}}],
                "usage": {"prompt_tokens": 19, "completion_tokens": 7},
            }).encode("utf-8")

    with patch.dict(os.environ, {
        "LEQUTIS_WORKER_MAX_REQUESTS_PER_DAY": "1",
        "LEQUTIS_WORKER_MAX_OUTPUT_TOKENS": "64",
        "LEQUTIS_WORKER_MAX_INPUT_CHARS": "8192",
    }):
        worker = OpenAICompatibleWorker(
            "https://provider.invalid/chat", "test-model", api_key="do-not-persist-key"
        )
        with patch("workers.urllib.request.urlopen", return_value=Response()) as urlopen:
            assert worker._chat("system", "private-prompt-marker") == {"candidates": []}
            request = urlopen.call_args.args[0]
            body = json.loads(request.data.decode("utf-8"))
            assert body["max_tokens"] == 64, body
            urlopen.assert_called_once()
        report = CreditManager().report()
        assert report["today"]["requests_reserved"] == 1, report
        assert report["observed_token_totals_all_time"] == {
            "provider_reported_prompt_tokens": 19,
            "provider_reported_completion_tokens": 7,
        }, report
        with L.connect() as db:
            payloads = [row[0] for row in db.execute("SELECT payload FROM events")]
        assert all("do-not-persist-key" not in item for item in payloads)
        assert all("private-prompt-marker" not in item for item in payloads)
        assert L.verify_event_chain()["ok"] is True
    print("  PASS")


def test_credit_manager_fails_closed_on_corrupt_chain(state: Path) -> None:
    print("TEST WORKERS: corrupt event chain blocks provider reservation")
    L = load_L(state)
    L.heartbeat()
    with L.connect() as db:
        db.execute("UPDATE events SET payload='{}' WHERE seq=1")
    from credit_manager import CreditManager

    with patch.dict(os.environ, {"LEQUTIS_WORKER_MAX_REQUESTS_PER_DAY": "2"}):
        assert CreditManager().reserve_request("test-provider", "test-model", 100) is None
    assert L.verify_event_chain()["ok"] is False
    print("  PASS")


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="lequtis-workers-"))
    try:
        test_deterministic_default(base / "a")
        test_script_worker_think_choose(base / "b")
        test_unsafe_worker_proposal_rejected(base / "c")
        test_store_note_retry_does_not_duplicate_memory(base / "d")
        test_resume_keeps_existing_task_identity(base / "e")
        test_credit_manager_default_blocks_provider_call(base / "f")
        test_credit_manager_reserves_and_accounts_atomically(base / "g")
        test_credit_manager_concurrent_calls_cannot_exceed_cap(base / "h")
        test_credit_manager_http_worker_records_usage(base / "i")
        test_credit_manager_fails_closed_on_corrupt_chain(base / "j")
        print()
        print("=== LEQUTIS WORKER TESTS: ALL PASS ===")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
