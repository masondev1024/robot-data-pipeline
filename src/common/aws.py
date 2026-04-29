"""AWS region constant + region-aware boto3 client factory.

Replaces scattered `boto3.client(svc, region_name="eu-west-1")` calls so the
region lives in one place. Clients are not cached — boto3 internally caches
credentials per Session, so per-call client creation is ms-level. Avoiding
caching keeps test mocks (which patch `boto3.client`) isolated between tests.
"""
import os

import boto3

AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "eu-west-1"))


def get_client(service: str):
    return boto3.client(service, region_name=AWS_REGION)
