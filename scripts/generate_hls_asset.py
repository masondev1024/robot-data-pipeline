"""Generate a deterministic short VOD HLS asset for the media lab."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=int, default=12)
    parser.add_argument("--segment-seconds", type=int, default=2)
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        parser.error("ffmpeg is required")
    if args.duration < args.segment_seconds * 2:
        parser.error("duration must contain at least two HLS segments")

    args.output.mkdir(parents=True, exist_ok=True)
    for path in args.output.glob("*"):
        if path.is_file():
            path.unlink()

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-t",
        str(args.duration),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-f",
        "hls",
        "-hls_time",
        str(args.segment_seconds),
        "-hls_playlist_type",
        "vod",
        "-hls_segment_filename",
        str(args.output / "segment%03d.ts"),
        str(args.output / "index.m3u8"),
    ]
    subprocess.run(command, check=True)

    playlist = args.output / "index.m3u8"
    segments = sorted(args.output.glob("*.ts"))
    if not playlist.exists() or len(segments) < 2:
        raise RuntimeError("ffmpeg did not produce a playlist and at least two segments")
    print(f"generated playlist={playlist} segments={len(segments)}")
    for path in [playlist, *segments]:
        print(f"{path.name}\t{path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
