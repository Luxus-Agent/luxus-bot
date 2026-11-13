"""
Small in-process abuse protection for the auth / OTP endpoints.

Two tools:

  • enforce()/record() — a sliding-window request limiter keyed by (scope, key),
    e.g. 3 forgot-password requests per hour per email, or 8 failed logins per
    15 minutes per (IP, username). Raises HTTP 429 with a Retry-After header.

  • otp_failed()/otp_reset() — counts WRONG guesses against the code currently
    issued for a key. After `max_attempts` the caller must invalidate that code
    (set it to NULL), so a 6-digit code can never be brute-forced: an attacker
    gets a handful of guesses per code and has to request a new one — which is
    itself rate limited.

State lives in this process's memory (no Redis in this stack). With N uvicorn
workers an attacker's effective budget is N× the limits, still negligible against
a 1-in-900,000 code; a restart clears the counters. Behind a reverse proxy, run
uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy ip>` so
`request.client.host` is the real client IP rather than the proxy's.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.config import settings

_lock = threading.Lock()
_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_otp_fails: dict[str, tuple[int, float]] = {}
_last_prune = time.monotonic()
_PRUNE_EVERY_S = 300
_OTP_STATE_TTL_S = 24 * 3600


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _prune(now: float) -> None:
    """Drop stale keys so memory can't grow without bound. Caller holds _lock."""
    global _last_prune
    if now - _last_prune < _PRUNE_EVERY_S:
        return
    _last_prune = now
    for k in [k for k, dq in _hits.items() if not dq or now - dq[-1] > 3600 * 24]:
        _hits.pop(k, None)
    for k in [k for k, (_, ts) in _otp_fails.items() if now - ts > _OTP_STATE_TTL_S]:
        _otp_fails.pop(k, None)


def enforce(scope: str, key: str, limit: int, window_s: int, record_hit: bool = True) -> None:
    """Raise 429 if (scope, key) already has `limit` hits in the last `window_s`
    seconds; otherwise (when record_hit) count this call as a hit."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    now = time.monotonic()
    with _lock:
        _prune(now)
        dq = _hits[(scope, key)]
        while dq and now - dq[0] > window_s:
            dq.popleft()
        if len(dq) >= limit:
            retry_after = max(1, int(window_s - (now - dq[0])))
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        if record_hit:
            dq.append(now)


def record(scope: str, key: str) -> None:
    """Count a hit without checking (use after enforce(..., record_hit=False))."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    with _lock:
        _hits[(scope, key)].append(time.monotonic())


def otp_failed(key: str, max_attempts: int) -> bool:
    """Register one wrong guess for the code currently issued under `key`.
    Returns True once the allowance is used up — the caller must then invalidate
    the code and tell the user to request a new one."""
    now = time.monotonic()
    with _lock:
        count, _ = _otp_fails.get(key, (0, now))
        count += 1
        _otp_fails[key] = (count, now)
        return count >= max_attempts


def otp_reset(key: str) -> None:
    """Forget the failure count — call when a fresh code is issued or one is used."""
    with _lock:
        _otp_fails.pop(key, None)
