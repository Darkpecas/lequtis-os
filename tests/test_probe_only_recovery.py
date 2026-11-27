"""Disposable subprocess regression: never access production DB."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "runtime/hermes-stdio-connector"

def test_probe_only(tmp_path):
    env = dict(os.environ, LEQUTIS_PROBE_ONLY="1", LEQUTIS_ROOT=str(tmp_path),
               LEQUTIS_STATE=str(tmp_path / "state"), LEQUTIS_HERMES_QUERY="1",
               LEQUTIS_CANONICAL_WRITE="1", LEQUTIS_WRITE_PRINCIPAL="fixture",
               LEQUTIS_TRUSTED_LOCAL_TRANSPORT="1", LEQUTIS_HERMES_BIN=sys.executable)
    requests = [{"jsonrpc":"2.0","id":1,"method":"tools/list"}]
    for i, name in enumerate(["lequtis_status","lequtis_verify_events","hermes_query",
                              "lequtis_canonical_write","lequtis_canonical_read","unknown"], 2):
        requests.append({"jsonrpc":"2.0","id":i,"method":"tools/call","params":{"name":name}})
    requests.append({"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"hermes_probe"}})
    proc = subprocess.run([sys.executable,str(ADAPTER/"lequtis_mcp_stdio.py")],
                          input="".join(json.dumps(r)+"\n" for r in requests),
                          text=True,capture_output=True,env=env,check=True,timeout=20)
    replies = [json.loads(line)["result"] for line in proc.stdout.splitlines()]
    assert [t["name"] for t in replies[0]["tools"]] == ["hermes_probe"]
    assert all(r["structuredContent"]["reason"] == "probe_scope_denied" for r in replies[1:7])
    assert replies[7]["structuredContent"]["ok"]
    assert not replies[7]["structuredContent"]["live_host"]
    pre = subprocess.run([sys.executable,str(ADAPTER/"host_preflight.py"),"--json"],
                         text=True,capture_output=True,env=env,check=True,timeout=20)
    report = json.loads(pre.stdout)
    assert report["db"]["skipped"] and report["core"]["skipped"]
    assert not report["live_host"]
    assert not (tmp_path/"state").exists()
