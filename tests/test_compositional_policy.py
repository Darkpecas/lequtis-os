"""Disposable tests for cross-tool authorization. Run: python -m unittest discover -s tests -p 'test_compositional_policy.py'"""
import unittest
from core.compositional_policy import Session, ToolPolicy

class PolicyTests(unittest.TestCase):
    def test_safe_chain(self):
        s = Session("task1", frozenset({"read", "write"}), 2)
        self.assertTrue(s.authorize(ToolPolicy("read", frozenset({"private"}), frozenset(), 2), resource_level=2).allowed)
        self.assertTrue(s.authorize(ToolPolicy("write", frozenset(), frozenset({"local"}), 2)).allowed)
        self.assertEqual(s.sensitivity, 2)

    def test_exfiltration_chain_denied(self):
        s = Session("task1", frozenset({"read", "http"}), 2)
        s.authorize(ToolPolicy("read", frozenset({"private"}), frozenset(), 2), resource_level=2)
        result = s.authorize(ToolPolicy("http", frozenset(), frozenset({"internet"}), 2, True))
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "sensitive_egress_denied")
        self.assertEqual(s.sensitivity, 2)

    def test_unknown_tool_denied(self):
        s = Session("task1", frozenset({"read"}), 2)
        self.assertFalse(s.authorize(ToolPolicy("http", frozenset(), frozenset({"internet"}), 2, True)).allowed)

    def test_clearance_denied_without_state_mutation(self):
        s = Session("task1", frozenset({"read"}), 1)
        self.assertFalse(s.authorize(ToolPolicy("read", frozenset({"secret"}), frozenset(), 3), resource_level=3).allowed)
        self.assertEqual(s.sensitivity, 0)

    def test_monotonicity(self):
        s = Session("task1", frozenset({"read"}), 3)
        p = ToolPolicy("read", frozenset({"data"}), frozenset(), 3)
        values = []
        for level in (1, 0, 3, 2):
            self.assertTrue(s.authorize(p, resource_level=level).allowed)
            values.append(s.sensitivity)
        self.assertEqual(values, [1, 1, 3, 3])

    def test_public_egress_allowed(self):
        s = Session("task1", frozenset({"http"}), 0)
        self.assertTrue(s.authorize(ToolPolicy("http", frozenset(), frozenset({"public"}), 0, True)).allowed)

if __name__ == "__main__":
    unittest.main()
