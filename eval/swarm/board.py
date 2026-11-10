"""One shared SQLite board. Leases are the kernel's, via the kernel CLI.

Arm D's workers pull with ``claim`` and no agenda id. That is decentralized
task allocation on a single database. It is not partition-tolerant infrastructure:
a live process keeps its lease until that process dies.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / "core" / "lequtis.py"


class BoardError(RuntimeError):
    pass


class KernelBoard:
    def __init__(self, db: Path) -> None:
        self.db = Path(db)
        self.db.parent.mkdir(parents=True, exist_ok=True)
        proc = self._run(["init"])
        if proc.returncode != 0:
            raise BoardError(proc.stdout + proc.stderr)

    def _env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LEQUTIS_DB": str(self.db),
            "LEQUTIS_STATE": str(self.db.parent),
            "LEQUTIS_ROOT": str(ROOT),
            "LEQUTIS_ARTIFACT_ROOT": str(self.db.parent / "artifacts"),
        }
        if extra:
            env.update(extra)
        return env

    def _run(self, args: list[str], extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, str(KERNEL), *args],
            env=self._env(extra),
            text=True,
            capture_output=True,
            timeout=30,
        )
        return proc

    def _json(self, args: list[str], *, expected: int = 0) -> dict[str, Any]:
        proc = self._run(args)
        if proc.returncode != expected:
            raise BoardError(
                f"{args} exited {proc.returncode}, expected {expected}\n{proc.stdout}\n{proc.stderr}"
            )
        if not proc.stdout.strip():
            raise BoardError(f"{args} produced no JSON\n{proc.stderr}")
        return json.loads(proc.stdout)

    def add_goal(self, packet_id: str) -> str:
        proc = self._run(["goal", "--key", packet_id, "propose: " + packet_id])
        if proc.returncode != 0:
            raise BoardError(proc.stdout + proc.stderr)
        with sqlite3.connect(self.db) as con:
            row = con.execute(
                "SELECT id FROM agenda WHERE idempotency_key=?",
                (packet_id,),
            ).fetchone()
        if row is None:
            raise BoardError("goal did not create " + packet_id)
        return row[0]

    def claim(self, agenda_id: str | None = None) -> dict[str, Any]:
        args = ["claim"] if agenda_id is None else ["claim", agenda_id]
        return self._json(args)

    def claim_and_hold(self, pause: Path) -> tuple[subprocess.Popen[str], dict[str, Any]]:
        pause.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, str(KERNEL), "claim"],
            env=self._env({"LEQUTIS_PAUSE_AFTER_CLAIM": str(pause)}),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        claimed = pause / "claimed"
        deadline = time.time() + 15
        while time.time() < deadline and not claimed.exists():
            if proc.poll() is not None:
                stdout, stderr = proc.communicate(timeout=5)
                raise BoardError(f"claim exited before pause\n{stdout}\n{stderr}")
            time.sleep(0.02)
        if not claimed.exists():
            proc.kill()
            raise BoardError("claim did not pause")
        return proc, json.loads(claimed.read_text(encoding="utf-8"))

    def commit(self, execution_id: str, lease_token: str, result: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
        proc = self._run(["commit", execution_id, lease_token, payload])
        if not proc.stdout.strip():
            raise BoardError(proc.stderr)
        body = json.loads(proc.stdout)
        body["returncode"] = proc.returncode
        return body

    def cancel_execution(self, execution_id: str, key: str) -> dict[str, Any]:
        return self._json(["cancel", "--key", key, "execution", execution_id])

    def recover(self) -> dict[str, Any]:
        return self._json(["recover"])

    def retry(self, agenda_id: str) -> subprocess.CompletedProcess[str]:
        return self._run(["retry", agenda_id])

    def execution(self, execution_id: str) -> sqlite3.Row:
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT * FROM executions WHERE id=?", (execution_id,)).fetchone()
            body = None if row is None else dict(row)
        finally:
            con.close()
        if body is None:
            raise BoardError("missing execution " + execution_id)
        return body
