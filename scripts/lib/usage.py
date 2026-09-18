"""Claude 5-hour usage throttle for the Python pipeline scripts.

A port of `scripts/wiki-ingest.sh`'s `fetch_from_api` / `read_from_cache` /
`get_usage` so a long Python run pauses on the same signal and at the same
threshold as the shell pipeline. Anthropic API first, HUD cache as fallback.

Throttling only applies to the `claude` backend; for the others the utilization
is unknown and callers run unthrottled, as the shell pipeline does.
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


THRESHOLD = 85
WAIT_SECONDS = 1800
CACHE_TTL_SECONDS = 120
HUD_CACHE = Path.home() / ".claude" / "plugins" / "claude-hud" / ".usage-cache.json"
_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_KEYCHAIN_SERVICE = "Claude Code-credentials"


def _access_token() -> str | None:
    """The OAuth access token from the macOS keychain, or None."""
    try:
        proc = subprocess.run(
            ["/usr/bin/security", "find-generic-password",
             "-s", _KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return data.get("claudeAiOauth", {}).get("accessToken") or None


def _from_api() -> int | None:
    """Five-hour utilization percent from the Anthropic API, or None."""
    token = _access_token()
    if not token:
        return None
    request = urllib.request.Request(
        _USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None
    value = payload.get("five_hour", {}).get("utilization")
    if value is None:
        return None
    try:
        return round(max(0.0, min(100.0, float(value))))
    except (TypeError, ValueError):
        return None


def _from_cache(now: float | None = None) -> int | None:
    """Five-hour utilization from the HUD cache, if fresh enough."""
    try:
        payload = json.loads(HUD_CACHE.read_text(encoding="utf-8"))
        age = ((now or time.time()) * 1000 - payload["timestamp"]) / 1000
        if age > CACHE_TTL_SECONDS:
            return None
        value = payload.get("data", {}).get("fiveHour")
        return None if value is None else int(value)
    except Exception:
        # A malformed or unreadable cache must never raise into the caller: it
        # would abort a long run over a diagnostic that does not matter.
        return None


def utilization() -> int | None:
    """Current 5-hour usage percent, API first then cache. None if unknown."""
    from_api = _from_api()
    if from_api is not None:
        return from_api
    return _from_cache()


def wait_until_below(
    threshold: int = THRESHOLD,
    wait_seconds: int = WAIT_SECONDS,
    *,
    context: str = "",
    sleep=time.sleep,
    probe=utilization,
) -> None:
    """Block until 5-hour usage is under `threshold`.

    An unknown utilization proceeds rather than stalling: the throttle is a
    courtesy to the usage window, not a correctness gate, and a run must not
    hang because the keychain or the API is unavailable.
    """
    while True:
        percent = probe()
        if percent is None:
            print("5-hour usage unknown — continuing unthrottled", file=sys.stderr)
            return
        if percent < threshold:
            print(f"5-hour usage: {percent}% (threshold {threshold}%)", file=sys.stderr)
            return
        resume = time.strftime("%H:%M", time.localtime(time.time() + wait_seconds))
        print(f"5-hour usage {percent}% ≥ {threshold}% — pausing "
              f"{wait_seconds // 60} min{f' ({context})' if context else ''}. "
              f"Next attempt {resume}.", file=sys.stderr)
        sleep(wait_seconds)
