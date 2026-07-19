"""Repository-level contract for the recruiter-facing quality gate."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_supported_python_version_is_explicit():
    assert (ROOT / ".python-version").read_text().strip() == "3.11"


def test_makefile_exposes_reproducible_entrypoints():
    makefile = (ROOT / "Makefile").read_text()
    for target in ("setup:", "lint:", "test:", "infra-check:", "verify:"):
        assert target in makefile
    assert "install -r requirements-dev.lock" in makefile


def test_quality_workflow_gates_python_and_infrastructure():
    workflow_path = ROOT / ".github" / "workflows" / "quality.yml"
    workflow = yaml.safe_load(workflow_path.read_text())
    jobs = workflow["jobs"]

    assert {"python-quality", "terraform-quality"} <= jobs.keys()

    python_steps = "\n".join(
        str(step.get("run", "")) for step in jobs["python-quality"]["steps"]
    )
    terraform_steps = "\n".join(
        str(step.get("run", "")) for step in jobs["terraform-quality"]["steps"]
    )

    assert "ruff check" in python_steps
    assert "pytest" in python_steps
    assert "pip install -r requirements-dev.lock" in python_steps
    assert "terraform fmt -check" in terraform_steps
    assert "terraform validate" in terraform_steps


def test_dev_dependencies_are_public_and_versioned():
    requirements = (ROOT / "requirements-dev.txt").read_text()
    assert "pytest" in requirements
    assert "ruff" in requirements
    assert "PyYAML" in requirements
    assert "httpx2" in requirements
    assert "matplotlib" in requirements

    lock = (ROOT / "requirements-dev.lock").read_text()
    assert "ruff==0.12.7" in lock
    assert "pytest==" in lock
    assert "httpx2==" in lock
