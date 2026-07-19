from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
RETIRED_ACCOUNT_ID = "827913617635"
RETIRED_BUCKET = "de-ai-06-smartfactory-bucket"


def _deployment_files() -> list[Path]:
    files = [
        *sorted((ROOT / "k8s").rglob("*.yaml")),
        *sorted((ROOT / "helm").glob("*.yaml")),
        *sorted((ROOT / ".github/workflows").glob("*.yml")),
        ROOT / "docker/airflow/Dockerfile",
        ROOT / "src/ml/redeploy.py",
    ]
    return [path for path in files if path.is_file()]


def _runtime_configuration_files() -> list[Path]:
    return [
        *sorted((ROOT / "sql").glob("*.sql")),
        *sorted((ROOT / "dags").glob("*.py")),
        *sorted((ROOT / "src").rglob("*.py")),
        ROOT / "scripts/diagnose_grafana.sh",
    ]


def test_deployment_sources_do_not_reference_retired_account():
    offenders = [
        path.relative_to(ROOT)
        for path in _deployment_files()
        if RETIRED_ACCOUNT_ID in path.read_text()
    ]
    assert offenders == []


def test_deployment_sources_do_not_reference_retired_bucket():
    offenders = [
        path.relative_to(ROOT)
        for path in _deployment_files()
        if RETIRED_BUCKET in path.read_text()
    ]
    assert offenders == []


def test_runtime_configuration_does_not_fall_back_to_retired_bucket():
    offenders = [
        path.relative_to(ROOT)
        for path in _runtime_configuration_files()
        if RETIRED_BUCKET in path.read_text()
    ]
    assert offenders == []


def test_workload_templates_do_not_use_latest_image_tag():
    image_latest = re.compile(r"^\s*image:\s*\S+:latest\s*$", re.MULTILINE)
    offenders = [
        path.relative_to(ROOT)
        for path in _deployment_files()
        if image_latest.search(path.read_text())
    ]
    assert offenders == []


def test_public_environment_example_contains_no_static_aws_credentials():
    example = (ROOT / ".env.example").read_text()
    assert "AWS_ACCESS_KEY_ID" not in example
    assert "AWS_SECRET_ACCESS_KEY" not in example
    assert "AWS_SESSION_TOKEN" not in example
    assert "AWS_PROFILE=robot-platform" in example


def test_prism_environment_example_defaults_to_offline_without_static_keys():
    example = (ROOT / "prism/.env.example").read_text()
    assert "BEDROCK_OFFLINE=true" in example
    assert "AWS_ACCESS_KEY_ID" not in example
    assert "AWS_SECRET_ACCESS_KEY" not in example


def test_k8s_deploy_guards_account_and_uses_rendered_manifests():
    workflow = (ROOT / ".github/workflows/k8s-deploy.yml").read_text()
    assert "vars.AWS_ACCOUNT_ID" in workflow
    assert "scripts/require_aws_account.sh" in workflow
    assert "scripts/render_deployment.py" in workflow
    assert "kubectl apply -f /tmp/robot-deploy/k8s --recursive" in workflow
    assert "kubectl apply -f k8s/" not in workflow
    assert "IMAGE_TAG: ${{ github.sha }}" in workflow
    assert "docker push $ECR_REGISTRY/robot-telemetry-generator:latest" not in workflow
    assert "docker push $ECR_REGISTRY/robot-telemetry-api:latest" not in workflow


def test_post_deploy_uses_rendered_dashboard_template():
    workflow = (ROOT / ".github/workflows/post-deploy.yml").read_text()
    assert "vars.AWS_ACCOUNT_ID" in workflow
    assert "scripts/require_aws_account.sh" in workflow
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in workflow
    assert "scripts/render_deployment.py" in workflow
    assert "/tmp/robot-deploy/k8s/monitoring/grafana-dashboards.yaml" in workflow
    assert "k8s/monitoring/grafana-dashboards.yaml" not in workflow.replace(
        "/tmp/robot-deploy/k8s/monitoring/grafana-dashboards.yaml", ""
    )


def test_workflows_take_non_secret_coordinates_from_repository_variables():
    workflows = [
        ROOT / ".github/workflows/k8s-deploy.yml",
        ROOT / ".github/workflows/post-deploy.yml",
        ROOT / ".github/workflows/phase8-e2e-verify.yml",
        ROOT / ".github/workflows/eval.yml",
    ]
    for path in workflows:
        source = path.read_text()
        assert "vars.AWS_REGION" in source, path.name

    deployment = (ROOT / ".github/workflows/k8s-deploy.yml").read_text()
    assert "vars.EKS_CLUSTER_NAME" in deployment
    assert "vars.S3_BUCKET_NAME" in deployment


def test_phase8_fails_early_when_bucket_coordinate_is_missing():
    workflow = (ROOT / ".github/workflows/phase8-e2e-verify.yml").read_text()
    assert "S3_BUCKET_NAME repository variable is required" in workflow


def test_terraform_workflow_cannot_apply_without_remote_state_bootstrap():
    workflow = (ROOT / ".github/workflows/terraform.yml").read_text()
    assert "terraform apply" not in workflow
    assert "TF_VAR_slack_webhook_url" not in workflow
    assert "workflow_dispatch" not in workflow


def test_quality_workflow_runs_an_explicit_render_smoke_test():
    workflow = (ROOT / ".github/workflows/quality.yml").read_text()
    assert "Render account-neutral deployment templates" in workflow
    assert "scripts/render_deployment.py" in workflow


def test_adot_setup_uses_rendered_manifests_without_mutating_sources():
    script = (ROOT / "scripts/setup_adot.sh").read_text()
    assert "scripts/require_aws_account.sh" in script
    assert "scripts/render_deployment.py" in script
    assert '"$RENDER_ROOT/k8s/monitoring/adot/collector.yaml"' in script
    assert '"$RENDER_ROOT/k8s/monitoring/adot/instrumentation.yaml"' in script
    assert "sed -i" not in script
    assert "TF_VAR_slack_webhook_url" not in script


def test_terraform_requires_a_portable_bucket_input():
    variables = (ROOT / "terraform/variables.tf").read_text()
    assert RETIRED_BUCKET not in variables
    assert 'variable "s3_bucket_name"' in variables
    bucket_block = variables.split('variable "s3_bucket_name"', 1)[1].split("}", 1)[0]
    assert "default" not in bucket_block
    assert "validation" in bucket_block


def test_terraform_publishes_non_secret_account_portability_example():
    example = ROOT / "terraform/example.tfvars"
    assert example.is_file()
    source = example.read_text()
    assert "s3_bucket_name" in source
    assert RETIRED_ACCOUNT_ID not in source
    assert RETIRED_BUCKET not in source
    assert "AWS_ACCESS_KEY_ID" not in source
    assert "AWS_SECRET_ACCESS_KEY" not in source
