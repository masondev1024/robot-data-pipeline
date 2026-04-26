import pathlib
import sys
from unittest.mock import MagicMock

_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "dags"))

# Mock sagemaker and xgboost modules (not available locally)
sys.modules["sagemaker"] = MagicMock()
sys.modules["sagemaker.xgboost"] = MagicMock()
sys.modules["xgboost"] = MagicMock()
