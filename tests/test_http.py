import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="yoke-test-http-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import http  # noqa: E402


class _FakeResp:
    """Minimal context-manager stand-in for the urlopen response."""

    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _make_urlopen(body=b"OK", error=None):
    """Fake urllib.request.urlopen: records the Request objects it sees and
    either returns a body or raises a pre-built error. No network."""
    calls = []

    def _urlopen(req, timeout=None):
        calls.append(req)
        if error is not None:
            raise error
        return _FakeResp(body)

    _urlopen.calls = calls
    return _urlopen


class HttpMixinTest(unittest.TestCase):
    def setUp(self):
        # deterministic + offline: frozen clock, no real sleep, no jitter
        http._HOST_STATE.clear()
        self.sleep = mock.MagicMock()
        patches = [
            mock.patch.object(http, "_now", lambda: 1000.0),
            mock.patch.object(http, "_sleep", self.sleep),
            mock.patch.object(http, "_rand_jitter", lambda: 0.0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _patch_urlopen(self, **kw):
        fake = _make_urlopen(**kw)
        p = mock.patch("urllib.request.urlopen", new=fake)
        p.start()
        self.addCleanup(p.stop)
        return fake

    def test_get_when_no_data(self):
        fake = self._patch_urlopen(body=b"hello")
        out = http.fetch_bytes("https://a.example/x")
        self.assertEqual(out, b"hello")
        self.assertEqual(len(fake.calls), 1)
        req = fake.calls[0]
        self.assertIsNone(req.data)              # no body → GET
        self.assertEqual(req.get_method(), "GET")

    def test_post_when_data(self):
        fake = self._patch_urlopen(body=b"ok")
        body = b'{"q": 1}'
        out = http.fetch_bytes(
            "https://a.example/search", data=body,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(out, b"ok")
        req = fake.calls[0]
        self.assertEqual(req.data, body)         # body present → POST
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Content-type"), "application/json")

    def test_paces_between_same_host_calls(self):
        self._patch_urlopen(body=b"x")
        http.fetch_bytes("https://a.example/1")   # first hit: no pacing
        http.fetch_bytes("https://a.example/2")   # second hit: paced
        paced = [c.args[0] for c in self.sleep.call_args_list]
        self.assertTrue(
            any(s >= http.BASE_DELAY for s in paced),
            f"expected a pacing sleep >= {http.BASE_DELAY}, saw {paced}",
        )

    def test_burst_cap_triggers_cooldown(self):
        self._patch_urlopen(body=b"x")
        for i in range(http.BURST_CAP):
            http.fetch_bytes(f"https://a.example/{i}")
        sleeps = [c.args[0] for c in self.sleep.call_args_list]
        self.assertIn(http.COOLDOWN, sleeps)      # burst cap forced a cooldown
        # burst reset after the cooldown
        self.assertEqual(http._HOST_STATE["a.example"]["burst"], 0)

    def test_429_sets_cooldown_then_next_call_blocked(self):
        err = urllib.error.HTTPError("https://a.example/x", 429, "Too Many", {}, None)
        fake = self._patch_urlopen(error=err)
        with self.assertRaises(http.Blocked):
            http.fetch_bytes("https://a.example/x")
        self.assertEqual(len(fake.calls), 1)      # one real attempt, no retry
        self.assertGreater(http._HOST_STATE["a.example"]["cooldown_until"], 1000.0)
        # host is now in cooldown → next call short-circuits, no new request
        with self.assertRaises(http.Blocked):
            http.fetch_bytes("https://a.example/y")
        self.assertEqual(len(fake.calls), 1)

    def test_403_sets_cooldown(self):
        err = urllib.error.HTTPError("https://a.example/x", 403, "Forbidden", {}, None)
        self._patch_urlopen(error=err)
        with self.assertRaises(http.Blocked):
            http.fetch_bytes("https://a.example/x")
        self.assertGreater(http._HOST_STATE["a.example"]["cooldown_until"], 1000.0)

    def test_distinct_hosts_independent_state(self):
        # host a gets 429 → cooldown; host b must stay reachable
        err = urllib.error.HTTPError("https://a.example/x", 429, "Too Many", {}, None)

        def _urlopen(req, timeout=None):
            if "a.example" in req.full_url:
                raise err
            return _FakeResp(b"b-ok")

        p = mock.patch("urllib.request.urlopen", new=_urlopen)
        p.start()
        self.addCleanup(p.stop)

        with self.assertRaises(http.Blocked):
            http.fetch_bytes("https://a.example/x")
        self.assertIn("a.example", http._HOST_STATE)
        self.assertNotIn("b.example", http._HOST_STATE)
        # b is untouched by a's cooldown
        self.assertEqual(http.fetch_bytes("https://b.example/y"), b"b-ok")


if __name__ == "__main__":
    unittest.main()
