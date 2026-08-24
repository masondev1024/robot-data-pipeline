#!/usr/bin/env python3
"""Render account-neutral Kubernetes and Helm templates.

Only non-secret deployment coordinates are accepted. AWS credentials are
resolved by the AWS SDK/CLI credential chain and are never read here.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
from collections.abc import Mapping


_ACCOUNT_ID = re.compile(r"^[0-9]{12}$")
_REGION = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-[0-9]$")
_CLUSTER_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{0,99}$")
_PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_IP_ADDRESS_SHAPED = re.compile(r"^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$")
_IMAGE_TAG = re.compile(r"^[0-9a-f]{40}$")
_PLACEHOLDER = re.compile(r"__([A-Z][A-Z0-9_]*)__")
_DEFERRED_PLACEHOLDERS = {"API_ALB_ARN_SUFFIX"}
_RESERVED_BUCKET_PREFIXES = ("xn--", "sthree-", "amzn-s3-demo-")
_RESERVED_BUCKET_SUFFIXES = (
    "-s3alias",
    "--ol-s3",
    ".mrap",
    "--x-s3",
    "--table-s3",
)


@dataclass(frozen=True)
class DeploymentConfig:
    aws_account_id: str
    aws_region: str
    eks_cluster_name: str
    s3_bucket_name: str
    image_tag: str
    project_name: str

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "DeploymentConfig":
        required = {
            "AWS_ACCOUNT_ID": _ACCOUNT_ID,
            "AWS_REGION": _REGION,
            "EKS_CLUSTER_NAME": _CLUSTER_NAME,
            "S3_BUCKET_NAME": _BUCKET_NAME,
            "IMAGE_TAG": _IMAGE_TAG,
        }
        normalized: dict[str, str] = {}
        for key, pattern in required.items():
            value = values.get(key, "").strip()
            if not value or pattern.fullmatch(value) is None:
                raise ValueError(f"invalid or missing {key}")
            normalized[key] = value

        bucket = normalized["S3_BUCKET_NAME"]
        if (
            ".." in bucket
            or _IP_ADDRESS_SHAPED.fullmatch(bucket)
            or bucket.startswith(_RESERVED_BUCKET_PREFIXES)
            or bucket.endswith(_RESERVED_BUCKET_SUFFIXES)
        ):
            raise ValueError("invalid or missing S3_BUCKET_NAME")

        project_name = values.get("PROJECT_NAME", "robot-telemetry").strip()
        if _PROJECT_NAME.fullmatch(project_name) is None:
            raise ValueError("invalid PROJECT_NAME")

        return cls(
            aws_account_id=normalized["AWS_ACCOUNT_ID"],
            aws_region=normalized["AWS_REGION"],
            eks_cluster_name=normalized["EKS_CLUSTER_NAME"],
            s3_bucket_name=normalized["S3_BUCKET_NAME"],
            image_tag=normalized["IMAGE_TAG"],
            project_name=project_name,
        )

    def replacements(self) -> dict[str, str]:
        return {
            "__AWS_ACCOUNT_ID__": self.aws_account_id,
            "__AWS_REGION__": self.aws_region,
            "__EKS_CLUSTER_NAME__": self.eks_cluster_name,
            "__S3_BUCKET_NAME__": self.s3_bucket_name,
            "__IMAGE_TAG__": self.image_tag,
            "__PROJECT_NAME__": self.project_name,
            "__KDS_STREAM_NAME__": f"{self.project_name}-stream",
            "__FIREHOSE_NAME__": f"{self.project_name}-firehose",
        }


def render_tree(
    source_root: Path, output_root: Path, config: DeploymentConfig
) -> list[Path]:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if output_root == source_root or output_root.is_relative_to(source_root):
        raise ValueError("output directory must be outside the source tree")
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError("output directory must be empty to prevent stale manifests")

    rendered_paths: list[Path] = []
    for source_path in sorted(source_root.rglob("*")):
        if not source_path.is_file() or source_path.suffix not in {
            ".yaml",
            ".yml",
            ".sql",
        }:
            continue

        content = source_path.read_text()
        for placeholder, value in config.replacements().items():
            content = content.replace(placeholder, value)

        unknown = sorted(set(_PLACEHOLDER.findall(content)) - _DEFERRED_PLACEHOLDERS)
        if unknown:
            names = ", ".join(unknown)
            raise ValueError(f"unknown or unresolved placeholder: {names}")

        output_path = output_root / source_path.relative_to(source_root)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)
        rendered_paths.append(output_path)

    return rendered_paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[1]
    output_root = args.output.resolve()
    config = DeploymentConfig.from_mapping(os.environ)

    rendered = []
    rendered.extend(render_tree(repository_root / "k8s", output_root / "k8s", config))
    rendered.extend(render_tree(repository_root / "helm", output_root / "helm", config))
    rendered.extend(render_tree(repository_root / "sql", output_root / "sql", config))
    print(f"rendered {len(rendered)} deployment files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
