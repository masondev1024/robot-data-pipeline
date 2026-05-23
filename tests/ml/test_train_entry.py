"""Unit tests for SageMaker XGBoost entry point (train_entry.py).

Task 8.2: Multi-class — 입력 CSV 컬럼은 [label, sample_weight, 5 features].
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd


def _write_train_csv(train_dir: Path, n_rows: int = 4) -> None:
    """[label, sample_weight, 5 features] 7열 CSV 작성 (header 없음)."""
    df = pd.DataFrame({
        "label":         [0, 2, 1, 0][:n_rows],
        "sample_weight": [1.0, 50.0, 50.0, 1.0][:n_rows],
        "avg_motor_temp": [70.0, 88.0, 92.0, 60.0][:n_rows],
        "max_motor_temp": [85.0, 95.0, 110.0, 70.0][:n_rows],
        "battery_drain":  [10, 20, 30, 5][:n_rows],
        "active_hours":   [8, 8, 12, 4][:n_rows],
        "max_temp_load_ratio": [1.5, 2.8, 3.2, 1.1][:n_rows],
    })
    df.to_csv(train_dir / "train.csv", index=False, header=False)


class TestParseArgs:
    def test_parse_args_reads_sm_model_dir(self):
        with patch.dict(os.environ, {"SM_MODEL_DIR": "/custom/model/dir"}):
            with patch("sys.argv", ["train_entry.py"]):
                from src.ml import train_entry
                args = train_entry.parse_args()
                assert args.model_dir == "/custom/model/dir"

    def test_parse_args_reads_sm_channel_train(self):
        with patch.dict(os.environ, {"SM_CHANNEL_TRAIN": "/custom/train/dir"}):
            with patch("sys.argv", ["train_entry.py"]):
                from src.ml import train_entry
                args = train_entry.parse_args()
                assert args.train_dir == "/custom/train/dir"

    def test_parse_args_default_objective_is_multi_softprob(self):
        with patch("sys.argv", ["train_entry.py"]):
            from src.ml import train_entry
            args = train_entry.parse_args()
            assert args.objective == "multi:softprob"
            assert args.num_class == 6
            assert args.eval_metric == "mlogloss"


class TestFeatureColumns:
    def test_feature_cols_constant_correct(self):
        """FEATURE_COLS 상수가 5개 feature 만 포함 (label/sample_weight 제외)."""
        from src.ml import train_entry

        assert train_entry.FEATURE_COLS == [
            "avg_motor_temp",
            "max_motor_temp",
            "battery_drain",
            "active_hours",
            "max_temp_load_ratio",
        ]

    def test_column_names_includes_sample_weight(self):
        from src.ml import train_entry

        assert train_entry.COLUMN_NAMES[0] == "label"
        assert train_entry.COLUMN_NAMES[1] == "sample_weight"
        assert len(train_entry.COLUMN_NAMES) == 7


class TestDataFrameProcessing:
    def test_dmatrix_called_with_weight_kwarg(self):
        """xgb.DMatrix 호출 시 weight=sample_weight 칼럼 전달 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            train_dir = Path(tmpdir) / "train"
            model_dir = Path(tmpdir) / "model"
            train_dir.mkdir()
            model_dir.mkdir()
            _write_train_csv(train_dir, n_rows=4)

            with patch("xgboost.train"):
                with patch("xgboost.DMatrix") as mock_dmatrix:
                    mock_dmatrix.return_value = MagicMock()
                    with patch.dict(os.environ, {
                        "SM_MODEL_DIR": str(model_dir),
                        "SM_CHANNEL_TRAIN": str(train_dir),
                    }):
                        with patch("sys.argv", ["train_entry.py"]):
                            from src.ml import train_entry
                            train_entry.main()

                    call = mock_dmatrix.call_args
                    X = call[0][0]
                    assert X.shape == (4, 5), "X must be (4 rows, 5 features)"
                    # weight kwarg
                    weight = call.kwargs.get("weight")
                    assert weight is not None
                    assert list(weight) == [1.0, 50.0, 50.0, 1.0]

    def test_xgb_train_receives_multi_class_params(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            train_dir = Path(tmpdir) / "train"
            model_dir = Path(tmpdir) / "model"
            train_dir.mkdir()
            model_dir.mkdir()
            _write_train_csv(train_dir, n_rows=4)

            with patch("xgboost.train") as mock_train:
                mock_train.return_value = MagicMock()
                with patch("xgboost.DMatrix"):
                    with patch.dict(os.environ, {
                        "SM_MODEL_DIR": str(model_dir),
                        "SM_CHANNEL_TRAIN": str(train_dir),
                    }):
                        with patch("sys.argv", ["train_entry.py"]):
                            from src.ml import train_entry
                            train_entry.main()

                    call = mock_train.call_args
                    params = call[0][0]
                    assert params["objective"] == "multi:softprob"
                    assert params["num_class"] == 6
                    assert params["eval_metric"] == "mlogloss"


class TestModelOutput:
    def test_model_saved_to_model_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            train_dir = Path(tmpdir) / "train"
            model_dir = Path(tmpdir) / "model"
            train_dir.mkdir()
            model_dir.mkdir()
            _write_train_csv(train_dir, n_rows=2)

            with patch("xgboost.train") as mock_train:
                with patch("xgboost.DMatrix"):
                    mock_booster = MagicMock()
                    saved_paths = []
                    mock_booster.save_model.side_effect = lambda p: saved_paths.append(p)
                    mock_train.return_value = mock_booster

                    with patch.dict(os.environ, {
                        "SM_MODEL_DIR": str(model_dir),
                        "SM_CHANNEL_TRAIN": str(train_dir),
                    }):
                        with patch("sys.argv", ["train_entry.py"]):
                            from src.ml import train_entry
                            train_entry.main()

                    assert saved_paths == [str(model_dir / "xgboost-model")]
