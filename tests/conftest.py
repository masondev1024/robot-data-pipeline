import pathlib
import sys
from unittest.mock import MagicMock

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "dags"))

# Mock sagemaker and xgboost modules (not available locally)
sys.modules["sagemaker"] = MagicMock()
sys.modules["sagemaker.xgboost"] = MagicMock()
sys.modules["xgboost"] = MagicMock()

TEST_AUTH_HEADERS = {
    "Authorization": "Basic dGVzdC11c2VyOnRlc3QtcGFzc3dvcmQ="
}


@pytest.fixture(scope="session", autouse=True)
def _set_test_portal_credentials():
    """Use deterministic valid credentials; tests must still authenticate explicitly."""
    try:
        import src.api.main as _main

        previous = _main._basic_auth_creds
        _main._basic_auth_creds = ("test-user", "test-password")
    except Exception:
        yield
    else:
        yield
        _main._basic_auth_creds = previous
