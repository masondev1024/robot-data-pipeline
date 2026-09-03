"""Upload the generated HLS VOD to both private S3 origins."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import boto3


CONTENT_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
}


def upload_directory(profile: str, region: str, bucket: str, directory: Path, prefix: str) -> list[dict[str, object]]:
    client = boto3.Session(profile_name=profile, region_name=region).client("s3")
    evidence: list[dict[str, object]] = []
    for path in sorted(directory.iterdir()):
        if path.suffix not in CONTENT_TYPES:
            continue
        key = f"{prefix.strip('/')}/{path.name}"
        cache_control = (
            "public,max-age=2,s-maxage=2"
            if path.suffix == ".m3u8"
            else "public,max-age=86400,immutable"
        )
        client.upload_file(
            str(path),
            bucket,
            key,
            ExtraArgs={
                "ContentType": CONTENT_TYPES[path.suffix],
                "CacheControl": cache_control,
            },
        )
        head = client.head_object(Bucket=bucket, Key=key)
        evidence.append(
            {
                "bucket": bucket,
                "region": region,
                "key": key,
                "bytes": head["ContentLength"],
                "etag": head["ETag"].strip('"'),
                "content_type": head.get("ContentType"),
            }
        )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="develope-test")
    parser.add_argument("--primary-region", default="eu-west-1")
    parser.add_argument("--secondary-region", default="us-east-1")
    parser.add_argument("--primary-bucket", required=True)
    parser.add_argument("--secondary-bucket", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--prefix", default="media")
    args = parser.parse_args()

    if not (args.directory / "index.m3u8").exists():
        parser.error("directory must contain index.m3u8; run generate_hls_asset.py first")

    evidence = [
        *upload_directory(args.profile, args.primary_region, args.primary_bucket, args.directory, args.prefix),
        *upload_directory(args.profile, args.secondary_region, args.secondary_bucket, args.directory, args.prefix),
    ]
    print(json.dumps({"objects": evidence}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
