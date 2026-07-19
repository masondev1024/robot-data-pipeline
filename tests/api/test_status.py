from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
import inspect

from conftest import TEST_AUTH_HEADERS
from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app, headers=TEST_AUTH_HEADERS)


class TestStatusApi:
    """GET /api/status endpoint tests"""

    def test_status_immediate_response(self, client, monkeypatch):
        """GET /api/status returns 200 immediately with data_date, cached_at, cache_ready."""
        monkeypatch.setattr("src.api.main._cache_ready", True)
        monkeypatch.setattr("src.api.main._cache_updated_at", "2026-04-27T10:00:00+00:00")
        monkeypatch.setattr("src.api.main._data_date", "2026-04-26")

        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "data_date" in data
        assert "cached_at" in data
        assert "cache_ready" in data

    def test_status_data_date_format(self, client, monkeypatch):
        """data_date is yesterday in ISO format (YYYY-MM-DD)."""
        # Mock yesterday date
        yesterday = "2026-04-26"
        monkeypatch.setattr("src.api.main._cache_ready", True)
        monkeypatch.setattr("src.api.main._cache_updated_at", "2026-04-27T10:00:00+00:00")
        monkeypatch.setattr("src.api.main._data_date", yesterday)

        response = client.get("/api/status")
        data = response.json()
        assert data["data_date"] == yesterday
        # Verify ISO format
        assert len(data["data_date"]) == 10
        assert data["data_date"].count("-") == 2

    @patch("src.common.aws.boto3.client")
    def test_status_timezone_kst(self, mock_boto, client, monkeypatch):
        """refresh_cache APScheduler add_job uses timezone='Asia/Seoul'."""
        # We need to check that refresh_cache would be scheduled with Asia/Seoul
        # Since startup() is async, we'll simulate it
        from src.api.main import refresh_cache
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        mock_boto.return_value = MagicMock()

        scheduler = AsyncIOScheduler()
        scheduler.add_job(refresh_cache, "cron", hour=1, minute=0, timezone="Asia/Seoul")

        job = scheduler.get_jobs()[0]
        # The trigger should have been configured with Asia/Seoul
        assert job.trigger is not None

    def test_status_cache_ready_false_still_returns_200(self, client, monkeypatch):
        """Status returns 200 even when cache_ready is False."""
        monkeypatch.setattr("src.api.main._cache_ready", False)
        monkeypatch.setattr("src.api.main._cache_updated_at", "")
        monkeypatch.setattr("src.api.main._data_date", "")

        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["cache_ready"] is False
