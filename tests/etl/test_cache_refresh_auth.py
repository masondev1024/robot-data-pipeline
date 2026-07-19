"""Authentication contract for the Airflow-to-Portal cache refresh call."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock
import urllib.error
import urllib.request

from botocore.exceptions import ClientError
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


@pytest.mark.parametrize("status", [401, 503])
def test_http_failure_logs_sanitized_status(monkeypatch, capsys, status):
    monkeypatch.setattr(
        etl.boto3,
        "client",
        lambda _service, **_kwargs: _SecretsClient("service:password"),
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        MagicMock(
            side_effect=urllib.error.HTTPError(
                url="http://portal/api/refresh",
                code=status,
                msg="server-provided-reason",
                hdrs=None,
                fp=None,
            )
        ),
    )

    etl._refresh_api_cache()

    output = capsys.readouterr().out
    assert f"category=http status={status}" in output
    assert "server-provided-reason" not in output


def test_access_denied_logs_sanitized_aws_error_code(monkeypatch, capsys):
    secret_material = "never-log-access-denied-detail"
    error = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                "Message": secret_material,
            }
        },
        "GetSecretValue",
    )
    monkeypatch.setattr(
        etl.boto3,
        "client",
        MagicMock(side_effect=error),
    )

    etl._refresh_api_cache()

    output = capsys.readouterr().out
    assert "category=aws code=AccessDeniedException" in output
    assert secret_material not in output
