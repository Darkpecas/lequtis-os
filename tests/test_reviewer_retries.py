import io
import json
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, "integrations")
import independent_reviewer as reviewer  # noqa: E402


def _http(code):
    return urllib.error.HTTPError("https://example.invalid", code, "x", {}, io.BytesIO(b""))


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


OK_BODY = json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}).encode()


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.req = mock.Mock()

    def test_503_then_success_retries(self):
        seq = [_http(503), _Resp(OK_BODY)]
        with mock.patch.object(reviewer.urllib.request, "urlopen", side_effect=seq) as up, \
             mock.patch.object(reviewer.time, "sleep") as sl:
            out = reviewer._post_with_retries(self.req)
        self.assertEqual(up.call_count, 2)
        sl.assert_called_once_with(reviewer.RETRY_DELAYS[0])
        self.assertIn("candidates", out)

    def test_persistent_503_reports_status_after_all_attempts(self):
        seq = [_http(503)] * (len(reviewer.RETRY_DELAYS) + 1)
        with mock.patch.object(reviewer.urllib.request, "urlopen", side_effect=seq), \
             mock.patch.object(reviewer.time, "sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                reviewer._post_with_retries(self.req)
        self.assertEqual(str(ctx.exception), "http_503")

    def test_client_error_is_not_retried(self):
        with mock.patch.object(reviewer.urllib.request, "urlopen", side_effect=[_http(404)]) as up, \
             mock.patch.object(reviewer.time, "sleep") as sl:
            with self.assertRaises(RuntimeError) as ctx:
                reviewer._post_with_retries(self.req)
        self.assertEqual(up.call_count, 1)
        sl.assert_not_called()
        self.assertEqual(str(ctx.exception), "http_404")


if __name__ == "__main__":
    unittest.main()
