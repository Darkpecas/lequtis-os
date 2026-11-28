import json, os, pathlib, subprocess, sys, tempfile, unittest
HERE = pathlib.Path(__file__).resolve().parents[1]
class ProbeOnly(unittest.TestCase):
    def test_scope_and_no_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, LEQUTIS_PROBE_ONLY="1", LEQUTIS_ROOT=tmp,
                       LEQUTIS_STATE=tmp, LEQUTIS_HERMES_QUERY="1",
                       LEQUTIS_CANONICAL_WRITE="1", LEQUTIS_WRITE_PRINCIPAL="fixture",
                       LEQUTIS_TRUSTED_LOCAL_TRANSPORT="1", LEQUTIS_HERMES_BIN=sys.executable)
            names = ["lequtis_status","lequtis_verify_events","hermes_query",
                     "lequtis_canonical_write","lequtis_canonical_read","unknown"]
            msgs = [{"jsonrpc":"2.0","id":0,"method":"tools/list"}]
            msgs += [{"jsonrpc":"2.0","id":i+1,"method":"tools/call","params":{"name":n}} for i,n in enumerate(names)]
            msgs += [{"jsonrpc":"2.0","id":99,"method":"tools/call","params":{"name":"hermes_probe"}}]
            p = subprocess.run([sys.executable,str(HERE/"lequtis_mcp_stdio.py")],env=env,input="".join(json.dumps(m)+"\n" for m in msgs),text=True,capture_output=True,check=True,timeout=15)
            replies = [json.loads(x)["result"] for x in p.stdout.splitlines()]
            self.assertEqual([t["name"] for t in replies[0]["tools"]],["hermes_probe"])
            for r in replies[1:-1]:
                self.assertEqual(r["structuredContent"]["reason"],"probe_only")
            self.assertTrue(replies[-1]["structuredContent"]["ok"])
            self.assertFalse(replies[-1]["structuredContent"]["live_host"])
            p = subprocess.run([sys.executable,str(HERE/"host_preflight.py"),"--json"],env=env,text=True,capture_output=True,check=True,timeout=15)
            r = json.loads(p.stdout)
            self.assertTrue(r["db"]["skipped"])
            self.assertTrue(r["core"]["skipped"])
            self.assertEqual(list(pathlib.Path(tmp).iterdir()),[])
if __name__ == "__main__": unittest.main()
