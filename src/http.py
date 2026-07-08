"""Anti-bot HTTP mixin: the one place every fetcher makes a request.

Stdlib only (urllib/time/random) so it never trips the no-third-party-import
invariant. Per-host pacing + burst cap + cooldown keep the scan polite enough
to not get a whole board's IP thrown into a 403/429 hole. Time, sleep and
jitter are module-level indirection hooks so tests run frozen and offline.
"""

import random
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DELAY = 0.5       # min gap between two hits to the same host (seconds)
JITTER_MAX = 1.0       # random 0..JITTER_MAX added on top, so we don't march
BURST_CAP = 20         # hits to one host before a forced breather
COOLDOWN = 5.0         # that breather (seconds)
COOLDOWN_LONG = 60.0   # penalty box after a host says 429/403

# host -> {"last": monotonic|None, "burst": int, "cooldown_until": monotonic}
_HOST_STATE = {}

# indirection hooks — tests monkeypatch these for determinism
_now = time.monotonic
_sleep = time.sleep


def _rand_jitter():
    return random.uniform(0.0, JITTER_MAX)


class Blocked(Exception):
    """Host is in cooldown, or answered 429/403. Callers isolate per-host."""


def fetch_bytes(url, *, data=None, headers=None, timeout=20):
    """GET (data is None) or POST (data bytes) `url`, returning the raw body.

    Paces same-host calls, forces a cooldown after BURST_CAP hits, and drops a
    host into a long cooldown on 429/403. No retry on any error.
    """
    host = urllib.parse.urlsplit(url).netloc
    state = _HOST_STATE.setdefault(
        host, {"last": None, "burst": 0, "cooldown_until": 0.0}
    )

    if _now() < state["cooldown_until"]:
        raise Blocked(f"{host} in cooldown")

    if state["last"] is not None:            # nothing to throttle on the first hit
        _sleep(BASE_DELAY + _rand_jitter())
    state["burst"] += 1
    if state["burst"] >= BURST_CAP:
        _sleep(COOLDOWN)
        state["burst"] = 0

    try:
        req = urllib.request.Request(url, data=data, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (429, 403):
            state["cooldown_until"] = _now() + COOLDOWN_LONG
            raise Blocked(f"{host} returned {e.code}") from e
        raise
    finally:
        # record the attempt time on EVERY path — a failed request still counts,
        # else the next same-host call skips pacing (worst in the vc probe fan-out).
        state["last"] = _now()
