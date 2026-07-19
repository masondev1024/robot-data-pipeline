import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts/require_aws_account.sh"


def _fake_aws(tmp_path: Path, *, account: str = "123456789012", exit_code: int = 0):
    binary = tmp_path / "aws"
    binary.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' '{account}'\n"
        f"exit {exit_code}\n"
    )
    binary.chmod(0o755)


def _run(tmp_path: Path, expected: str | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    if expected is None:
        env.pop("EXPECTED_AWS_ACCOUNT_ID", None)
    else:
        env["EXPECTED_AWS_ACCOUNT_ID"] = expected
    return subprocess.run(
        ["bash", str(GUARD)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_guard_rejects_missing_expected_account(tmp_path: Path):
    _fake_aws(tmp_path)
    result = _run(tmp_path, None)
    assert result.returncode == 2
    assert "EXPECTED_AWS_ACCOUNT_ID" in result.stderr


def test_guard_accepts_matching_sts_account(tmp_path: Path):
    _fake_aws(tmp_path, account="123456789012")
    result = _run(tmp_path, "123456789012")
    assert result.returncode == 0
    assert "verified" in result.stdout


def test_guard_rejects_different_sts_account(tmp_path: Path):
    _fake_aws(tmp_path, account="999999999999")
    result = _run(tmp_path, "123456789012")
    assert result.returncode == 3
    assert "refusing AWS changes" in result.stderr


def test_guard_rejects_invalid_aws_session(tmp_path: Path):
    _fake_aws(tmp_path, exit_code=1)
    result = _run(tmp_path, "123456789012")
    assert result.returncode == 4
    assert "STS identity" in result.stderr
