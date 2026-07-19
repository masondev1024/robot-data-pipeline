#!/usr/bin/env bash
set -uo pipefail

expected="${EXPECTED_AWS_ACCOUNT_ID:-}"
if [[ ! "$expected" =~ ^[0-9]{12}$ ]]; then
  echo "EXPECTED_AWS_ACCOUNT_ID must be a 12-digit account ID" >&2
  exit 2
fi

if ! actual=$(aws sts get-caller-identity --query Account --output text 2>/dev/null); then
  echo "unable to verify AWS STS identity; refusing AWS changes" >&2
  exit 4
fi

if [ "$actual" != "$expected" ]; then
  echo "AWS account mismatch; refusing AWS changes" >&2
  exit 3
fi

echo "AWS account verified: $actual"
