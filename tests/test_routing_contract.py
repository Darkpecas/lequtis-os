"""The routing contract names four tiers and refuses an unverified model."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import routing_contract  # noqa: E402


class RoutingContractTests(unittest.TestCase):
    def test_shipped_contract_has_four_verified_tiers(self):
        document = routing_contract.load(routing_contract.contract_path(ROOT))
        self.assertEqual(
            [tier["id"] for tier in document["tiers"]],
            ["tier0", "tier1", "tier2", "tier3"],
        )
        names = [model["name"] for tier in document["tiers"] for model in tier["models"]]
        self.assertIn("d1-ultra", names)
        self.assertIn("LiquidAI/LFM3-1.7B", names)
        self.assertIn("LiquidAI/LFM2.5-2.6B", names)
        self.assertIn("meta-models/Muse-Glimmer-30B", names)
        self.assertIn("meta-models/Muse-Spark-Open-816B-A42B", names)
        self.assertNotIn("Muse-Spark-Open-816B", names)
        for tier in document["tiers"]:
            self.assertTrue(tier["input_contract"]["summary"])
            self.assertTrue(tier["output_contract"]["summary"])
            self.assertTrue(tier["fallback"])
            self.assertTrue(tier["verifier_requirement"])
            for model in tier["models"]:
                self.assertEqual(model["availability"], "VERIFIED")

    def test_unverified_model_is_refused(self):
        document = routing_contract.load(routing_contract.contract_path(ROOT))
        document["tiers"][0]["models"][0]["availability"] = "NOT FOUND"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ROUTING_CONTRACT.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(routing_contract.RoutingContractError):
                routing_contract.load(path)


if __name__ == "__main__":
    unittest.main()
