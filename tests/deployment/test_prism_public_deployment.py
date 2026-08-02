"""Contract tests for the isolated, public PRISM demo deployment."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PRISM_ROOT = REPOSITORY_ROOT / "prism"
VALID_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0"
VALID_BCRYPT_HASHES = {
    "2a-minimum-cost": "$2a$04$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0",
    "2b-typical-cost": VALID_BCRYPT_HASH,
    "2b-bcrypt-base64": (
        "$2b$12$./cdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0"
    ),
    "2y-maximum-cost": "$2y$31$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0",
}
INVALID_BCRYPT_HASHES = {
    "unsupported-version": "$2x$12$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0",
    "cost-too-low": "$2b$03$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0",
    "cost-too-high": "$2b$32$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0",
    "truncated": "$2b$12$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "non-bcrypt-character": "$2b$12$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0+",
    "overlong": "$2b$12$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ00",
    "missing-cost-separator": "$2b$12abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0",
}


def write_public_demo_env(
    path: Path,
    *,
    public_domain: str = "prism.example.com",
    auth_hash: str = VALID_BCRYPT_HASH,
) -> None:
    path.write_text(
        "\n".join(
            (
                f"PUBLIC_DOMAIN={public_domain}",
                "CADDY_ACME_EMAIL=ops@example.com",
                "CADDY_BASIC_AUTH_USER=reviewer",
                f"CADDY_BASIC_AUTH_HASH='{auth_hash}'",
                "",
            )
        )
    )
    path.chmod(0o600)


def load_public_compose() -> dict:
    return yaml.safe_load((PRISM_ROOT / "docker-compose.public.yml").read_text())


def test_public_compose_keeps_operator_app_private_and_hardened() -> None:
    """Catch a public topology that exposes or weakens the app container."""
    compose = load_public_compose()

    assert compose["name"] == "prism-public"
    assert set(compose["services"]) == {"caddy", "operator-app"}

    app = compose["services"]["operator-app"]
    assert "ports" not in app
    assert app["expose"] == ["8503"]
    assert app["environment"] == {
        "HOME": "/tmp",
        "PRISM_MODE": "demo",
        "PRISM_OFFLINE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "2026",
        "STREAMLIT_SERVER_PORT": "8503",
    }
    assert app["volumes"] == ["prism-public-data:/app/data"]
    assert app["user"] == "10001:10001"
    assert app["read_only"] is True
    assert app["cap_drop"] == ["ALL"]
    assert app["security_opt"] == ["no-new-privileges:true"]
    assert app["tmpfs"] == ["/tmp:rw,noexec,nosuid,size=64m"]
    assert app["restart"] == "unless-stopped"
    assert app["cpus"] == "1.0"
    assert app["mem_limit"] == "2g"
    assert app["pids_limit"] == 256
    assert app["networks"] == ["app"]
    assert "env_file" not in app
    assert app["build"] == {
        "context": "..",
        "dockerfile": "prism/Dockerfile.app",
        "args": {"PUBLIC_STREAMLIT_CONFIG": "true"},
    }
    assert app["image"] == "${PRISM_PUBLIC_OPERATOR_IMAGE:-prism-public-operator:local}"


def test_caddy_is_the_only_public_entrypoint_and_has_immutable_config() -> None:
    """Catch public port exposure, mutable Caddy config, or missing proxy readiness."""
    compose = load_public_compose()
    caddy = compose["services"]["caddy"]

    assert caddy["ports"] == [
        "${PRISM_HTTP_PORT:-80}:80",
        "${PRISM_HTTPS_PORT:-443}:443",
        "${PRISM_HTTPS_PORT:-443}:443/udp",
    ]
    assert caddy["depends_on"] == {"operator-app": {"condition": "service_healthy"}}
    assert caddy["build"] == {
        "context": "..",
        "dockerfile": "prism/Dockerfile.caddy",
    }
    assert caddy["image"] == "${PRISM_PUBLIC_CADDY_IMAGE:-prism-public-caddy:local}"
    assert caddy["environment"] == {
        "PUBLIC_DOMAIN": "${PUBLIC_DOMAIN:?PUBLIC_DOMAIN is required}",
        "CADDY_ACME_EMAIL": "${CADDY_ACME_EMAIL:?CADDY_ACME_EMAIL is required}",
        "CADDY_BASIC_AUTH_USER": "${CADDY_BASIC_AUTH_USER:?CADDY_BASIC_AUTH_USER is required}",
        "CADDY_BASIC_AUTH_HASH": "${CADDY_BASIC_AUTH_HASH:?CADDY_BASIC_AUTH_HASH is required}",
    }
    assert caddy["cap_drop"] == ["ALL"]
    assert caddy["cap_add"] == ["NET_BIND_SERVICE"]
    assert caddy["read_only"] is True
    assert caddy["security_opt"] == ["no-new-privileges:true"]
    assert caddy["restart"] == "unless-stopped"
    assert caddy["cpus"] == "0.50"
    assert caddy["mem_limit"] == "256m"
    assert caddy["pids_limit"] == 128
    assert caddy["healthcheck"] == {
        "test": [
            "CMD",
            "caddy",
            "validate",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        ],
        "interval": "30s",
        "timeout": "5s",
        "retries": 3,
        "start_period": "10s",
    }
    assert caddy["volumes"] == [
        "caddy-data:/data",
        "caddy-config:/config",
    ]
    assert caddy["networks"] == ["app", "edge"]
    assert "env_file" not in caddy
    assert all("/" not in volume.split(":", 1)[0] for volume in caddy["volumes"])

    dockerfile = (PRISM_ROOT / "Dockerfile.caddy").read_text()
    assert dockerfile.startswith("FROM caddy:2.10.2")
    assert "COPY prism/Caddyfile /etc/caddy/Caddyfile" in dockerfile


def test_public_topology_has_no_cloud_credentials_or_repository_mounts() -> None:
    """Catch host credentials or source paths crossing the public deployment boundary."""
    compose_text = (PRISM_ROOT / "docker-compose.public.yml").read_text().lower()
    assert "aws_" not in compose_text
    assert "bedrock" not in compose_text
    assert "cloudflare" not in compose_text
    assert "env_file" not in compose_text
    assert "../" not in compose_text

    example = (PRISM_ROOT / ".env.public.example").read_text().lower()
    assert "aws_access_key" not in example
    assert "aws_secret" not in example
    assert "cloudflare" not in example
    assert "password" not in example
    assert "$2a$" not in example
    assert "caddy_basic_auth_hash='$2b$...'" in example


def test_public_caddyfile_requires_auth_before_proxying() -> None:
    """Catch a public proxy without local administration disablement and basic auth."""
    caddyfile = (PRISM_ROOT / "Caddyfile").read_text()

    global_options, _, _ = caddyfile.partition("\n}\n\n")
    assert "admin off" in global_options
    assert "email {$CADDY_ACME_EMAIL}" in global_options
    assert "basic_auth bcrypt" in caddyfile
    assert "{$CADDY_BASIC_AUTH_USER}" in caddyfile
    assert "{$CADDY_BASIC_AUTH_HASH}" in caddyfile
    assert "reverse_proxy operator-app:8503" in caddyfile


def test_public_streamlit_image_contracts_protect_runtime_state() -> None:
    """Catch an image that cannot run the app unprivileged with public protections."""
    config = (PRISM_ROOT / "streamlit-public-config.toml").read_text()
    assert "enableCORS = true" in config
    assert "enableXsrfProtection = true" in config

    dockerfile = (PRISM_ROOT / "Dockerfile.app").read_text()
    assert "groupadd --gid 10001 prism" in dockerfile
    assert "useradd --uid 10001 --gid 10001" in dockerfile
    for source in ("apps", "src", "assets", "data", ".streamlit"):
        assert f"COPY --chown=10001:10001 {source} /app/{source}" in dockerfile
    assert "ARG PUBLIC_STREAMLIT_CONFIG=false" in dockerfile
    assert (
        "COPY --chown=10001:10001 prism/streamlit-public-config.toml "
        "/tmp/streamlit-public-config.toml"
    ) in dockerfile
    assert "[ \"$PUBLIC_STREAMLIT_CONFIG\" = true ]" in dockerfile
    assert "cp /tmp/streamlit-public-config.toml /app/.streamlit/config.toml" in dockerfile
    assert "USER " not in dockerfile


def test_dockerignore_excludes_local_demo_database() -> None:
    """Catch a build context that accidentally includes mutable demo data."""
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text().splitlines()
    assert "data/*.duckdb" in dockerignore


@pytest.mark.parametrize(
    "public_domain",
    (
        "http://prism.example.com",
        "https://prism.example.com",
        "prism.example.com:443",
        "prism.example.com/demo",
        "prism .example.com",
        "-prism.example.com",
        "prism-.example.com",
        "prism..example.com",
        "192.0.2.1",
        f"{'a' * 64}.example.com",
    ),
    ids=(
        "http-scheme",
        "https-scheme",
        "port",
        "path",
        "whitespace",
        "leading-hyphen",
        "trailing-hyphen",
        "empty-label",
        "ipv4-address",
        "overlong-label",
    ),
)
def test_prepare_script_rejects_non_fqdn_public_domains(
    tmp_path: Path, public_domain: str
) -> None:
    """A Caddy public address must be a bare FQDN, never a URL or endpoint."""
    prepare_script = PRISM_ROOT / "scripts" / "prepare-public-demo.sh"
    env_file = tmp_path / "prism-public.env"
    write_public_demo_env(env_file, public_domain=public_domain)

    rejected = subprocess.run(
        ["bash", str(prepare_script), "--env-file", str(env_file)],
        text=True,
        capture_output=True,
    )

    assert rejected.returncode != 0
    assert "PUBLIC_DOMAIN" in rejected.stderr


@pytest.mark.parametrize(
    "public_domain",
    ("prism.example.com", "prism-demo.example.com", "xn--bcher-kva.example.com"),
    ids=("standard", "hyphenated-label", "punycode"),
)
def test_prepare_script_accepts_bare_dns_fqdns(
    tmp_path: Path, public_domain: str
) -> None:
    """Normal DNS names, including punycode labels, remain valid public domains."""
    prepare_script = PRISM_ROOT / "scripts" / "prepare-public-demo.sh"
    env_file = tmp_path / "prism-public.env"
    write_public_demo_env(env_file, public_domain=public_domain)

    prepared = subprocess.run(
        ["bash", str(prepare_script), "--env-file", str(env_file)],
        text=True,
        capture_output=True,
    )

    assert prepared.returncode == 0, prepared.stderr


@pytest.mark.parametrize("case_name", tuple(VALID_BCRYPT_HASHES))
def test_prepare_script_accepts_complete_bcrypt_hashes(
    tmp_path: Path, case_name: str
) -> None:
    """Only complete bcrypt forms with supported versions and cost bounds are valid."""
    prepare_script = PRISM_ROOT / "scripts" / "prepare-public-demo.sh"
    env_file = tmp_path / "prism-public.env"
    auth_hash = VALID_BCRYPT_HASHES[case_name]
    write_public_demo_env(env_file, auth_hash=auth_hash)

    prepared = subprocess.run(
        ["bash", str(prepare_script), "--env-file", str(env_file)],
        text=True,
        capture_output=True,
    )

    assert prepared.returncode == 0, prepared.stderr
    assert auth_hash not in prepared.stdout
    assert auth_hash not in prepared.stderr


@pytest.mark.parametrize("case_name", tuple(INVALID_BCRYPT_HASHES))
def test_prepare_script_rejects_malformed_bcrypt_hashes(
    tmp_path: Path, case_name: str
) -> None:
    """Truncation or malformed bcrypt input must fail before Compose receives it."""
    prepare_script = PRISM_ROOT / "scripts" / "prepare-public-demo.sh"
    env_file = tmp_path / "prism-public.env"
    auth_hash = INVALID_BCRYPT_HASHES[case_name]
    write_public_demo_env(env_file, auth_hash=auth_hash)

    rejected = subprocess.run(
        ["bash", str(prepare_script), "--env-file", str(env_file)],
        text=True,
        capture_output=True,
    )

    assert rejected.returncode != 0
    assert auth_hash not in rejected.stdout
    assert auth_hash not in rejected.stderr


def test_public_demo_scripts_validate_host_env_without_leaking_hash(tmp_path: Path) -> None:
    """Host preflight accepts a protected public config without printing its hash."""
    prepare_script = PRISM_ROOT / "scripts" / "prepare-public-demo.sh"
    reset_script = PRISM_ROOT / "scripts" / "reset-public-demo-data.sh"
    env_file = tmp_path / "prism-public.env"
    auth_hash = VALID_BCRYPT_HASH
    write_public_demo_env(env_file)

    assert subprocess.run(
        ["bash", str(prepare_script), "--help"], text=True, capture_output=True
    ).returncode == 0
    assert subprocess.run(
        ["bash", str(reset_script), "--help"], text=True, capture_output=True
    ).returncode == 0

    prepared = subprocess.run(
        ["bash", str(prepare_script), "--env-file", str(env_file)],
        text=True,
        capture_output=True,
    )
    assert prepared.returncode == 0, prepared.stderr
    assert str(env_file) in prepared.stdout
    assert "prism.example.com" in prepared.stdout
    assert auth_hash not in prepared.stdout
    assert auth_hash not in prepared.stderr

    for invalid_hash in (auth_hash, f"'{auth_hash}", f"{auth_hash}'"):
        invalid_env_file = tmp_path / f"invalid-{len(invalid_hash)}.env"
        invalid_env_file.write_text(
            "\n".join(
                (
                    "PUBLIC_DOMAIN=prism.example.com",
                    "CADDY_ACME_EMAIL=ops@example.com",
                    "CADDY_BASIC_AUTH_USER=reviewer",
                    f"CADDY_BASIC_AUTH_HASH={invalid_hash}",
                    "",
                )
            )
        )
        invalid_env_file.chmod(0o600)
        rejected = subprocess.run(
            ["bash", str(prepare_script), "--env-file", str(invalid_env_file)],
            text=True,
            capture_output=True,
        )
        assert rejected.returncode != 0
        assert invalid_hash not in rejected.stdout
        assert invalid_hash not in rejected.stderr

    docker_marker = tmp_path / "docker-was-called"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(f"#!/usr/bin/env bash\ntouch {docker_marker}\n")
    fake_docker.chmod(0o755)
    refused_reset = subprocess.run(
        [
            "bash",
            str(reset_script),
            "--env-file",
            str(env_file),
            "--confirm-reset",
            "RESET_PRISM_PUBLIC_DEMO_DATA_EXTRA",
        ],
        text=True,
        capture_output=True,
        env={"PATH": f"{tmp_path}:{os.environ['PATH']}"},
    )
    assert refused_reset.returncode != 0
    assert "RESET_PRISM_PUBLIC_DEMO_DATA" in refused_reset.stderr
    assert not docker_marker.exists()


def test_public_demo_reset_removes_stopped_operator_before_literal_volume(
    tmp_path: Path,
) -> None:
    """Reset unblocks the named volume only after removing its stopped app container."""
    reset_script = PRISM_ROOT / "scripts" / "reset-public-demo-data.sh"
    env_file = tmp_path / "prism-public.env"
    docker_log = tmp_path / "docker.log"
    fake_docker = tmp_path / "docker"
    write_public_demo_env(env_file)
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"${FAKE_DOCKER_LOG:?}\"\n"
    )
    fake_docker.chmod(0o755)

    reset = subprocess.run(
        [
            "bash",
            str(reset_script),
            "--env-file",
            str(env_file),
            "--confirm-reset",
            "RESET_PRISM_PUBLIC_DEMO_DATA",
        ],
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "FAKE_DOCKER_LOG": str(docker_log),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
    )

    assert reset.returncode == 0, reset.stderr
    compose_file = PRISM_ROOT / "scripts" / ".." / "docker-compose.public.yml"
    assert docker_log.read_text().splitlines() == [
        f"compose --env-file {env_file} -f {compose_file} stop operator-app",
        f"compose --env-file {env_file} -f {compose_file} rm -f operator-app",
        "volume rm prism-public-data",
        f"compose --env-file {env_file} -f {compose_file} up -d --no-build --wait",
    ]


def test_prepare_script_distinguishes_gnu_and_bsd_stat_mode_detection() -> None:
    """Linux hosts use GNU stat, while local macOS remains a supported test host."""
    prepare_text = (PRISM_ROOT / "scripts" / "prepare-public-demo.sh").read_text()

    assert "stat --version" in prepare_text
    assert "stat -c '%a'" in prepare_text
    assert "stat -f '%Lp'" in prepare_text
    assert prepare_text.index("stat --version") < prepare_text.index("stat -c '%a'")


def test_hosted_portfolio_runbook_documents_safe_public_operations() -> None:
    """Runbook must keep credentials host-only and make recovery auditable."""
    readme = (PRISM_ROOT / "README.md").read_text()

    assert "## Hosted portfolio deployment" in readme
    assert "sudo install -o root -g root -m 600" in readme
    assert "host-only" in readme.lower()
    assert "sudo bash prism/scripts/prepare-public-demo.sh --env-file" in readme
    assert "sudo docker compose --env-file" in readme
    assert "config --quiet" in readme
    assert "sudo docker volume inspect prism-public-data" in readme
    assert "curl -I https://" in readme
    assert "curl -u" in readme
    assert "sudo bash prism/scripts/reset-public-demo-data.sh" in readme
    assert "--confirm-reset RESET_PRISM_PUBLIC_DEMO_DATA" in readme
    assert "CADDY_BASIC_AUTH_HASH='$2b$...'" in readme
    assert "PRISM_PUBLIC_OPERATOR_IMAGE=registry.example/prism-operator@sha256:" in readme
    assert "PRISM_PUBLIC_CADDY_IMAGE=registry.example/prism-caddy@sha256:" in readme
    assert "sudo docker compose --env-file /etc/prism-public.env -f prism/docker-compose.public.yml pull" in readme
    assert "up -d --no-build --wait" in readme
    assert "prism-public-operator:local" in readme
    assert "{{.Id}}" in readme
    assert "not a registry digest" in readme

    for line in readme.splitlines():
        if "docker compose" in line and " config" in line:
            assert "config --quiet" in line


def test_public_env_example_documents_image_overrides_without_secrets() -> None:
    """Release image inputs are discoverable without publishing a digest or hash."""
    example = (PRISM_ROOT / ".env.public.example").read_text()

    assert "# PRISM_PUBLIC_OPERATOR_IMAGE=" in example
    assert "# PRISM_PUBLIC_CADDY_IMAGE=" in example
    assert "@sha256:" not in example
    assert "CADDY_BASIC_AUTH_HASH='$2b$...'" in example


def test_compose_accepts_quoted_bcrypt_without_interpolation_warning(tmp_path: Path) -> None:
    """A single-quoted dotenv bcrypt value must reach Compose literally."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is unavailable")

    compose_version = subprocess.run(
        [docker, "compose", "version"], text=True, capture_output=True
    )
    if compose_version.returncode != 0:
        pytest.skip("Docker Compose is unavailable")

    env_file = tmp_path / "prism-public.env"
    auth_hash = VALID_BCRYPT_HASH
    write_public_demo_env(env_file)

    configured = subprocess.run(
        [
            docker,
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(PRISM_ROOT / "docker-compose.public.yml"),
            "config",
            "--quiet",
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
    )
    assert configured.returncode == 0, configured.stderr
    assert auth_hash not in configured.stdout
    assert auth_hash not in configured.stderr
    assert "variable is not set" not in configured.stderr.lower()
