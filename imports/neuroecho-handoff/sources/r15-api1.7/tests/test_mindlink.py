"""Local MindLink contract tests; no hardware or network access required."""
import unittest
from unittest.mock import patch
from urllib.error import URLError

from server import mindlink


def sample():
    return {
        "api_version": "1.0", "connected": True, "live": True, "signal_quality": 0,
        "attention": {"value": 65, "valid": True, "source": "neurosky_esense", "age_ms": 500},
    }


class MindLinkTests(unittest.TestCase):
    def test_disabled_never_contacts_device(self):
        with patch.object(mindlink, "_fetch", side_effect=AssertionError("device was contacted")):
            self.assertEqual(mindlink.read_attention()["reason"], "not_enabled")
            self.assertEqual(mindlink.read_attention(enabled=1)["reason"], "not_enabled")

    def test_valid_snapshot_and_no_cached_value(self):
        state = sample()
        with patch.object(mindlink, "_fetch", return_value=state):
            result = mindlink.read_attention(enabled=True)
            self.assertTrue(result["available"])
            self.assertEqual(result["score"], 65)
            self.assertGreaterEqual(result["age_ms"], 500)
            state["live"] = False
            result = mindlink.read_attention(enabled=True)
            self.assertFalse(result["available"])
            self.assertIsNone(result["score"])

    def test_bad_service_or_signal_never_returns_score(self):
        cases = [("connected", False), ("live", False), ("signal_quality", None),
                 ("signal_quality", 1), ("signal_quality", False), ("api_version", "2.0")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                state = sample()
                state[field] = value
                with patch.object(mindlink, "_fetch", return_value=state):
                    result = mindlink.read_attention(enabled=True)
                self.assertFalse(result["available"])
                self.assertIsNone(result["score"])

    def test_invalid_or_expired_attention_never_returns_score(self):
        cases = [("valid", False), ("source", "personal_model"), ("value", None), ("value", 0),
                 ("value", True), ("value", float("nan")), ("value", 10 ** 400), ("value", 101), ("age_ms", None),
                 ("age_ms", -1), ("age_ms", 2501), ("age_ms", float("inf"))]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                state = sample()
                state["attention"][field] = value
                with patch.object(mindlink, "_fetch", return_value=state):
                    result = mindlink.read_attention(enabled=True)
                self.assertFalse(result["available"])
                self.assertIsNone(result["score"])

    def test_request_time_counts_against_freshness(self):
        state = sample()
        state["attention"]["age_ms"] = 2000
        with patch.object(mindlink, "_fetch", return_value=state), patch.object(mindlink.time, "monotonic", side_effect=[1.0, 1.6]):
            result = mindlink.read_attention(enabled=True)
        self.assertFalse(result["available"])
        self.assertIsNone(result["score"])

    def test_failed_request_does_not_preserve_previous_score(self):
        for error in [URLError("offline"), TimeoutError(), ValueError("bad response")]:
            with self.subTest(error=error):
                with patch.object(mindlink, "_fetch", side_effect=[sample(), error]):
                    self.assertTrue(mindlink.read_attention(enabled=True)["available"])
                    result = mindlink.read_attention(enabled=True)
                self.assertEqual(result["reason"], "service_unavailable")
                self.assertIsNone(result["score"])

    def test_fixed_loopback_and_bounded_read(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, n):
                self.read_size = n
                return b'{}'
        response = Response()
        class Opener:
            def open(self, request, timeout):
                self.url, self.timeout = request.full_url, timeout
                return response
        opener = Opener()
        with patch.object(mindlink, "build_opener", return_value=opener) as build:
            self.assertEqual(mindlink._fetch(), {})
        self.assertEqual(opener.url, "http://127.0.0.1:8876/api/v1/state?source=esense")
        self.assertEqual(opener.timeout, 1.0)
        self.assertEqual(response.read_size, 65537)
        self.assertEqual(len(build.call_args.args), 2)
        self.assertIsInstance(build.call_args.args[1], mindlink._NoRedirect)


if __name__ == "__main__":
    unittest.main()
