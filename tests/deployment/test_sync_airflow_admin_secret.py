import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/sync_airflow_admin_secret.sh"
PASSWORD = "portfolio-only-secret"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(0o755)


def _fake_commands(tmp_path: Path, *, account: str, secret_exit: int = 0) -> Path:
    calls = tmp_path / "calls.log"
    _write_executable(
        tmp_path / "aws",
        "#!/usr/bin/env bash\n"
        "printf 'aws %s\\n' \"$*\" >> \"$FAKE_CALLS\"\n"
        "if [[ \"$1 $2\" == 'sts get-caller-identity' ]]; then\n"
        f"  printf '%s\\n' '{account}'\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1 $2\" == 'secretsmanager get-secret-value' ]]; then\n"
        f"  [[ {secret_exit} -eq 0 ]] || exit {secret_exit}\n"
        f"  printf '%s' '{PASSWORD}'\n"
        "  exit 0\n"
        "fi\n"
        "exit 64\n",
    )
    _write_executable(
        tmp_path / "kubectl",
        "#!/usr/bin/env bash\n"
        "printf 'kubectl %s\\n' \"$*\" >> \"$FAKE_CALLS\"\n"
        "if [[ \"$*\" == *'create namespace'* ]]; then\n"
        "  : > \"$FAKE_NAMESPACE\"\n"
        "  printf '%s\\n' 'apiVersion: v1' 'kind: Namespace'\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$*\" == *'create secret generic'* ]]; then\n"
        "  IFS= read -r secret\n"
        "  printf '%s' \"$secret\" > \"$FAKE_CAPTURE\"\n"
        "  printf '%s\\n' 'apiVersion: v1' 'kind: Secret'\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$*\" == *'apply -f -'* ]]; then\n"
        "  grep -q 'kind:'\n"
        "  status=$?\n"
        "  printf 'applied\\n' >> \"$FAKE_APPLIED\"\n"
        "  exit $status\n"
        "fi\n"
        "exit 64\n",
    )
    return calls


def _run(tmp_path: Path, *, account: str, expected: str, secret_exit: int = 0):
    calls = _fake_commands(tmp_path, account=account, secret_exit=secret_exit)
    capture = tmp_path / "captured-secret"
    applied = tmp_path / "applied"
    namespace = tmp_path / "namespace"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path}:{env['PATH']}",
            "AWS_ACCOUNT_ID": expected,
            "AWS_REGION": "eu-west-1",
            "ROBOT_ENV_FILE": str(tmp_path / "absent.env"),
            "FAKE_CALLS": str(calls),
            "FAKE_CAPTURE": str(capture),
            "FAKE_APPLIED": str(applied),
            "FAKE_NAMESPACE": str(namespace),
        }
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, calls.read_text(), capture, applied, namespace


def test_account_mismatch_stops_before_secret_or_kubernetes_access(tmp_path: Path):
    result, calls, capture, applied, namespace = _run(
        tmp_path, account="999999999999", expected="123456789012"
    )

    assert result.returncode == 3
    assert "secretsmanager" not in calls
    assert "kubectl" not in calls
    assert not capture.exists()
    assert not applied.exists()
    assert not namespace.exists()


def test_matching_account_syncs_secret_through_stdin(tmp_path: Path):
    result, calls, capture, applied, namespace = _run(
        tmp_path, account="123456789012", expected="123456789012"
    )

    assert result.returncode == 0
    assert "secretsmanager get-secret-value" in calls
    assert "--from-file=password=/dev/stdin" in calls
    assert capture.read_text() == PASSWORD
    assert applied.exists()
    assert len(applied.read_text().splitlines()) == 2
    assert namespace.exists()


def test_password_is_never_written_to_process_output_or_arguments(tmp_path: Path):
    result, calls, _, _, _ = _run(
        tmp_path, account="123456789012", expected="123456789012"
    )

    assert PASSWORD not in result.stdout
    assert PASSWORD not in result.stderr
    assert PASSWORD not in calls


def test_secret_lookup_failure_aborts_before_kubernetes_access(tmp_path: Path):
    result, calls, capture, applied, namespace = _run(
        tmp_path,
        account="123456789012",
        expected="123456789012",
        secret_exit=42,
    )

    assert result.returncode != 0
    assert "secretsmanager get-secret-value" in calls
    assert "kubectl" not in calls
    assert not capture.exists()
    assert not applied.exists()
    assert not namespace.exists()
