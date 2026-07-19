from pathlib import Path

import pytest

from scripts.render_deployment import DeploymentConfig, render_tree


VALID_VALUES = {
    "AWS_ACCOUNT_ID": "123456789012",
    "AWS_REGION": "eu-west-1",
    "EKS_CLUSTER_NAME": "robot-telemetry-cluster",
    "S3_BUCKET_NAME": "robot-platform-example",
    "IMAGE_TAG": "0123456789abcdef0123456789abcdef01234567",
}


def _config(**overrides: str) -> DeploymentConfig:
    return DeploymentConfig.from_mapping(VALID_VALUES | overrides)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AWS_ACCOUNT_ID", "1234"),
        ("AWS_REGION", "EU_WEST_1"),
        ("EKS_CLUSTER_NAME", "INVALID_CLUSTER"),
        ("S3_BUCKET_NAME", "Invalid_Bucket"),
        ("S3_BUCKET_NAME", "robot..bucket"),
        ("S3_BUCKET_NAME", "192.168.0.1"),
        ("S3_BUCKET_NAME", "xn--robot-bucket"),
        ("S3_BUCKET_NAME", "robot-bucket-s3alias"),
        ("IMAGE_TAG", "latest"),
        ("IMAGE_TAG", "short-sha"),
    ],
)
def test_rejects_invalid_deployment_values(key: str, value: str):
    with pytest.raises(ValueError, match=key):
        _config(**{key: value})


def test_rejects_missing_required_value():
    values = VALID_VALUES.copy()
    values.pop("S3_BUCKET_NAME")

    with pytest.raises(ValueError, match="S3_BUCKET_NAME"):
        DeploymentConfig.from_mapping(values)


def test_renders_supported_placeholders_without_mutating_source(tmp_path: Path):
    source = tmp_path / "templates"
    source.mkdir()
    template = source / "deployment.yaml"
    template.write_text(
        "\n".join(
            [
                "account: __AWS_ACCOUNT_ID__",
                "region: __AWS_REGION__",
                "cluster: __EKS_CLUSTER_NAME__",
                "bucket: __S3_BUCKET_NAME__",
                "image: __AWS_ACCOUNT_ID__.dkr.ecr.__AWS_REGION__.amazonaws.com/api:__IMAGE_TAG__",
            ]
        )
        + "\n"
    )
    before = template.read_text()

    rendered = render_tree(source, tmp_path / "rendered", _config())

    output = tmp_path / "rendered/deployment.yaml"
    assert rendered == [output]
    assert output.read_text() == (
        "account: 123456789012\n"
        "region: eu-west-1\n"
        "cluster: robot-telemetry-cluster\n"
        "bucket: robot-platform-example\n"
        "image: 123456789012.dkr.ecr.eu-west-1.amazonaws.com/api:"
        "0123456789abcdef0123456789abcdef01234567\n"
    )
    assert template.read_text() == before


def test_rejects_unknown_placeholder(tmp_path: Path):
    source = tmp_path / "templates"
    source.mkdir()
    (source / "deployment.yaml").write_text("value: __UNKNOWN_VALUE__\n")

    with pytest.raises(ValueError, match="UNKNOWN_VALUE"):
        render_tree(source, tmp_path / "rendered", _config())


def test_preserves_known_post_deploy_placeholder(tmp_path: Path):
    source = tmp_path / "templates"
    source.mkdir()
    (source / "dashboard.yaml").write_text(
        "load_balancer: __API_ALB_ARN_SUFFIX__\nregion: __AWS_REGION__\n"
    )

    render_tree(source, tmp_path / "rendered", _config())

    assert (tmp_path / "rendered/dashboard.yaml").read_text() == (
        "load_balancer: __API_ALB_ARN_SUFFIX__\nregion: eu-west-1\n"
    )


def test_rejects_output_inside_source_tree(tmp_path: Path):
    source = tmp_path / "templates"
    source.mkdir()

    with pytest.raises(ValueError, match="output"):
        render_tree(source, source / "rendered", _config())


def test_rejects_nonempty_output_to_prevent_stale_manifest_apply(tmp_path: Path):
    source = tmp_path / "templates"
    source.mkdir()
    (source / "deployment.yaml").write_text("region: __AWS_REGION__\n")
    output = tmp_path / "rendered"
    output.mkdir()
    (output / "removed-resource.yaml").write_text("kind: Deployment\n")

    with pytest.raises(ValueError, match="empty"):
        render_tree(source, output, _config())


def test_only_renders_supported_deployment_files(tmp_path: Path):
    source = tmp_path / "templates"
    source.mkdir()
    (source / "deployment.yaml").write_text("region: __AWS_REGION__\n")
    (source / "notes.txt").write_text("__AWS_REGION__\n")

    rendered = render_tree(source, tmp_path / "rendered", _config())

    assert rendered == [tmp_path / "rendered/deployment.yaml"]
    assert not (tmp_path / "rendered/notes.txt").exists()


def test_renders_sql_templates(tmp_path: Path):
    source = tmp_path / "templates"
    source.mkdir()
    (source / "bronze.sql").write_text(
        "LOCATION 's3://__S3_BUCKET_NAME__/bronze/'\n"
    )

    rendered = render_tree(source, tmp_path / "rendered", _config())

    assert rendered == [tmp_path / "rendered/bronze.sql"]
    assert (tmp_path / "rendered/bronze.sql").read_text() == (
        "LOCATION 's3://robot-platform-example/bronze/'\n"
    )
