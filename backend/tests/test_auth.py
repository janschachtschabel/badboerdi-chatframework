"""Studio-API-Key-Auth — no-op wenn kein Key gesetzt, sonst timing-safe Vergleich.

``require_studio_key`` ist async; wir rufen es direkt via ``asyncio.run`` auf
(kein pytest-asyncio nötig) und übergeben die Header-/Query-Werte explizit.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.services import auth


def _call(header=None, query=None):
    return asyncio.run(auth.require_studio_key(x_studio_key=header, key=query))


def test_no_key_configured_is_noop(monkeypatch):
    monkeypatch.delenv("STUDIO_API_KEY", raising=False)
    assert _call(header=None, query=None) is None
    assert _call(header="irgendwas", query=None) is None  # egal, Auth aus


def test_correct_key_in_header_passes(monkeypatch):
    monkeypatch.setenv("STUDIO_API_KEY", "s3cr3t")
    assert _call(header="s3cr3t", query=None) is None


def test_correct_key_in_query_passes(monkeypatch):
    monkeypatch.setenv("STUDIO_API_KEY", "s3cr3t")
    assert _call(header=None, query="s3cr3t") is None


def test_wrong_key_raises_401(monkeypatch):
    monkeypatch.setenv("STUDIO_API_KEY", "s3cr3t")
    with pytest.raises(HTTPException) as exc:
        _call(header="falsch", query=None)
    assert exc.value.status_code == 401


def test_missing_key_when_configured_raises_401(monkeypatch):
    monkeypatch.setenv("STUDIO_API_KEY", "s3cr3t")
    with pytest.raises(HTTPException):
        _call(header=None, query=None)


def test_key_is_stripped(monkeypatch):
    # Whitespace-Toleranz: Env und Eingabe werden getrimmt.
    monkeypatch.setenv("STUDIO_API_KEY", "  s3cr3t  ")
    assert _call(header="s3cr3t", query=None) is None
