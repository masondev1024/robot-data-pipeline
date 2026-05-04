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


@pytest.fixture(scope="session", autouse=True)
def _disable_portal_basic_auth():
    """src.api.main BasicAuthMiddleware 를 fallback 경로(creds=None → 통과) 로 강제.
    Why: 사용자 로컬 AWS creds 가 있으면 _get_basic_auth_creds 가 진짜 Secrets Manager 값을
    read 해서 인증이 켜지고 TestClient 요청이 모두 401. fallback (개발/로컬) 경로 활용 — 코드 변경 X."""
    try:
        import src.api.main as _main

        _main._get_basic_auth_creds = lambda: None
    except Exception:
        pass
