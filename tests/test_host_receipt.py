#!/usr/bin/env python3
"""Disposable tests for the read-only host receipt collector."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'runtime' / 'hermes-stdio-connector' / 'host_receipt.py'

class ReceiptTests(unittest.TestCase):
    def run_receipt(self, root):
        p = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_missing_prerequisites_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self.run_receipt(tmp)
            self.assertFalse(data['git']['ok'])
            self.assertFalse(data['preflight']['ok'])
            self.assertFalse(data['live_host_verified'])
            self.assertFalse(data['sovereign_loop_verified'])

    def test_exact_local_checkout_still_not_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                            'commit', '--allow-empty', '-qm', 'disposable'], check=True)
            (root/'core').mkdir()
            (root/'core'/'lequtis.py').write_text('# fixture\n')
            f = root/'runtime'/'hermes-stdio-connector'/'host_preflight.py'
            f.parent.mkdir(parents=True)
            f.write_text('print("{\\\"ok\\\": true}")\n')
            data = self.run_receipt(root)
            self.assertTrue(data['git']['ok'])
            self.assertTrue(data['core_present'])
            self.assertTrue(data['preflight_present'])
            self.assertTrue(data['preflight']['ok'])
            self.assertEqual(data['scope'], 'local_read_only')
            self.assertFalse(data['live_host_verified'])
            self.assertFalse(data['sovereign_loop_verified'])

if __name__ == '__main__':
    unittest.main()
