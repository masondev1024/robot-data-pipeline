#!/usr/bin/env python3
"""
Harness Phase Executor.
Phase를 순차적으로 실행하고, 상태를 관리하고, 결과를 기록한다.

Usage: python3 scripts/execute.py <task-name>
Example: python3 scripts/execute.py mvp
"""

import itertools
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
PHASES_DIR = ROOT / "phases"
SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
COMMIT_TEMPLATE = "feat({task}): phase {num} — {name}"

KST = timezone(timedelta(hours=9))


def now_iso() -> str:
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S%z")


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Phase discovery
# ---------------------------------------------------------------------------

def discover_phases(task_dir: Path) -> list[dict]:
    """phases/{task}/phase{N}.md 파일들을 찾아서 순서대로 반환.
    각 phase의 상태는 phases/{task}/phase{N}.status.json에 저장."""
    phases = []
    for f in sorted(task_dir.glob("phase*.md")):
        name = f.stem  # "phase0", "phase1", ...
        num_str = name.replace("phase", "")
        if not num_str.isdigit():
            continue
        num = int(num_str)

        status_file = task_dir / f"phase{num}.status.json"
        if status_file.exists():
            status_data = load_json(status_file)
        else:
            status_data = {"phase": num, "status": "pending"}
            save_json(status_file, status_data)

        phases.append({
            "phase": num,
            "name": extract_phase_name(f),
            "status_file": status_file,
            "prompt_file": f,
            **status_data,
        })

    return sorted(phases, key=lambda p: p["phase"])


def extract_phase_name(phase_file: Path) -> str:
    """phase 파일의 첫 줄에서 이름 추출. 예: '# Phase 0: 프로젝트 세팅' → '프로젝트-세팅'"""
    try:
        first_line = phase_file.read_text().split("\n")[0]
        if ":" in first_line:
            name = first_line.split(":", 1)[1].strip()
            return name.lower().replace(" ", "-")
        return phase_file.stem
    except Exception:
        return phase_file.stem


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True
    )


def git_ensure_branch(task_name: str):
    branch = f"feat-{task_name}"
    current = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    if current == branch:
        return

    r = git("rev-parse", "--verify", branch)
    if r.returncode == 0:
        git("checkout", branch)
    else:
        git("checkout", "-b", branch)

    print(f"  Branch: {branch}")


def git_commit(task_name: str, phase_num: int, phase_name: str):
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode != 0:
        msg = COMMIT_TEMPLATE.format(task=task_name, num=phase_num, name=phase_name)
        git("commit", "-m", msg)
        print(f"  Commit: {msg}")


# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------

class Spinner:
    def __init__(self, message: str):
        self._message = message
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._start = 0.0

    def _spin(self):
        for ch in itertools.cycle(SPINNER_CHARS):
            if self._stop.is_set():
                break
            elapsed = int(time.monotonic() - self._start)
            sys.stderr.write(f"\r{ch} {self._message} [{elapsed}s]")
            sys.stderr.flush()
            self._stop.wait(0.1)
        sys.stderr.write("\r" + " " * 80 + "\r")
        sys.stderr.flush()

    def __enter__(self):
        self._start = time.monotonic()
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start


# ---------------------------------------------------------------------------
# Phase execution
# ---------------------------------------------------------------------------

def build_preamble(project: str, task_name: str) -> str:
    return f"""{project} 프로젝트의 아래 phase를 수행하라.

## 코드 작성 전

- /CLAUDE.md와 /docs/ 하위 문서를 읽고 프로젝트 맥락을 파악하라.
- 이전 phase의 코드를 확인하고 일관성을 유지하라.

## 작업 완료 후

- phase에 명시된 AC(Acceptance Criteria) 커맨드를 실행하라.
- /phases/{task_name}/phase{{N}}.status.json을 업데이트하라:
  - AC 통과 → {{"phase": N, "status": "completed"}}
  - 3회 수정 시도 후에도 실패 → {{"phase": N, "status": "error", "error_message": "..."}}
  - 사람의 개입이 필요한 경우 → {{"phase": N, "status": "blocked", "blocked_reason": "..."}} 기록 후 즉시 중단
- 변경사항을 커밋하라: feat({task_name}): phase N — phase-name

## 제약

- 이 phase에 명시된 작업만 수행하라. 추가 기능이나 파일을 만들지 마라.
- 기존 테스트를 깨뜨리지 마라.

---

"""


