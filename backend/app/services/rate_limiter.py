"""Rate Limiter — sliding window per session and per IP.

In-memory implementation (no Redis dependency). Sufficient for a single
backend process; for horizontal scaling swap _state for a Redis client.

Konfiguration in 01-base/safety-config.yaml unter `rate_limits`.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from app.services.config_loader import load_safety_config

# Per-key state: deque of unix timestamps
_state: dict[str, deque[float]] = {}


def _check_window(key: str, max_requests: int, window_seconds: int, now: float) -> bool:
    """Return True if allowed, False if exceeded."""
    if max_requests <= 0:
        return True
    dq = _state.setdefault(key, deque())
    cutoff = now - window_seconds
    while dq and dq[0] < cutoff:
        dq.popleft()
    if len(dq) >= max_requests:
        return False
    dq.append(now)
    return True


def check_rate_limit(session_id: str, ip: str = "") -> dict[str, Any]:
    """Check rate limits for a request.

    Returns:
        {
          "allowed": bool,
          "reason": str,           # which limit was hit
          "retry_after": int,      # seconds until oldest entry expires
          "blocked_message": str,  # user-facing message
        }
    """
    cfg = (load_safety_config().get("rate_limits") or {})
    if not cfg.get("enabled", False):
        return {"allowed": True, "reason": "", "retry_after": 0, "blocked_message": ""}

    now = time.time()

    per_session = cfg.get("per_session") or {}
    per_ip = cfg.get("per_ip") or {}
    ip_whitelist = set(cfg.get("ip_whitelist") or [])
    ip_enabled = per_ip.get("enabled", True)

    checks = []
    if per_session.get("enabled", True):
        checks.extend([
            ("session_minute", f"s:{session_id}:1m",
             per_session.get("requests_per_minute", 0), 60),
            ("session_hour", f"s:{session_id}:1h",
             per_session.get("requests_per_hour", 0), 3600),
        ])
    if ip and ip_enabled and ip not in ip_whitelist:
        checks.append(("ip_minute", f"i:{ip}:1m",
                       per_ip.get("requests_per_minute", 0), 60))
        checks.append(("ip_hour", f"i:{ip}:1h",
                       per_ip.get("requests_per_hour", 0), 3600))

    for label, key, mx, win in checks:
        if not _check_window(key, mx, win, now):
            dq = _state.get(key, deque())
            retry = int(win - (now - dq[0])) if dq else win
            return {
                "allowed": False,
                "reason": label,
                "retry_after": max(retry, 1),
                "blocked_message": cfg.get(
                    "blocked_message",
                    "Zu viele Anfragen — bitte kurz warten."
                ),
            }

    return {"allowed": True, "reason": "", "retry_after": 0, "blocked_message": ""}


def reset_session(session_id: str) -> None:
    """Clear all rate-limit state for a session (for /restart)."""
    for k in list(_state.keys()):
        if k.startswith(f"s:{session_id}:"):
            del _state[k]
