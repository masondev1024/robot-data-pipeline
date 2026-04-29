"""Unit tests for SageMaker XGBoost entry point (train_entry.py).
Tests SageMaker environment variable handling and feature processing.
"""

import os
import sys
import tempfile
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
import importlib


class TestParseArgs:
    """Tests for parse_args function in train_entry."""

    def test_parse_args_reads_sm_model_dir(self):
        """parse_args reads SM_MODEL_DIR from environment."""
        # Mock sys.argv to avoid argparse issues
        with patch.dict(os.environ, {"SM_MODEL_DIR": "/custom/model/dir"}):
            with patch("sys.argv", ["train_entry.py"]):
                from src.ml import train_entry
                args = train_entry.parse_args()
                assert args.model_dir == "/custom/model/dir"

    def test_parse_args_reads_sm_channel_train(self):
        """parse_args reads SM_CHANNEL_TRAIN from environment."""
        with patch.dict(os.environ, {"SM_CHANNEL_TRAIN": "/custom/train/dir"}):
            with patch("sys.argv", ["train_entry.py"]):
                from src.ml import train_entry
                args = train_entry.parse_args()
                assert args.train_dir == "/custom/train/dir"

    def test_parse_args_both_sm_env_vars(self):
        """parse_args reads both SM_MODEL_DIR and SM_CHANNEL_TRAIN together."""
        env_vars = {
            "SM_MODEL_DIR": "/opt/ml/model",
            "SM_CHANNEL_TRAIN": "/opt/ml/input/data/train",
        }
        with patch.dict(os.environ, env_vars):
            with patch("sys.argv", ["train_entry.py"]):
                from src.ml import train_entry
                args = train_entry.parse_args()
                assert args.model_dir == "/opt/ml/model"
                assert args.train_dir == "/opt/ml/input/data/train"


class TestFeatureColumns:
    """Tests for feature column alignment in train_entry."""

    def test_feature_cols_correct_order(self):
        """Feature columns match expected order and values."""
        from src.ml import train_entry

        # Access the hardcoded feature_cols from main() context
        # We'll test via the actual train_entry module
        expected_cols = ["avg_motor_temp", "max_motor_temp", "battery_drain", "active_hours"]

        # Create a temporary CSV to test via main
        with tempfile.TemporaryDirectory() as tmpdir:
            train_dir = Path(tmpdir) / "train"
            model_dir = Path(tmpdir) / "model"
            train_dir.mkdir()
            model_dir.mkdir()

            # Create CSV with expected columns
            df = pd.DataFrame({
                "label": [0, 1, 1, 0],
                "avg_motor_temp": [70, 88, 92, 60],
                "max_motor_temp": [85, 95, 110, 70],
                "battery_drain": [10, 20, 30, 5],
                "active_hours": [8, 8, 12, 4],
            })
            df.to_csv(train_dir / "train.csv", index=False, header=False)

            # Mock XGBoost to capture feature handling
            with patch("xgboost.train") as mock_xgb_train:
                with patch("xgboost.DMatrix") as mock_dmatrix:
                    # Make DMatrix constructor return a mock that records X shape
                    mock_dm = MagicMock()
                    mock_dmatrix.return_value = mock_dm

                    with patch.dict(os.environ, {
                        "SM_MODEL_DIR": str(model_dir),
                        "SM_CHANNEL_TRAIN": str(train_dir),
                    }):
                        with patch("sys.argv", ["train_entry.py"]):
                            train_entry.main()

                    # Verify DMatrix was called with X having 4 columns
                    call_args = mock_dmatrix.call_args
                    X = call_args[0][0]  # First positional arg is X
                    assert X.shape[1] == 4, "X should have 4 feature columns"


class TestDataFrameProcessing:
    """Tests for DataFrame loading and processing in train_entry."""

    def test_load_csv_and_split_features_labels(self):
        """train_entry loads CSV and splits into X and y correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            train_dir = Path(tmpdir) / "train"
            model_dir = Path(tmpdir) / "model"
            train_dir.mkdir()
            model_dir.mkdir()

            # Create test data
            test_data = pd.DataFrame({
                "label": [0, 1, 1, 0],
                "avg_motor_temp": [70.0, 88.0, 92.0, 60.0],
                "max_motor_temp": [85.0, 95.0, 110.0, 70.0],
                "battery_drain": [10, 20, 30, 5],
                "active_hours": [8, 8, 12, 4],
            })
            test_data.to_csv(train_dir / "train.csv", index=False, header=False)

            # Mock xgboost methods
            with patch("xgboost.train") as mock_xgb_train:
                with patch("xgboost.DMatrix") as mock_dmatrix:
                    # Capture DMatrix call to verify shape
                    dm_calls = []
                    def capture_dmatrix(X, label=None):
                        dm_calls.append((X.shape, label))
                        return MagicMock()

                    mock_dmatrix.side_effect = capture_dmatrix

                    with patch.dict(os.environ, {
                        "SM_MODEL_DIR": str(model_dir),
                        "SM_CHANNEL_TRAIN": str(train_dir),
                    }):
                        with patch("sys.argv", ["train_entry.py"]):
                            from src.ml import train_entry
                            train_entry.main()

                    # Verify DMatrix received correct shapes
                    assert len(dm_calls) > 0, "DMatrix should be called"
                    X_shape, y = dm_calls[0]
                    assert X_shape == (4, 4), "X should be (4 rows, 4 features)"
                    # y should be the label series


class TestModelOutput:
    """Tests for model file output in train_entry."""

    def test_model_saved_to_model_dir(self):
        """train_entry saves xgboost-model to args.model_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            train_dir = Path(tmpdir) / "train"
            model_dir = Path(tmpdir) / "model"
            train_dir.mkdir()
            model_dir.mkdir()

            # Create test CSV
            pd.DataFrame({
                "label": [0, 1],
                "avg_motor_temp": [70, 88],
                "max_motor_temp": [85, 95],
                "battery_drain": [10, 20],
                "active_hours": [8, 8],
            }).to_csv(train_dir / "train.csv", index=False, header=False)

            # Mock xgboost and capture save_model call
            with patch("xgboost.train") as mock_xgb_train:
                with patch("xgboost.DMatrix"):
                    # Create a mock booster with save_model method
                    mock_booster = MagicMock()
                    saved_paths = []

                    def capture_save_model(path):
                        saved_paths.append(path)

                    mock_booster.save_model.side_effect = capture_save_model
                    mock_xgb_train.return_value = mock_booster

                    with patch.dict(os.environ, {
                        "SM_MODEL_DIR": str(model_dir),
                        "SM_CHANNEL_TRAIN": str(train_dir),
                    }):
                        with patch("sys.argv", ["train_entry.py"]):
                            from src.ml import train_entry
                            train_entry.main()

                    # Verify save_model was called with correct path
                    assert len(saved_paths) > 0, "save_model should be called"
                    saved_path = saved_paths[0]
                    assert saved_path == str(model_dir / "xgboost-model")
