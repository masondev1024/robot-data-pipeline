"""Prevent flagship Bedrock contract tests from being disabled again."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_bedrock_contract_modules_have_no_global_skip():
    for relative_path in (
        "tests/api/test_chat.py",
        "tests/etl/test_bedrock_report.py",
    ):
        source = (ROOT / relative_path).read_text()
        assert "pytestmark = pytest.mark.skip" not in source, relative_path
