"""Fail-closed authentication boundary contract for the Portal API."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient
import pytest

import src.api.main as api


_ORIGINAL_GET_BASIC_AUTH_CREDS = api._get_basic_auth_creds
_VALID_USER = "test-user"
_VALID_PASSWORD = "test-password"


def _authorization(user: str = _VALID_USER, password: str = _VALID_PASSWORD) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


class _BrokenSecretsClient:
    def get_secret_value(self, **_kwargs):
        raise RuntimeError("secret backend unavailable: never-log-this-password")


class _StaticSecretsClient:
    def __init__(self, value: str):
        self._value = value

    def get_secret_value(self, **_kwargs):
        return {"SecretString": self._value}


@pytest.fixture(autouse=True)
def _reset_auth_state(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PORTAL_AUTH_MODE", "required")
    monkeypatch.setattr(api, "_basic_auth_creds", None)
    monkeypatch.setattr(api, "_get_basic_auth_creds", _ORIGINAL_GET_BASIC_AUTH_CREDS)
    monkeypatch.setattr(api, "_cache_ready", True)


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


def test_healthz_is_the_only_public_probe(client):
    response = client.get("/healthz")

    assert response.status_code == 200


def test_required_mode_fails_closed_when_secret_fetch_fails(
    client, monkeypatch
):
    monkeypatch.setattr(api, "get_client", lambda _service: _BrokenSecretsClient())

    response = client.get("/api/status")

    assert response.status_code == 503
    assert "never-log-this-password" not in response.text


def test_required_mode_fails_closed_for_malformed_secret(client, monkeypatch):
    monkeypatch.setattr(
        api, "get_client", lambda _service: _StaticSecretsClient("missing-separator")
    )

    response = client.get("/api/status")

    assert response.status_code == 503


def test_secret_fetch_failure_is_not_cached_and_can_recover(client, monkeypatch):
    clients = iter(
        [
            _BrokenSecretsClient(),
            _StaticSecretsClient(f"{_VALID_USER}:{_VALID_PASSWORD}"),
        ]
    )
    monkeypatch.setattr(api, "get_client", lambda _service: next(clients))

    failed = client.get("/api/status")
    recovered = client.get(
        "/api/status", headers={"Authorization": _authorization()}
    )

    assert failed.status_code == 503
    assert recovered.status_code == 200


def test_protected_path_without_authorization_returns_401(client, monkeypatch):
    monkeypatch.setattr(
        api,
        "_get_basic_auth_creds",
        lambda: (_VALID_USER, _VALID_PASSWORD),
    )

    response = client.get("/api/status")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="robot-portal"'


def test_incorrect_credentials_return_401(client, monkeypatch):
    monkeypatch.setattr(
        api,
        "_get_basic_auth_creds",
        lambda: (_VALID_USER, _VALID_PASSWORD),
    )

    response = client.get(
        "/api/status",
        headers={"Authorization": _authorization(password="wrong")},
    )

    assert response.status_code == 401


def test_valid_credentials_reach_protected_handler(client, monkeypatch):
    monkeypatch.setattr(
        api,
        "_get_basic_auth_creds",
        lambda: (_VALID_USER, _VALID_PASSWORD),
    )

    response = client.get(
        "/api/status", headers={"Authorization": _authorization()}
    )

    assert response.status_code == 200


def test_malformed_basic_header_returns_401(client, monkeypatch):
    monkeypatch.setattr(
        api,
        "_get_basic_auth_creds",
        lambda: (_VALID_USER, _VALID_PASSWORD),
    )

    response = client.get(
        "/api/status", headers={"Authorization": "Basic not-valid-@@@"}
    )

    assert response.status_code == 401


@pytest.mark.parametrize("app_env", ["local", "test"])
def test_disabled_auth_is_explicitly_allowed_only_off_production(
    client, monkeypatch, app_env
):
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("PORTAL_AUTH_MODE", "disabled")
    monkeypatch.setattr(api, "get_client", lambda _service: _BrokenSecretsClient())

    response = client.get("/api/status")

    assert response.status_code == 200


def test_disabled_auth_is_rejected_in_production(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PORTAL_AUTH_MODE", "disabled")

    response = client.get("/api/status")

    assert response.status_code == 503


def test_unknown_auth_mode_is_rejected(client, monkeypatch):
    monkeypatch.setenv("PORTAL_AUTH_MODE", "optional")

    response = client.get("/api/status")

    assert response.status_code == 503


def test_refresh_is_not_public(client, monkeypatch):
    async def _noop_refresh_cache():
        return None

    monkeypatch.setattr(api, "refresh_cache", _noop_refresh_cache)
    monkeypatch.setattr(
        api,
        "_get_basic_auth_creds",
        lambda: (_VALID_USER, _VALID_PASSWORD),
    )

    response = client.post("/api/refresh")

    assert response.status_code == 401