def run_phase(phase: dict, preamble: str) -> dict:
    phase_num = phase["phase"]
    phase_name = phase["name"]
    prompt_file = phase["prompt_file"]

    prompt = preamble + prompt_file.read_text()
    output_file = prompt_file.parent / f"phase{phase_num}.output.json"

    result = subprocess.run(
        ["claude", "-p", "--dangerously-skip-permissions", "--output-format", "json", prompt],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=1800,
    )

    output = {
        "phase": phase_num,
        "name": phase_name,
        "exitCode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }

    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return output


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/execute.py <task-name>")
        print("Example: python3 scripts/execute.py mvp")
        sys.exit(1)

    task_name = sys.argv[1]
    task_dir = PHASES_DIR / task_name
    if not task_dir.is_dir():
        print(f"ERROR: {task_dir} not found")
        sys.exit(1)

    phases = discover_phases(task_dir)
    if not phases:
        print(f"ERROR: No phase files found in {task_dir}")
        sys.exit(1)

    total = len(phases)
    pending = [p for p in phases if p["status"] == "pending"]

    print(f"\n{'='*50}")
    print(f"  Harness Executor")
    print(f"  Task: {task_name} | Phases: {total} | Pending: {len(pending)}")
    print(f"{'='*50}")

    # Check for error/blocked
    for p in phases:
        if p["status"] == "error":
            print(f"\n  ✗ Phase {p['phase']} ({p['name']}) failed.")
            print(f"  Error: {p.get('error_message', 'unknown')}")
            print(f"  Fix and reset status to 'pending' in {p['status_file']} to retry.")
            sys.exit(1)
        if p["status"] == "blocked":
            print(f"\n  ⏸ Phase {p['phase']} ({p['name']}) blocked.")
            print(f"  Reason: {p.get('blocked_reason', 'unknown')}")
            sys.exit(2)

    # Git branch
    git_ensure_branch(task_name)

    # Preamble
    project = "FeedbackPulse"
    preamble = build_preamble(project, task_name)

    # Phase loop
    while True:
        phases = discover_phases(task_dir)
        current = next((p for p in phases if p["status"] == "pending"), None)

        if current is None:
            print("\n  All phases completed!")
            break

        phase_num = current["phase"]
        phase_name = current["name"]
        done = sum(1 for p in phases if p["status"] == "completed")

        # Record start time
        status_data = load_json(current["status_file"])
        if "started_at" not in status_data:
            status_data["started_at"] = now_iso()
            save_json(current["status_file"], status_data)

        # Run
        with Spinner(f"Phase {phase_num}/{total - 1} ({done} done): {phase_name}") as sp:
            run_phase(current, preamble)
            elapsed = int(sp.elapsed)

        # Re-read status
        status_data = load_json(current["status_file"])
        status = status_data.get("status", "pending")
        ts = now_iso()

        if status == "completed":
            status_data["completed_at"] = ts
            save_json(current["status_file"], status_data)
            git_commit(task_name, phase_num, phase_name)
            print(f"  ✓ Phase {phase_num}: {phase_name} [{elapsed}s]")

        elif status == "error":
            status_data["failed_at"] = ts
            save_json(current["status_file"], status_data)
            git_commit(task_name, phase_num, phase_name)
            print(f"  ✗ Phase {phase_num}: {phase_name} failed [{elapsed}s]")
            print(f"    Error: {status_data.get('error_message', 'unknown')}")
            sys.exit(1)

        elif status == "blocked":
            status_data["blocked_at"] = ts
            save_json(current["status_file"], status_data)
            print(f"  ⏸ Phase {phase_num}: {phase_name} blocked [{elapsed}s]")
            print(f"    Reason: {status_data.get('blocked_reason', 'unknown')}")
            sys.exit(2)

        else:  # still pending
            status_data["status"] = "error"
            status_data["error_message"] = "Phase did not update status"
            status_data["failed_at"] = ts
            save_json(current["status_file"], status_data)
            print(f"  ✗ Phase {phase_num}: status not updated [{elapsed}s]")
            sys.exit(1)

    print(f"\n{'='*50}")
    print(f"  Task '{task_name}' completed!")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
