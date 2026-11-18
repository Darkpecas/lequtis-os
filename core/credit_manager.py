"""Fail-closed request budgeting for hosted cognitive workers.

Usage reservations live in LeQutis's existing event chain. A request is
reserved before network access, so timeouts and malformed replies still use
the configured allowance. This bounds calls and output tokens; it cannot
calculate currency charges because provider pricing and adjustments are
external.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

EVENT_RESERVED = "credit.request_reserved"
EVENT_DENIED = "credit.request_denied"
EVENT_RESULT = "credit.request_result"

MAX_DAILY_REQUESTS = 20
MAX_OUTPUT_TOKENS = 512
MAX_INPUT_CHARS = 32_768


def _setting(name: str, default: int, maximum: int) -> tuple[int, bool]:
    raw = os.environ.get(name)
    if raw is None:
        return default, True
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0, False
    if not 0 <= value <= maximum:
        return 0, False
    return value, True


def settings() -> dict[str, Any]:
    """Return bounded settings; invalid values become a zero allowance."""
    daily, daily_valid = _setting(
        "LEQUTIS_WORKER_MAX_REQUESTS_PER_DAY", 0, MAX_DAILY_REQUESTS
    )
    output, output_valid = _setting(
        "LEQUTIS_WORKER_MAX_OUTPUT_TOKENS", 128, MAX_OUTPUT_TOKENS
    )
    input_chars, input_valid = _setting(
        "LEQUTIS_WORKER_MAX_INPUT_CHARS", 8192, MAX_INPUT_CHARS
    )
    return {
        "max_requests_per_utc_day": daily,
        "max_output_tokens": output,
        "max_input_chars": input_chars,
        "configuration_valid": daily_valid and output_valid and input_valid,
    }


def _lequtis():
    # Import lazily: lequtis imports workers inside THINK/CHOOSE.
    import lequtis

    return lequtis


class CreditManager:
    """Reserve bounded provider requests in the canonical LeQutis ledger."""

    def reserve_request(
        self, provider: str, model: str, input_chars: int
    ) -> dict[str, Any] | None:
        L = _lequtis()
        policy = settings()
        request_id = str(uuid.uuid4())
        utc_day = datetime.now(timezone.utc).date().isoformat()

        try:
            # The autonomous loop initializes LeQutis before THINK/CHOOSE.
            # A standalone worker without that canonical state must fail
            # closed instead of creating a second database implicitly.
            if not L.DB.is_file():
                return None
            with L.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                rows = db.execute(
                    """
                    SELECT seq, ts, event_type, payload, previous_hash, event_hash
                    FROM events ORDER BY seq ASC
                    """
                ).fetchall()
                integrity = L._verify_event_rows(rows)
                if not integrity["ok"]:
                    db.rollback()
                    return None

                used = db.execute(
                    """SELECT COUNT(*) FROM events
                       WHERE event_type=? AND substr(ts,1,10)=?""",
                    (EVENT_RESERVED, utc_day),
                ).fetchone()[0]
                reason = None
                if not policy["configuration_valid"]:
                    reason = "invalid_budget_configuration"
                elif policy["max_requests_per_utc_day"] == 0:
                    reason = "external_requests_disabled"
                elif used >= policy["max_requests_per_utc_day"]:
                    reason = "daily_request_limit_reached"
                elif policy["max_output_tokens"] == 0:
                    reason = "output_token_limit_is_zero"
                elif (
                    policy["max_input_chars"] == 0
                    or input_chars > policy["max_input_chars"]
                ):
                    reason = "input_character_limit_reached"

                if reason:
                    L._append_event(
                        db,
                        EVENT_DENIED,
                        {
                            "request_id": request_id,
                            "provider": provider,
                            "model": model,
                            "utc_day": utc_day,
                            "reason": reason,
                            "requests_reserved_today": used,
                            "daily_limit": policy["max_requests_per_utc_day"],
                        },
                    )
                    return None

                L._append_event(
                    db,
                    EVENT_RESERVED,
                    {
                        "request_id": request_id,
                        "provider": provider,
                        "model": model,
                        "utc_day": utc_day,
                        "requests_reserved_today": used + 1,
                        "daily_limit": policy["max_requests_per_utc_day"],
                        "input_chars": int(input_chars),
                        "max_input_chars": policy["max_input_chars"],
                        "max_output_tokens": policy["max_output_tokens"],
                    },
                )
                return {
                    "request_id": request_id,
                    "max_output_tokens": policy["max_output_tokens"],
                }
        except Exception:
            # No provider request is allowed when reservation or integrity
            # accounting cannot complete.
            return None

    def finish_request(
        self,
        request_id: str,
        provider: str,
        model: str,
        outcome: str,
        usage: dict[str, Any] | None = None,
        error_type: str | None = None,
    ) -> bool:
        L = _lequtis()
        usage = usage if isinstance(usage, dict) else {}

        def token_value(*keys: str) -> int | None:
            for key in keys:
                value = usage.get(key)
                if type(value) is int and value >= 0:
                    return value
            return None

        payload = {
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "outcome": outcome,
            "prompt_tokens": token_value("prompt_tokens", "input_tokens"),
            "completion_tokens": token_value("completion_tokens", "output_tokens"),
            "total_tokens": token_value("total_tokens"),
        }
        if error_type:
            payload["error_type"] = str(error_type)[:80]

        try:
            with L.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                rows = db.execute(
                    """
                    SELECT seq, ts, event_type, payload, previous_hash, event_hash
                    FROM events ORDER BY seq ASC
                    """
                ).fetchall()
                if not L._verify_event_rows(rows)["ok"]:
                    db.rollback()
                    return False

                reservation_found = False
                result_found = False
                for row in db.execute(
                    "SELECT event_type,payload FROM events WHERE event_type IN (?,?)",
                    (EVENT_RESERVED, EVENT_RESULT),
                ):
                    try:
                        event_payload = json.loads(row["payload"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if event_payload.get("request_id") != request_id:
                        continue
                    if row["event_type"] == EVENT_RESERVED:
                        reservation_found = True
                    elif row["event_type"] == EVENT_RESULT:
                        result_found = True
                if not reservation_found or result_found:
                    db.rollback()
                    return False

                L._append_event(db, EVENT_RESULT, payload)
                return True
        except Exception:
            return False

    def report(self) -> dict[str, Any]:
        L = _lequtis()
        policy = settings()
        L.init()
        integrity = L.verify_event_chain()
        today = datetime.now(timezone.utc).date().isoformat()
        if not integrity["ok"]:
            return {
                "evidence_label": "LOCAL LEDGER READ; EVENT CHAIN INVALID",
                "event_chain": integrity,
                "policy": policy,
                "today_utc": today,
                "money_cost": "unknown",
            }

        with L.connect() as db:
            rows = db.execute(
                """SELECT event_type,payload FROM events
                   WHERE event_type IN (?,?,?) ORDER BY seq""",
                (EVENT_RESERVED, EVENT_DENIED, EVENT_RESULT),
            ).fetchall()
        reserved = denied = completed = prompt_tokens = completion_tokens = 0
        for row in rows:
            try:
                item = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if item.get("utc_day") == today and row["event_type"] == EVENT_RESERVED:
                reserved += 1
            elif item.get("utc_day") == today and row["event_type"] == EVENT_DENIED:
                denied += 1
            elif row["event_type"] == EVENT_RESULT:
                if item.get("outcome") in ("response_received", "invalid_response"):
                    completed += 1
                prompt_tokens += int(item.get("prompt_tokens") or 0)
                completion_tokens += int(item.get("completion_tokens") or 0)

        return {
            "evidence_label": "LOCAL CANONICAL LEDGER; NOT PROVIDER BILLING DATA",
            "event_chain": integrity,
            "today_utc": today,
            "policy": policy,
            "today": {
                "requests_reserved": reserved,
                "requests_denied": denied,
                "daily_limit_remaining": max(
                    0, policy["max_requests_per_utc_day"] - reserved
                ),
            },
            "observed_token_totals_all_time": {
                "provider_reported_prompt_tokens": prompt_tokens,
                "provider_reported_completion_tokens": completion_tokens,
            },
            "money_cost": "unknown; consult the provider billing dashboard",
        }
