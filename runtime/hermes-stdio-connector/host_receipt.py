#!/usr/bin/env python3
"""Read-only LeQutis host receipt. Never asserts remote reachability or live loop completion."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

def probe_command(argv: list[str], timeout: int = 5) -> dict:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        return {"ok": proc.returncode == 0, "exit_code": proc.returncode,
                "value": proc.stdout.strip().splitlines()[0][:180] if proc.stdout.strip() else None}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": type(exc).__name__}

def git_revision(root: Path) -> dict:
    if not (root / '.git').exists():
        return {"ok": False, "reason": "no_git_checkout"}
    result = probe_command(['git', '-C', str(root), 'rev-parse', 'HEAD'])
    val = result.get('value')
    if not (result['ok'] and val and len(val) == 40 and all(c in '0123456789abcdef' for c in val)):
        return {"ok": False, "reason": "git_head_unavailable"}
    return {"ok": True, "commit": val}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Read-only local host evidence receipt')
    parser.add_argument('--root', type=Path, default=ROOT, help='Existing LeQutis repository root')
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    preflight = root / 'runtime' / 'hermes-stdio-connector' / 'host_preflight.py'
    hermes = shutil.which(os.environ.get('LEQUTIS_HERMES_BIN', 'hermes'))
    report = {
        'schema': 'lequtis.host_receipt.v1',
        'captured_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'scope': 'local_read_only',
        'live_host_verified': False,
        'sovereign_loop_verified': False,
        'git': git_revision(root),
        'core_present': (root / 'core' / 'lequtis.py').is_file(),
        'preflight_present': preflight.is_file(),
        'preflight_sha256': hashlib.sha256(preflight.read_bytes()).hexdigest() if preflight.is_file() else None,
        'hermes_binary_present': hermes is not None,
        'hermes_version': probe_command([hermes, '--version']) if hermes else {"ok": False, "reason": "not_found"},
    }
    if preflight.is_file():
        p = probe_command(['python3', str(preflight), '--json'], timeout=10)
        # Avoid saving the full host-local report which can contain sensitive paths.
        report['preflight'] = {'ok': p['ok'], 'exit_code': p.get('exit_code'), 'error': p.get('error')}
    else:
        report['preflight'] = {'ok': False, 'reason': 'not_found'}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0  # Collection succeeds even if prerequisites fail; result is in JSON.

if __name__ == '__main__':
    raise SystemExit(main())
