"""Verify direct CloudFront, Cloudflare Worker, HLS and controlled failover."""

from __future__ import annotations

import argparse
import json
import math
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch(url: str) -> tuple[int, dict[str, str], bytes, float]:
    started = time.perf_counter()
    try:
        with urlopen(
            Request(
                url,
                headers={
                    "Accept": "application/vnd.apple.mpegurl,*/*",
                    # Cloudflare's managed bot protection rejects Python-urllib/3.x;
                    # emulate the browser class of HLS clients used in the lab.
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                },
            ),
            timeout=20,
        ) as response:
            body = response.read()
            return response.status, dict(response.headers.items()), body, (time.perf_counter() - started) * 1000
    except HTTPError as error:
        body = error.read()
        return error.code, dict(error.headers.items()), body, (time.perf_counter() - started) * 1000
    except URLError as error:
        raise RuntimeError(f"request failed for {url}: {error.reason}") from error


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
    return ordered[index]


def assert_playlist(url: str, expected_origin: str | None = None) -> dict[str, object]:
    status, headers, body, latency = fetch(url)
    text = body.decode("utf-8", errors="replace")
    if status != 200 or "#EXTM3U" not in text:
        raise AssertionError(f"playlist check failed: {url} status={status}")
    if expected_origin and headers.get("X-Media-Lab-Origin") != expected_origin:
        raise AssertionError(
            f"origin header mismatch: expected={expected_origin} actual={headers.get('X-Media-Lab-Origin')}"
        )
    segment = next((line.strip() for line in text.splitlines() if line.strip().endswith(".ts")), None)
    if not segment:
        raise AssertionError(f"playlist has no segment: {url}")
    segment_url = f"{url.rsplit('/', 1)[0]}/{segment}"
    segment_status, segment_headers, segment_body, segment_latency = fetch(segment_url)
    if segment_status != 200 or not segment_body:
        raise AssertionError(f"segment check failed: {segment_url} status={segment_status}")
    return {
        "playlist_url": url,
        "playlist_status": status,
        "playlist_bytes": len(body),
        "playlist_content_type": headers.get("Content-Type"),
        "playlist_latency_ms": round(latency, 2),
        "segment_url": segment_url,
        "segment_status": segment_status,
        "segment_bytes": len(segment_body),
        "segment_content_type": segment_headers.get("Content-Type"),
        "segment_latency_ms": round(segment_latency, 2),
        "origin": headers.get("X-Media-Lab-Origin"),
        "fallback": headers.get("X-Media-Lab-Fallback"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary-url", required=True)
    parser.add_argument("--secondary-url", required=True)
    parser.add_argument("--worker-url", required=True)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("repeat must be at least 1")

    bases = {
        "cloudfront-primary": args.primary_url.rstrip("/"),
        "cloudfront-secondary": args.secondary_url.rstrip("/"),
        "cloudflare-primary": f"{args.worker_url.rstrip('/')}/media/index.m3u8",
        "cloudflare-fallback": f"{args.worker_url.rstrip('/')}/media/index.m3u8?force_primary_failure=1",
    }
    evidence: dict[str, object] = {"routes": {}, "checks": []}

    direct_primary = assert_playlist(f"{bases['cloudfront-primary']}/media/index.m3u8")
    direct_secondary = assert_playlist(f"{bases['cloudfront-secondary']}/media/index.m3u8")
    worker_primary = assert_playlist(bases["cloudflare-primary"], "cloudfront-primary")
    worker_fallback = assert_playlist(bases["cloudflare-fallback"], "cloudfront-secondary")
    evidence["checks"] = [direct_primary, direct_secondary, worker_primary, worker_fallback]

    for name, url in bases.items():
        latencies = []
        origins = set()
        for _ in range(args.repeat):
            status, headers, body, latency = fetch(url)
            if status != 200 or not body:
                raise AssertionError(f"route check failed: {name} status={status}")
            latencies.append(latency)
            if headers.get("X-Media-Lab-Origin"):
                origins.add(headers["X-Media-Lab-Origin"])
        evidence["routes"][name] = {
            "requests": len(latencies),
            "successes": len(latencies),
            "p95_latency_ms": round(p95(latencies), 2),
            "origins": sorted(origins),
        }

    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
