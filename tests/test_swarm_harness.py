"""Swarm harness: budget, faults, held-out keys, and the four-arm report."""
import ast
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.swarm.answer_keys import keys  # noqa: E402
from eval.swarm.arms import run_arm  # noqa: E402
from eval.swarm.budget import CAP, COST, POOL, Budget, add_costs  # noqa: E402
from eval.swarm.corpus import packets  # noqa: E402
from eval.swarm.faults import FAULTS  # noqa: E402
from eval.swarm.metrics import classify_claim, correctness_adjusted_latency, grade  # noqa: E402
from eval.swarm.provider import MockProvider, ProviderRefused, load_provider  # noqa: E402
from eval.swarm.runner import build_report  # noqa: E402
from eval.swarm.schedule import waves  # noqa: E402
from eval.swarm.worker import extract  # noqa: E402

FORBIDDEN_IMPORTS = {"socket", "urllib", "http", "requests", "openai"}
KEY_IMPORTERS = {"metrics.py"}


def _priors(packet, completed):
    found = []
    for dep in packet["depends_on"]:
        for claim in completed[dep]["claims"]:
            found.append(claim["proposition"])
    return found


class SwarmHarnessTests(unittest.TestCase):
    def test_corpus_is_synthetic_and_keys_are_not_in_the_packet(self):
        rows = packets()
        self.assertEqual(len(rows), 8)
        kinds = {row["kind"] for row in rows}
        self.assertEqual(
            kinds,
            {
                "parallel-extraction",
                "serial-dependency",
                "conflicting-source",
                "unanswerable",
                "benign-quoted-instruction",
            },
        )
        for row in rows:
            self.assertEqual(row["label"], "SYNTHETIC")
            self.assertNotIn("acceptable_propositions", row)
            self.assertNotIn("unknown", row)
        self.assertEqual(set(keys()), {row["packet_id"] for row in rows})

    def test_worker_modules_do_not_import_keys_or_network(self):
        swarm = ROOT / "eval" / "swarm"
        for path in sorted(swarm.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                for module in modules:
                    root_name = module.split(".")[0]
                    self.assertNotIn(root_name, FORBIDDEN_IMPORTS, path.name)
                    if "answer_keys" in module:
                        self.assertIn(path.name, KEY_IMPORTERS, path.name)

    def test_extractor_matches_held_out_keys_when_dependencies_are_respected(self):
        corpus = packets()
        completed = {}
        for wave in waves(corpus, 1):
            for packet in wave:
                completed[packet["packet_id"]] = extract(
                    packet, _priors(packet, completed), 7, MockProvider()
                )
        graded = grade(corpus, completed)
        self.assertEqual(graded["precision"], 1)
        self.assertEqual(graded["completeness"], 1)
        self.assertEqual(graded["correct_unknowns"], 2)
        self.assertEqual(graded["fabricated_citations"], 0)
        self.assertTrue(graded["proxy_for_human_adjudication"])
        again = extract(corpus[0], [], 7, MockProvider())
        self.assertEqual(again, completed["syn-01"])

    def test_fabricated_citation_is_not_supported(self):
        packet = packets()[1]
        claim = {"proposition": "beacon = north", "source_hashes": ["0" * 64]}
        self.assertEqual(classify_claim(claim, packet, keys()["syn-02"]), "fabricated")

    def test_real_provider_is_refused_and_mock_does_not_spend(self):
        provider = load_provider(None)
        self.assertEqual(provider.name, "mock")
        result = provider.complete("SYNTHETIC", seed=1, max_tokens=4)
        self.assertFalse(result["network_call"])
        self.assertEqual(result["money_spent"], 0)
        with self.assertRaises(ProviderRefused):
            load_provider({"provider": "openai"})
        with self.assertRaises(ProviderRefused):
            load_provider({"provider": "openai", "money_cap": True})
        with self.assertRaises(ProviderRefused) as refused:
            load_provider({"provider": "openai", "money_cap": 1})
        self.assertIn("not shipped", str(refused.exception))

    def test_budget_reservation_is_atomic_and_refuses_overspend(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = Budget(Path(tmp) / "budget.db")
            self.assertTrue(budget.reserve("task", {"tokens": CAP["tokens"], "tool_calls": 0, "wall_ms": 0}))
            self.assertFalse(budget.reserve("task", {"tokens": 1, "tool_calls": 0, "wall_ms": 0}))
            self.assertEqual(budget.spent("task")["tokens"], CAP["tokens"])
            with self.assertRaises(ValueError):
                budget.reserve("task", {"tokens": -1, "tool_calls": 0, "wall_ms": 0})
            race = Budget(Path(tmp) / "race.db")
            barrier = threading.Barrier(2)
            results = []

            def attempt():
                barrier.wait()
                results.append(race.reserve("task", {"tokens": 100, "tool_calls": 0, "wall_ms": 0}))

            threads = [threading.Thread(target=attempt) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertEqual(sorted(results), [False, True])
            self.assertEqual(race.spent("task")["tokens"], 100)

    def test_every_fault_meets_its_preregistered_expectation(self):
        self.assertEqual(
            [name for name, _func in FAULTS],
            [
                "worker_kill_mid_lease",
                "duplicate_delivery",
                "late_result_after_cancel",
                "stale_lease",
                "poisoned_passage",
                "partitioned_worker",
                "forbidden_side_effect",
                "overspend",
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, func in FAULTS:
                outcome = func(root / name)
                self.assertEqual(outcome["fault"], name, outcome)
                self.assertTrue(outcome["expectation_met"], outcome)
                self.assertEqual(outcome["applies_to"], ["A", "B", "C", "D"])

    def test_clean_arms_pass_safety_and_follow_the_schedule_model(self):
        corpus = packets()
        expected = _expected_makespans(corpus)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, makespan in expected.items():
                result = run_arm(name, corpus, root / name, seed=20261110)
                self.assertEqual(result["safety"], "PASS", result)
                self.assertEqual(result["safety_failures"], [])
                self.assertEqual(result["metrics"]["simulated_makespan_ms"], makespan)
                self.assertEqual(result["metrics"]["precision"], 1)
                self.assertEqual(result["metrics"]["completeness"], 1)
                self.assertEqual(result["metrics"]["duplicate_work"], 0)
                self.assertLessEqual(result["metrics"]["tokens"] / len(corpus), CAP["tokens"])
                self.assertFalse(result["partition_tolerant"])
            self.assertTrue(result["pull_allocation"])
        cal_d = correctness_adjusted_latency(expected["D"], 1)
        cal_c = correctness_adjusted_latency(expected["C"], 1)
        self.assertLess(cal_c, cal_d)

    def test_report_labels_the_mock_and_evaluates_falsifiers(self):
        report = build_report(20261110, "2026-11-10")
        self.assertTrue(report["runner_ok"], report.get("arms"))
        self.assertIn("not an LLM swarm benefit", report["statement"])
        self.assertIn("not partition-tolerant", report["arm_d_scope"])
        self.assertEqual(report["provider"]["network_calls"], 0)
        self.assertFalse(report["provider"]["real_provider_shipped"])
        self.assertEqual(report["budget_cap_per_task"], CAP)
        self.assertEqual(set(report["arms"]), {"A", "B", "C", "D"})
        self.assertEqual(
            {fault["fault"] for fault in report["faults"]},
            {name for name, _func in FAULTS},
        )
        falsifiers = report["falsifiers"]
        self.assertIn(
            falsifiers["D_beats_C_on_correctness_adjusted_latency"]["label"],
            {"REJECTED", "NOT REJECTED"},
        )
        self.assertIn(
            falsifiers["D_beats_B_precision_by_10_points"]["label"],
            {"REJECTED", "NOT REJECTED"},
        )
        for name in ("A", "B", "C", "D"):
            self.assertEqual(falsifiers["any_safety_failure_fails_the_arm"][name], "PASS")
        self.assertEqual(report["arms"]["D"]["pull_allocation"], True)
        self.assertEqual(report["arms"]["C"]["pull_allocation"], False)
        repeated = build_report(20261110, "2026-11-10")
        for name in ("A", "B", "C", "D"):
            left = dict(report["arms"][name]["metrics"])
            right = dict(repeated["arms"][name]["metrics"])
            left.pop("process_wall_ms")
            right.pop("process_wall_ms")
            self.assertEqual(left, right)
        self.assertEqual(
            report["falsifiers"]["D_beats_C_on_correctness_adjusted_latency"]["label"],
            repeated["falsifiers"]["D_beats_C_on_correctness_adjusted_latency"]["label"],
        )


def _expected_makespans(corpus):
    serial = COST["plan"]["wall_ms"] + COST["worker"]["wall_ms"] + COST["verify"]["wall_ms"]
    ensemble = (
        COST["plan"]["wall_ms"] + COST["worker"]["wall_ms"]
        + COST["synthesize"]["wall_ms"] + COST["verify"]["wall_ms"]
    )
    c_waves = waves(corpus, POOL)
    d_total = 0
    for wave in c_waves:
        size = len(wave)
        d_total += (
            COST["lease"]["wall_ms"] * size
            + COST["worker"]["wall_ms"]
            + COST["lease"]["wall_ms"] * size
            + COST["verify"]["wall_ms"]
        )
    per_task = {
        "A": add_costs(COST["plan"], COST["worker"], COST["verify"]),
        "D": add_costs(COST["lease"], COST["worker"], COST["lease"], COST["verify"]),
    }
    for cost in per_task.values():
        assert cost["tokens"] <= CAP["tokens"]
        assert cost["tool_calls"] <= CAP["tool_calls"]
        assert cost["wall_ms"] <= CAP["wall_ms"]
    return {
        "A": serial * len(waves(corpus, 1)),
        "B": ensemble * len(waves(corpus, 1)),
        "C": serial * len(c_waves),
        "D": d_total,
    }


if __name__ == "__main__":
    unittest.main()
