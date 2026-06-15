"""Rate-Limiter — Sliding-Window, schul-tauglich (per-Session fein, per-IP grob).

Die reine Fenster-Logik (`_check_window`) bekommt ``now`` injiziert und ist
damit voll deterministisch testbar. `check_rate_limit` wird über eine
gemockte Config geprüft; das In-Memory-State-Dict wird je Test geleert.
"""

from __future__ import annotations

import pytest

from app.services import rate_limiter as rl


@pytest.fixture(autouse=True)
def _clear_state():
    rl._state.clear()
    yield
    rl._state.clear()


# ── _check_window: pure sliding window ──────────────────────────────────

def test_window_allows_up_to_max_then_blocks():
    # max 3 in 60s, alle zur selben „Zeit" t=1000
    assert rl._check_window("k", 3, 60, 1000.0) is True
    assert rl._check_window("k", 3, 60, 1000.0) is True
    assert rl._check_window("k", 3, 60, 1000.0) is True
    assert rl._check_window("k", 3, 60, 1000.0) is False  # 4. überschreitet


def test_window_slides_old_entries_out():
    assert rl._check_window("k", 1, 60, 1000.0) is True
    assert rl._check_window("k", 1, 60, 1000.0) is False  # zu früh
    # 61s später ist der erste Eintrag aus dem Fenster gefallen
    assert rl._check_window("k", 1, 60, 1061.0) is True


def test_window_zero_max_is_unlimited():
    for _ in range(1000):
        assert rl._check_window("k", 0, 60, 1000.0) is True


# ── check_rate_limit: config-getrieben ──────────────────────────────────

_CFG = {
    "rate_limits": {
        "enabled": True,
        "per_session": {"enabled": True, "requests_per_minute": 3, "requests_per_hour": 100},
        "per_ip": {"enabled": True, "requests_per_minute": 5, "requests_per_hour": 200},
        "ip_whitelist": ["9.9.9.9"],
        "blocked_message": "stop",
    }
}


def _patch(monkeypatch, cfg=_CFG):
    monkeypatch.setattr(rl, "load_safety_config", lambda: cfg)


def test_disabled_always_allows(monkeypatch):
    _patch(monkeypatch, {"rate_limits": {"enabled": False}})
    for _ in range(50):
        assert rl.check_rate_limit("s1", "1.2.3.4")["allowed"] is True


def test_per_session_blocks_after_limit(monkeypatch):
    _patch(monkeypatch)
    for _ in range(3):
        assert rl.check_rate_limit("s1", "")["allowed"] is True
    res = rl.check_rate_limit("s1", "")
    assert res["allowed"] is False
    assert res["reason"] == "session_minute"
    assert res["blocked_message"] == "stop"
    assert res["retry_after"] >= 1


def test_sessions_are_independent(monkeypatch):
    _patch(monkeypatch)
    for _ in range(3):
        rl.check_rate_limit("s1", "")
    assert rl.check_rate_limit("s1", "")["allowed"] is False
    # andere Session ist unbelastet
    assert rl.check_rate_limit("s2", "")["allowed"] is True


def test_per_ip_blocks_across_sessions_simulating_nat(monkeypatch):
    # Viele Sessions, dieselbe IP → IP-Limit (5/min) greift trotz frischer Sessions.
    _patch(monkeypatch)
    allowed = 0
    for i in range(10):
        if rl.check_rate_limit(f"sess-{i}", "203.0.113.7")["allowed"]:
            allowed += 1
    assert allowed == 5  # genau das per-IP-Minutenlimit


def test_whitelisted_ip_is_exempt_from_ip_limit(monkeypatch):
    # Whitelist-IP: nur das per-Session-Limit greift, das IP-Limit nie.
    _patch(monkeypatch)
    allowed = 0
    for i in range(10):
        if rl.check_rate_limit(f"sess-{i}", "9.9.9.9")["allowed"]:
            allowed += 1
    assert allowed == 10  # kein IP-Block, jede frische Session zählt einzeln


def test_reset_session_clears_only_that_session(monkeypatch):
    _patch(monkeypatch)
    for _ in range(3):
        rl.check_rate_limit("s1", "")
    assert rl.check_rate_limit("s1", "")["allowed"] is False
    rl.reset_session("s1")
    assert rl.check_rate_limit("s1", "")["allowed"] is True
