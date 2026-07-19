"""Authentication contract for the Airflow-to-Portal cache refresh call."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock
import urllib.request

import pytest


pytest.importorskip("airflow")

import robot_daily_etl as etl


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps({"rows_after": 1}).encode("utf-8")


class _SecretsClient:
    def __init__(self, value: str):
        self._value = value

    def get_secret_value(self, **_kwargs):
        return {"SecretString": self._value}


def test_refresh_sends_portal_secret_as_basic_header(monkeypatch, capsys):
    username = "airflow-service"
    password = "service-password"
    secrets_client = _SecretsClient(f"{username}:{password}")
    urlopen = MagicMock(return_value=_Response())
    monkeypatch.setattr(
        etl.boto3,
        "client",
        lambda service, **_kwargs: secrets_client
        if service == "secretsmanager"
        else MagicMock(),
    )
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    etl._refresh_api_cache()

    request = urlopen.call_args.args[0]
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    assert request.get_header("Authorization") == f"Basic {token}"
    output = capsys.readouterr().out
    assert username not in output
    assert password not in output
    assert token not in output


@pytest.mark.parametrize("secret", ["missing-separator", ":password", "user:"])
def test_portal_auth_header_rejects_malformed_secret(monkeypatch, secret):
    monkeypatch.setattr(
        etl.boto3,
        "client",
        lambda _service, **_kwargs: _SecretsClient(secret),
    )

    with pytest.raises(ValueError, match="malformed"):
        etl._portal_basic_auth_header()


def test_secret_failure_is_warning_only_and_redacted(monkeypatch, capsys):
    secret_material = "never-log-service-password"
    urlopen = MagicMock(return_value=_Response())

    def _broken_client(_service, **_kwargs):
        raise RuntimeError(secret_material)

    monkeypatch.setattr(etl.boto3, "client", _broken_client)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    etl._refresh_api_cache()

    urlopen.assert_not_called()
    output = capsys.readouterr().out
    assert "WARN" in output
    assert secret_material not in output
