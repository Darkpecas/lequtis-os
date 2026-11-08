import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("arrays", ROOT / "research" / "liquid_neurology_arrays.py")
arrays = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arrays)

class ResearchArraysTest(unittest.TestCase):
    def test_seven_unique_packets(self):
        items = list(arrays.packets("MCP"))
        self.assertEqual(len(items), 7)
        self.assertEqual(len({p["idempotency_key"] for p in items}), 7)
        self.assertTrue(all(p["status"] == "NOT_EXECUTED" for p in items))
    def test_deterministic(self):
        self.assertEqual(list(arrays.packets("x")), list(arrays.packets("x")))
    def test_reject_self_report(self):
        data = dict(status="VERIFIED", idempotency_key="k", primary_sources=["url"],
                    test_observation="PASS", verifier="same", executor="same", evidence_hash="h")
        self.assertFalse(arrays.verify_receipt(data))
        data["verifier"] = "independent"
        self.assertTrue(arrays.verify_receipt(data))
    def test_incomplete_receipt(self):
        self.assertFalse(arrays.verify_receipt({"status": "VERIFIED"}))
if __name__ == "__main__":
    unittest.main()
