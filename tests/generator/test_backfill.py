"""src/generator/backfill.py 단위 테스트.

모든 boto3 호출은 Mock — 실 KDS 호출 0건.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.generator import backfill


# ── generate_timestamps ──────────────────────────────────────────

class TestGenerateTimestamps:
    def test_zero_days_returns_empty(self):
        assert backfill.generate_timestamps(0, 5) == []

    def test_negative_days_returns_empty(self):
        assert backfill.generate_timestamps(-1, 5) == []

    def test_zero_interval_raises(self):
        with pytest.raises(ValueError):
            backfill.generate_timestamps(7, 0)

    def test_seven_days_five_min(self):
        # 7d × 24h × 12 (5-min interval) = 2,016 timestamps per robot
        ts = backfill.generate_timestamps(7, 5)
        assert len(ts) == 7 * 24 * 12

    def test_one_day_60_min(self):
        # 1d × 24 = 24 timestamps
        ts = backfill.generate_timestamps(1, 60)
        assert len(ts) == 24

    def test_timestamps_within_past_days(self):
        ts = backfill.generate_timestamps(3, 60)
        now = datetime.now(timezone.utc)
        three_days_ago = now - timedelta(days=3, minutes=1)
        assert all(three_days_ago <= t <= now for t in ts)

    def test_timestamps_strictly_increasing(self):
        ts = backfill.generate_timestamps(2, 30)
        assert all(ts[i] < ts[i + 1] for i in range(len(ts) - 1))


# ── generate_record ──────────────────────────────────────────────

PROFILE = {
    "robot_id":        "ROBOT-00001",
    "pos_x":           37.5,
    "pos_y":           126.9,
    "motor_temp_base": 75.0,
    "load_base":       50,
    "drain_factor":    1.5,
    "is_faulty":       False,
    "battery":         80,
}

FAULTY_PROFILE = {**PROFILE, "robot_id": "ROBOT-00002", "is_faulty": True}


class TestGenerateRecord:
    def test_required_fields(self):
        t = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
        rec = backfill.generate_record(PROFILE, t)
        for key in ("robot_id", "pos_x", "pos_y", "battery_level",
                    "current_load", "motor_temp", "timestamp"):
            assert key in rec

    def test_timestamp_format_iso8601(self):
        t = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
        rec = backfill.generate_record(PROFILE, t)
        assert rec["timestamp"] == "2026-04-25T12:00:00Z"

    def test_robot_id_matches_profile(self):
        t = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
        rec = backfill.generate_record(PROFILE, t)
        assert rec["robot_id"] == "ROBOT-00001"

    def test_battery_level_in_range(self):
        t = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
        for _ in range(50):
            rec = backfill.generate_record(PROFILE, t)
            assert 0 <= rec["battery_level"] <= 100

    def test_motor_temp_clamped(self):
        t = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
        for _ in range(100):
            rec = backfill.generate_record(PROFILE, t)
            assert 55.0 <= rec["motor_temp"] <= 110.0

    def test_current_load_in_range(self):
        t = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
        for _ in range(50):
            rec = backfill.generate_record(PROFILE, t)
            assert 0 <= rec["current_load"] <= 100

    def test_faulty_robot_can_spike(self):
        # is_faulty 로봇은 5% 확률로 spike → 100회 시도 시 1건이라도 90+ 이면 OK
        t = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
        temps = [
            backfill.generate_record(FAULTY_PROFILE, t)["motor_temp"]
            for _ in range(200)
        ]
        # faulty robot은 motor_base=75 이지만 spike 시 91~99 도달 가능
        assert max(temps) >= 90.0


# ── chunked ──────────────────────────────────────────────────────

class TestChunked:
    def test_exact_multiple(self):
        chunks = list(backfill.chunked(range(10), 5))
        assert chunks == [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]]

    def test_remainder(self):
        chunks = list(backfill.chunked(range(7), 3))
        assert chunks == [[0, 1, 2], [3, 4, 5], [6]]

    def test_empty(self):
        assert list(backfill.chunked([], 5)) == []


# ── push_to_kinesis (Mock KDS) ───────────────────────────────────

class TestPushToKinesis:
    def test_single_batch(self):
        client = MagicMock()
        records = [{"robot_id": f"ROBOT-{i:05d}", "timestamp": "2026-04-25T12:00:00Z"}
                   for i in range(100)]
        total = backfill.push_to_kinesis(records, "test-stream", client)
        assert total == 100
        client.put_records.assert_called_once()
        kwargs = client.put_records.call_args.kwargs
        assert kwargs["StreamName"] == "test-stream"
        assert len(kwargs["Records"]) == 100

    def test_multiple_batches_at_500_limit(self):
        client = MagicMock()
        records = [{"robot_id": f"ROBOT-{i:05d}", "timestamp": "x"}
                   for i in range(1250)]  # 500 + 500 + 250
        total = backfill.push_to_kinesis(records, "test-stream", client)
        assert total == 1250
        assert client.put_records.call_count == 3
        sizes = [len(c.kwargs["Records"]) for c in client.put_records.call_args_list]
        assert sizes == [500, 500, 250]

    def test_record_serialized_to_json_bytes(self):
        client = MagicMock()
        records = [{"robot_id": "ROBOT-00001", "timestamp": "2026-04-25T12:00:00Z"}]
        backfill.push_to_kinesis(records, "test-stream", client)
        sent = client.put_records.call_args.kwargs["Records"][0]
        assert sent["PartitionKey"] == "ROBOT-00001"
        # Data 가 json bytes 인지 검증
        assert json.loads(sent["Data"]) == records[0]


# ── backfill_records (제너레이터 결합) ─────────────────────────────

class TestBackfillRecords:
    def test_total_count(self):
        profiles = [PROFILE, FAULTY_PROFILE]
        timestamps = [
            datetime(2026, 4, 25, h, 0, tzinfo=timezone.utc)
            for h in range(3)
        ]
        recs = list(backfill.backfill_records(profiles, timestamps))
        assert len(recs) == len(profiles) * len(timestamps)  # 2 × 3 = 6

    def test_each_profile_has_each_timestamp(self):
        profiles = [PROFILE, FAULTY_PROFILE]
        timestamps = [
            datetime(2026, 4, 25, h, 0, tzinfo=timezone.utc)
            for h in range(2)
        ]
        recs = list(backfill.backfill_records(profiles, timestamps))
        # 각 robot_id가 각 timestamp에 등장
        pairs = {(r["robot_id"], r["timestamp"]) for r in recs}
        assert len(pairs) == 4  # 2 robots × 2 timestamps


# ── main entry (env vars + Mock boto3) ───────────────────────────

class TestMainEntry:
    def test_zero_days_exits_early(self, capsys, monkeypatch, tmp_path):
        # CSV 파일 만들어두기 (load_profiles 호출 안 가야 함)
        monkeypatch.setenv("BACKFILL_DAYS", "0")
        monkeypatch.setenv("KINESIS_STREAM_NAME", "test-stream")

        with patch("src.generator.backfill.boto3.client") as mock_boto:
            backfill.main()

        out = capsys.readouterr().out
        assert "backfill mode disabled" in out
        # boto3 client 호출 안 일어났어야 함
        mock_boto.assert_not_called()

    def test_main_uses_env_region(self, monkeypatch, tmp_path):
        # 작은 CSV로 빠른 테스트
        csv_path = tmp_path / "seed.csv"
        csv_path.write_text(
            "Process temperature [K],Rotational speed [rpm],Tool wear [min],Machine failure\n"
            "310,1500,30,0\n"
        )
        monkeypatch.setenv("BACKFILL_DAYS", "1")
        monkeypatch.setenv("BACKFILL_INTERVAL_MIN", "720")  # 1 timestamp per 12h → 2/day
        monkeypatch.setenv("ROBOT_COUNT", "2")
        monkeypatch.setenv("KINESIS_STREAM_NAME", "test-stream")
        monkeypatch.setenv("SEED_CSV_PATH", str(csv_path))
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")

        with patch("src.generator.backfill.boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            backfill.main()

        # boto3.client 가 region eu-west-1 로 호출됨
        mock_boto.assert_called_once_with("kinesis", region_name="eu-west-1")
        # put_records 1회 이상 호출 (records=2 robots × 2 timestamps = 4 → 1 batch)
        assert mock_client.put_records.called
