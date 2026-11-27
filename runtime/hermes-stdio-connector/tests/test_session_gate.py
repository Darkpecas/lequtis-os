import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timezone, timedelta
from session_gate import assess
class Gate(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.r = dict(session_id='s', observed_at=self.now.isoformat(), authenticated=True, probe_ok=True, read_only=True, receipt_id='r')
    def check(self, **changes):
        return assess(['git'], {'git': dict(self.r, **changes)}, 's', self.now)['state']
    def test_ready(self): self.assertEqual(self.check(), 'READY')
    def test_wrong_session(self): self.assertEqual(self.check(session_id='old'), 'DEGRADED')
    def test_stale(self): self.assertEqual(self.check(observed_at=(self.now-timedelta(seconds=301)).isoformat()), 'DEGRADED')
    def test_future(self): self.assertEqual(self.check(observed_at=(self.now+timedelta(seconds=1)).isoformat()), 'DEGRADED')
    def test_auth(self): self.assertEqual(self.check(authenticated=False), 'DEGRADED')
    def test_probe(self): self.assertEqual(self.check(probe_ok=False), 'DEGRADED')
    def test_write(self): self.assertEqual(self.check(read_only=False), 'DEGRADED')
    def test_receipt(self): self.assertEqual(self.check(receipt_id=''), 'DEGRADED')
    def test_missing(self): self.assertEqual(assess(['git'], {}, 's', self.now)['state'], 'DEGRADED')
    def test_empty(self):
        with self.assertRaises(ValueError): assess([], {}, 's', self.now)
    def test_malformed(self): self.assertEqual(self.check(observed_at='bad'), 'DEGRADED')
if __name__ == '__main__': unittest.main()
