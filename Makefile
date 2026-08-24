PYTHON ?= python3.11
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

.PHONY: setup lint test infra-check verify

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements-dev.lock

lint:
	$(VENV_PYTHON) -m ruff check src tests --select E9,F63,F7,F82

test:
	AIRFLOW_HOME=/tmp/robot-data-pipeline-airflow PYTHONHASHSEED=2026 \
		$(VENV_PYTHON) -m pytest -q --ignore=tests/etl -m "not slow"

infra-check:
	terraform fmt -check -recursive terraform
	terraform -chdir=terraform init -backend=false -input=false
	terraform -chdir=terraform validate
	terraform -chdir=terraform/validation init -backend=false -input=false
	terraform -chdir=terraform/validation validate

verify: lint test infra-check
