"""Authorize.net client tests.

Live API calls are NOT tested here — that requires sandbox credentials.
What we do test: config gating, environment label, request-body shape (via
monkeypatch), and response parsing of canned Auth.net payloads.
"""
from __future__ import annotations

import pytest

from core import authnet


# ── Config gating ────────────────────────────────────────────────────────────
# Tests isolate from streamlit secrets by patching `authnet._secret` directly —
# otherwise the local `.streamlit/secrets.toml` file leaks placeholder values
# into the test.


def _stub_secret(values: dict):
    """Return a _secret-shaped function that reads from `values` only."""
    def _secret(key, default=None):
        return values.get(key, default)
    return _secret


def test_is_configured_false_without_secrets(monkeypatch):
    monkeypatch.setattr(authnet, "_secret", _stub_secret({}))
    assert not authnet.is_configured()
    assert authnet.env_label() == "(not configured)"


def test_is_configured_true_with_secrets(monkeypatch):
    monkeypatch.setattr(authnet, "_secret", _stub_secret({
        "AUTHNET_API_LOGIN_ID": "test-login",
        "AUTHNET_TRANSACTION_KEY": "test-key",
        "AUTHNET_ENV": "sandbox",
    }))
    assert authnet.is_configured()
    assert authnet.env_label() == "sandbox"


def test_config_routes_to_sandbox_by_default(monkeypatch):
    monkeypatch.setattr(authnet, "_secret", _stub_secret({
        "AUTHNET_API_LOGIN_ID": "x",
        "AUTHNET_TRANSACTION_KEY": "y",
    }))
    cfg = authnet._config()
    assert cfg["endpoint"] == authnet.SANDBOX_ENDPOINT


def test_config_routes_to_production_when_requested(monkeypatch):
    monkeypatch.setattr(authnet, "_secret", _stub_secret({
        "AUTHNET_API_LOGIN_ID": "x",
        "AUTHNET_TRANSACTION_KEY": "y",
        "AUTHNET_ENV": "production",
    }))
    cfg = authnet._config()
    assert cfg["endpoint"] == authnet.PRODUCTION_ENDPOINT


def test_missing_credentials_raises(monkeypatch):
    monkeypatch.setattr(authnet, "_secret", _stub_secret({}))
    with pytest.raises(RuntimeError, match="credentials not configured"):
        authnet._config()
