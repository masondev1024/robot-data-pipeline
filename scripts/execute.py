#!/usr/bin/env python3
"""
Harness Step Executor — phase 내 step을 순차/병렬 실행하고 자가 교정한다.

개선사항:
1. Context Isolation  : Librarian 서브세션으로 컨텍스트 격리
2. Parallel Execution : depends_on 기반 DAG — 독립 step 동시 실행
3. Role-based Routing : domain별 가이드라인 선택적 로드
4. Socratic Pre-flight: 실행 전 아키텍처 가정 소크라테스식 검증 (--preflight)
5. Auto-Healing       : MAX_RETRIES 소진 후 git reset --hard 자동 정리
6. Future/Promise     : Librarian Future 선행 스케줄 → Worker 블로킹 보장

Usage:
    python3 scripts/execute.py <phase-dir> [--push] [--preflight] [--preflight-yes]
"""

import argparse
import concurrent.futures
import contextlib
import json
import subprocess
import sys
import threading
import time
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Librarian — Context Isolation (#1 + #3 + #6)
# ---------------------------------------------------------------------------

class Librarian:
    """
    별도 Claude 서브세션에서 domain 관련 가이드라인만 요약한다.

    Future/Promise 패턴 (#6):
        raw     = librarian.load_raw()
        future  = executor.submit(librarian.summarize, raw)   # 비동기 시작
        # ... 다른 setup 작업 병렬 수행 ...
        guardrails = future.result()                           # 필요 시 블로킹
    """

    TIMEOUT = 120  # 요약 서브세션 최대 대기 시간(초)

    # domain → 로드할 doc 파일명 목록 (빈 리스트 = 전부 로드) (#3)
    DOMAIN_DOCS: dict[str, list[str]] = {
        "terraform": ["ARCHITECTURE.md", "ADR.md"],
        "python":    ["ARCHITECTURE.md", "ADR.md", "research.md"],
        "sql":       ["ARCHITECTURE.md", "ADR.md"],
        "airflow":   ["ARCHITECTURE.md", "ADR.md"],
        "flink":     ["ARCHITECTURE.md", "ADR.md", "research.md"],
        "k8s":       ["ARCHITECTURE.md", "ADR.md"],
        "mixed":     ["ARCHITECTURE.md", "ADR.md", "research.md"],
        "default":   [],  # 빈 리스트 = 전체 로드
    }

    def __init__(self, domain: str, root: Path):
        self._domain = domain
        self._root = root

    def load_raw(self) -> str:
        """CLAUDE.md + domain 필터 docs/*.md 를 원문 그대로 합쳐 반환한다."""
        sections: list[str] = []

        claude_md = self._root / "CLAUDE.md"
        if claude_md.exists():
            sections.append(f"## 프로젝트 규칙 (CLAUDE.md)\n\n{claude_md.read_text()}")

        docs_dir = self._root / "docs"
        if docs_dir.is_dir():
            allowed = self.DOMAIN_DOCS.get(self._domain, [])
            for doc in sorted(docs_dir.glob("*.md")):
                if not allowed or doc.name in allowed:
                    sections.append(f"## {doc.stem}\n\n{doc.read_text()}")

        return "\n\n---\n\n".join(sections) if sections else ""

    def summarize(self, raw: str) -> str:
        """
        Claude 서브세션을 호출하여 domain 관련 핵심 제약만 추출·요약한다.
        서브세션 실패 시 raw 원본을 그대로 반환(fallback).
        """
        if not raw:
            return ""

        prompt = (
            f"당신은 컨텍스트 요약 전문가입니다.\n\n"
            f"아래 프로젝트 가이드라인에서 '{self._domain}' 작업에 직접 관련된 "
            f"핵심 제약·아키텍처 결정·금지사항만 추출하여 간결하게 요약하세요. "
            f"'{self._domain}'과 무관한 도메인 규칙이나 UI 가이드는 완전히 제외하세요.\n\n"
            f"---\n\n{raw}"
        )

        result = subprocess.run(
            ["claude", "-p", "--output-format", "text", prompt],
            capture_output=True, text=True, timeout=self.TIMEOUT,
        )

        if result.returncode == 0 and result.stdout.strip():
            return (
                f"## 핵심 가이드라인 (Librarian 요약, domain={self._domain})\n\n"
                f"{result.stdout.strip()}"
            )

        return raw  # fallback: 원본 전체 사용


# ---------------------------------------------------------------------------
# Progress indicator
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def progress_indicator(label: str):
    """터미널 진행 표시기. with 문으로 사용하며 .elapsed 로 경과 시간을 읽는다."""
    frames = "◐◓◑◒"
    stop = threading.Event()
    t0 = time.monotonic()

    def _animate():
        idx = 0
        while not stop.wait(0.12):
            sec = int(time.monotonic() - t0)
            sys.stderr.write(f"\r{frames[idx % len(frames)]} {label} [{sec}s]")
            sys.stderr.flush()
            idx += 1
        sys.stderr.write("\r" + " " * (len(label) + 20) + "\r")
        sys.stderr.flush()

    th = threading.Thread(target=_animate, daemon=True)
    th.start()
    info = types.SimpleNamespace(elapsed=0.0)
    try:
        yield info
    finally:
        stop.set()
        th.join()
        info.elapsed = time.monotonic() - t0


# ---------------------------------------------------------------------------
# StepExecutor
# ---------------------------------------------------------------------------

class StepExecutor:
    """Phase 디렉토리 안의 step들을 DAG 기반으로 병렬/순차 실행하는 하네스."""

    MAX_RETRIES = 3
    FEAT_MSG  = "feat({phase}): step {num} — {name}"
    CHORE_MSG = "chore({phase}): step {num} output"
    TZ = timezone(timedelta(hours=9))
    SHADOW_DIR = ".harness_shadow"

    # Named gate lookup — phases/index.json 의 `pre_gate_check` 가 이 키 중 하나면
    # 아래 리스트의 파일들이 모두 존재하는지로 검증된다.
    # 새 phase 는 named gate 추가 대신 phases/index.json 에
    # `"gate_files": ["relative/path", ...]` 를 직접 선언하는 것을 권장한다.
    _NAMED_GATES: dict[str, list[str]] = {
        "check_env":              [".env.example"],
        "check_infra_base":       ["terraform/variables.tf"],
        "verify_ingestion_flow":  [
            "src/generator/app.py",
            "terraform/modules/data_pipeline/glue.tf",
        ],
        "verify_batch_output":    ["dags/robot_daily_etl.py"],
        "check_serving_deps":     ["src/api/main.py"],
        "verify_serving_layer":   ["src/api/main.py"],
    }

    def __init__(self, phase_dir_name: str, *,
                 auto_push: bool = False, preflight: bool = False,
                 preflight_yes: bool = False, simulate: bool = False):
        self._root            = str(ROOT)
        self._phases_dir      = ROOT / "phases"
        self._phase_dir       = self._phases_dir / phase_dir_name
        self._phase_dir_name  = phase_dir_name
        self._top_index_file  = self._phases_dir / "index.json"
        self._auto_push       = auto_push
        self._preflight       = preflight
        self._preflight_yes   = preflight_yes
        self._simulate        = simulate
        self._shadow_root     = ROOT / self.SHADOW_DIR
        self._commit_lock     = threading.Lock()
        self._simulation_logs = []

        if not self._phase_dir.is_dir():
            print(f"ERROR: {self._phase_dir} not found")
            sys.exit(1)

        self._index_file = self._phase_dir / "index.json"
        if not self._index_file.exists():
            print(f"ERROR: {self._index_file} not found")
            sys.exit(1)

        idx = self._read_json(self._index_file)
        self._project    = idx.get("project", "project")
        self._phase_name = idx.get("phase", phase_dir_name)
        self._domain     = idx.get("domain", "default")
        self._total      = len(idx["steps"])

        if self._simulate:
            self._shadow_root.mkdir(exist_ok=True)
            print(f"  Mode: SIMULATION (Shadow: {self.SHADOW_DIR})")

    # ------------------------------------------------------------------
    # Timestamps & JSON I/O
    # ------------------------------------------------------------------

    def _stamp(self) -> str:
        return datetime.now(self.TZ).strftime("%Y-%m-%dT%H:%M:%S%z")

    @staticmethod
    def _read_json(p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(p: Path, data: dict):
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # Git
    # ------------------------------------------------------------------

    def _run_git(self, *args) -> subprocess.CompletedProcess:
        cmd = ["git"] + list(args)
        return subprocess.run(cmd, cwd=self._root, capture_output=True, text=True)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        self._print_header()
        
        # [CRITICAL] Plan Approval Gate
        if not self._check_plan_approval():
            print(f"\n  ✗ ERROR: '/plan.md'의 상태가 [APPROVED]가 아닙니다.")
            print(f"    작업을 시작하려면 먼저 '/plan.md'를 검토하고 상태를 [APPROVED]로 변경하십시오.")
            sys.exit(1)

        self._generate_dag_graph()
        
        # Phase Gate Check
        if not self._run_phase_gate():
            print(f"  ✗ Phase Gate Check 실패. 실행을 중단합니다.")
            sys.exit(1)

        if not self._simulate:
            self._checkout_branch()

        # ── Librarian Future 선행 스케줄링 (#6) ──────────────────────────
        librarian   = Librarian(domain=self._domain, root=ROOT)
        raw         = librarian.load_raw()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            librarian_future = pool.submit(librarian.summarize, raw)
            self._ensure_created_at()

            if self._preflight:
                if not self._run_preflight(raw):
                    sys.exit(0)

            sys.stderr.write("  Librarian: 컨텍스트 요약 중... ")
            sys.stderr.flush()
            guardrails = librarian_future.result()
            sys.stderr.write("완료\n")
            sys.stderr.flush()

        self._execute_all_steps(guardrails)
        
        if self._simulate:
            self._generate_simulation_report()
        else:
            self._finalize()

    # ------------------------------------------------------------------
    # Plan Approval Gate
    # ------------------------------------------------------------------

    def _check_plan_approval(self) -> bool:
        """plan.md 파일의 상태가 APPROVED인지 확인한다."""
        plan_path = Path(self._root) / "plan.md"
        if not plan_path.exists():
            return False
        
        content = plan_path.read_text(encoding="utf-8")
        # 대소문자 구분 없이 [APPROVED] 또는 `APPROVED` 패턴 확인
        import re
        if re.search(r"\[APPROVED\]|`APPROVED`", content, re.IGNORECASE):
            return True
        return False

    # ------------------------------------------------------------------
    # Phase Gate — Smart Gate Logic
    # ------------------------------------------------------------------

    def _run_phase_gate(self) -> bool:
        """이전 Phase의 물리적/논리적 완결성을 검증한다.

        검증 대상 파일 목록은 두 가지 경로로 결정된다 (선언적 우선).
            1) phases/index.json의 해당 phase entry에 `gate_files: [...]` 가 있으면 그 목록.
            2) `pre_gate_check: "<named>"` 가 있으면 `_NAMED_GATES` 표에서 lookup.
        둘 다 없으면 gate 없음 → 통과.
        """
        phase_entry = {}
        for p in self._read_json(self._top_index_file).get("phases", []):
            if p["dir"] == self._phase_dir_name:
                phase_entry = p
                break

        gate_files: list[str] = phase_entry.get("gate_files", []) or []
        gate_cmd:   str       = phase_entry.get("pre_gate_check", "") or ""

        if not gate_files and gate_cmd:
            if gate_cmd in self._NAMED_GATES:
                gate_files = self._NAMED_GATES[gate_cmd]
            else:
                print(f"  Gate: '{gate_cmd}' 알 수 없는 named gate — 통과 처리")
                return True

        if not gate_files:
            return True

        label = gate_cmd or "gate_files"
        print(f"  Gate: '{label}' 검증 중... ({len(gate_files)}개 파일)")

        if self._simulate:
            return self._verify_logical_connection(gate_cmd)

        root = Path(self._root)
        missing = [f for f in gate_files if not (root / f).exists()]
        if missing:
            for f in missing:
                print(f"    [FAIL] 누락: {f}")
            return False
        return True

    def _verify_logical_connection(self, gate_cmd: str) -> bool:
        """시뮬레이션 모드에서 코드 간의 논리적 연결성을 정적으로 검증한다."""
        import re
        
        # 1단계: 환경 설정 검증
        if gate_cmd == "check_env":
            return (Path(self._root) / ".env.example").exists()

        # 2단계: Phase 0 -> Phase 1 연결성 (VPC, 리전 등)
        if gate_cmd == "check_infra_base":
            vars_path = self._shadow_root / "terraform/variables.tf"
            if not vars_path.exists():
                print(f"    [FAIL] '{vars_path.name}' 파일이 Shadow 디렉토리에 없습니다.")
                return False

            content = vars_path.read_text()
            # 핵심 변수 정의 확인
            checks = {
                "vpc_cidr": r'default\s*=\s*"10\.0\.32\.0/16"',
                "aws_region": r'default\s*=\s*"eu-west-1"',
                "cluster_name": r'default\s*=\s*"robot-telemetry-cluster"'
            }
            for name, pattern in checks.items():
                if not re.search(pattern, content):
                    print(f"    [FAIL] {name} 설정이 확정값과 일치하지 않습니다.")
                    return False
            return True
        
        # 3단계: Phase 1 -> Phase 2 연결성 (KDS 이름, 스키마 일치 여부)
        if gate_cmd == "verify_ingestion_flow":
            gen_path = self._shadow_root / "src/generator/app.py"
            glue_path = self._shadow_root / "terraform/modules/data_pipeline/glue.tf"
            if not (gen_path.exists() and glue_path.exists()):
                return False
            
            # TODO: 실제 스키마 필드 대조 로직 (추후 확장)
            return True

        return True

    # ------------------------------------------------------------------
    # DAG Visualization — Mermaid.js
    # ------------------------------------------------------------------

    def _generate_dag_graph(self):
        """현재 Phase의 Step 의존성을 Mermaid.js 그래프로 시각화한다."""
        index = self._read_json(self._index_file)
        lines = ["graph TD"]
        
        # 스타일 정의
        lines.append("  classDef completed fill:#4CAF50,stroke:#fff,color:#fff;")
        lines.append("  classDef pending fill:#f9f9f9,stroke:#333;")
        lines.append("  classDef error fill:#f44336,stroke:#fff,color:#fff;")
        lines.append("  classDef blocked fill:#FF9800,stroke:#fff,color:#fff;")

        for s in index["steps"]:
            sid = f"S{s['step']}"
            label = f"\"{s['step']}. {s['name']}\""
            lines.append(f"  {sid}[{label}]")
            
            # 상태별 클래스 적용
            status = s.get("status", "pending")
            lines.append(f"  class {sid} {status};")
            
            # 의존성 연결
            for dep in s.get("depends_on", []):
                lines.append(f"  S{dep} --> {sid}")
        
        graph_content = "\n".join(lines)
        dag_path = self._phase_dir / "DAG.md"
        
        with open(dag_path, "w", encoding="utf-8") as f:
            f.write(f"# Phase DAG: {self._phase_name}\n\n```mermaid\n{graph_content}\n```\n")
        
        # ROOT 대신 self._root를 사용하여 테스트 경로 문제 해결
        try:
            rel_dag = dag_path.relative_to(self._root)
        except ValueError:
            rel_dag = dag_path.name
        print(f"  DAG: {rel_dag} 업데이트 완료")

    # ------------------------------------------------------------------
    # Simulation Report
    # ------------------------------------------------------------------

    def _generate_simulation_report(self):
        """시뮬레이션 결과를 모아 리포트를 생성한다."""
        report_path = Path(self._root) / "SIMULATION_REPORT.md"
        now = self._stamp()
        
        content = [
            f"# Simulation Report: {self._phase_name}",
            f"- 생성 시각: {now}",
            f"- 결과: SUCCESS (Arch-Validation Passed)",
            "\n## 1. Librarian Summary",
            self._simulation_logs[0] if self._simulation_logs else "N/A",
            "\n## 2. Pre-flight Questions",
            self._simulation_logs[1] if len(self._simulation_logs) > 1 else "N/A",
            "\n## 3. Shadow Artifacts",
            f"모든 코드가 `{self.SHADOW_DIR}/` 하위에 논리적으로 생성되었습니다.",
            "\n---",
            "이 리포트를 검토하고 실제 실행을 위해 `--simulate` 옵션 없이 명령어를 입력하십시오."
        ]
        
        report_path.write_text("\n".join(content), encoding="utf-8")
        print(f"\n  ✓ Simulation Report 생성 완료: {report_path.name}")

    # ------------------------------------------------------------------
    # Pre-flight — Socratic (#4)
    # ------------------------------------------------------------------

    def _run_preflight(self, raw_guardrails: str) -> bool:
        """소크라테스식 사전 검증 — 실행 전 아키텍처 가정을 역질문한다."""
        print("\n  Pre-flight: 아키텍처 가정 검증 중...")

        step_contents = [
            f.read_text()
            for f in sorted(self._phase_dir.glob("step*.md"))
        ]
        steps_text = "\n\n---\n\n".join(step_contents)

        prompt = (
            f"{raw_guardrails}\n\n"
            "위 프로젝트 규칙과 아래 실행 예정 Step들을 검토하고, "
            "실행 전 반드시 확인이 필요한 모호한 가정이나 잠재적 아키텍처 결함을 "
            "3가지 이내로 질문 형태로 제시하라. 각 질문은 번호를 붙여 한 줄로 작성하라.\n\n"
            "--- 실행 예정 Steps ---\n\n" + steps_text
        )

        result = subprocess.run(
            ["claude", "-p", "--output-format", "text", prompt],
            capture_output=True, text=True, timeout=120,
        )

        if result.returncode != 0 or not result.stdout.strip():
            print("  Pre-flight: 서브세션 실패. 건너뜁니다.")
            return True

        self._simulation_logs.append(result.stdout.strip())

        print("\n  ┌─ Pre-flight 질문 (확인 후 Enter로 계속) ────────────")
        for line in result.stdout.strip().splitlines():
            print(f"  │ {line}")
        print("  └──────────────────────────────────────────────────\n")

        if self._simulate:
            print("  Simulation 모드이므로 자동으로 Enter를 처리합니다.")
            return True

        if self._preflight_yes:
            print("  --preflight-yes: 비인터랙티브 모드 — 자동 통과.")
            return True

        try:
            answer = input("  계속하려면 Enter, 중단하려면 q: ").strip()
        except EOFError:
            # stdin 닫힘(non-TTY 환경): 안전하게 통과 처리
            print("  stdin 닫힘 — 자동 통과.")
            return True

        if answer.lower() == "q":
            print("  Pre-flight: 실행 중단.")
            return False
        return True

    # ------------------------------------------------------------------
    # Guardrails & context
    # ------------------------------------------------------------------

    def _load_guardrails(self) -> str:
        """하위 호환 메서드 — 테스트 및 레거시 호출용. load_raw() 위임."""
        domain    = getattr(self, "_domain", "default")
        librarian = Librarian(domain=domain, root=ROOT)
        return librarian.load_raw()

    @staticmethod
    def _build_step_context(index: dict) -> str:
        lines = [
            f"- Step {s['step']} ({s['name']}): {s['summary']}"
            for s in index["steps"]
            if s["status"] == "completed" and s.get("summary")
        ]
        if not lines:
            return ""
        return "## 이전 Step 산출물\n\n" + "\n".join(lines) + "\n\n"

    def _build_preamble(self, guardrails: str, step_context: str,
                        prev_error: Optional[str] = None) -> str:
        commit_example = self.FEAT_MSG.format(
            phase=self._phase_name, num="N", name="<step-name>")
        retry_section = ""
        if prev_error:
            retry_section = (
                f"\n## ⚠ 이전 시도 실패 — 아래 에러를 반드시 참고하여 수정하라\n\n"
                f"{prev_error}\n\n---\n\n"
            )
        
        sim_instr = ""
        if self._simulate:
            sim_instr = (
                f"### [SIMULATION MODE] ###\n"
                f"1. 당신은 현재 시뮬레이션 모드에서 작업 중입니다.\n"
                f"2. 모든 파일 생성 및 수정은 실제 경로가 아닌 `{self.SHADOW_DIR}/` 하위의 동일한 경로에 수행하세요.\n"
                f"   예: `terraform/main.tf` 생성 요청 시 -> `{self.SHADOW_DIR}/terraform/main.tf`에 작성.\n"
                f"3. 실제 AWS 리소스를 생성하거나 외부 API를 호출하지 마세요. 코드로만 구현하세요.\n"
                f"4. `index.json` 상태 업데이트는 실제 경로 `/phases/{self._phase_dir_name}/index.json`에 수행하세요.\n\n"
            )

        return (
            f"당신은 {self._project} 프로젝트의 개발자입니다. 아래 step을 수행하세요.\n\n"
            f"{sim_instr}"
            f"{guardrails}\n\n---\n\n"
            f"{step_context}{retry_section}"
            f"## 작업 규칙\n\n"
            f"1. 이전 step에서 작성된 코드를 확인하고 일관성을 유지하라.\n"
            f"2. 이 step에 명시된 작업만 수행하라. 추가 기능이나 파일을 만들지 마라.\n"
            f"3. 기존 테스트를 깨뜨리지 마라.\n"
            f"4. AC(Acceptance Criteria) 검증을 직접 실행하라.\n"
            f"5. /phases/{self._phase_dir_name}/index.json의 해당 step status를 업데이트하라:\n"
            f"   - AC 통과 → \"completed\" + \"summary\" 필드에 이 step의 산출물을 한 줄로 요약\n"
            f"   - {self.MAX_RETRIES}회 수정 시도 후에도 실패 → \"error\" + \"error_message\" 기록\n"
            f"   - 사용자 개입이 필요한 경우 (API 키, 인증, 수동 설정 등) → \"blocked\" + \"blocked_reason\" 기록 후 즉시 중단\n"
            f"6. 모든 변경사항을 커밋하라:\n"
            f"   {commit_example}\n\n---\n\n"
        )

    # ------------------------------------------------------------------
    # Claude invocation
    # ------------------------------------------------------------------

    def _invoke_claude(self, step: dict, preamble: str) -> dict:
        step_num, step_name = step["step"], step["name"]
        step_file = self._phase_dir / f"step{step_num}.md"

        if not step_file.exists():
            print(f"  ERROR: {step_file} not found")
            sys.exit(1)

        prompt = preamble + step_file.read_text()
        
        # Simulation 모드일 때 추가 로그
        if self._simulate:
            print(f"  Simulation: Step {step_num} 실행 중 (Shadow Write)...")

        result = subprocess.run(
            ["claude", "-p", "--dangerously-skip-permissions",
             "--output-format", "json", prompt],
            cwd=self._root, capture_output=True, text=True, timeout=1800,
        )

        if result.returncode != 0:
            print(f"\n  WARN: Claude가 비정상 종료됨 (code {result.returncode})")
            if result.stderr:
                print(f"  stderr: {result.stderr[:500]}")

        output = {
            "step":     step_num,
            "name":     step_name,
            "exitCode": result.returncode,
            "stdout":   result.stdout,
            "stderr":   result.stderr,
        }
        out_path = self._phase_dir / f"step{step_num}-output.json"
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        return output

    # ------------------------------------------------------------------
    # Header & validation
    # ------------------------------------------------------------------

    def _print_header(self):
        print(f"\n{'='*60}")
        print(f"  Harness Step Executor (Architecture Guardian)")
        print(f"  Phase: {self._phase_name} | Domain: {self._domain} | Steps: {self._total}")
        if self._simulate:
            print(f"  Mode: SIMULATION (Shadow-Active)")
        if self._auto_push:
            print(f"  Auto-push: enabled")
        if self._preflight:
            print(f"  Pre-flight: enabled")
        print(f"{'='*60}")

    def _check_blockers(self):
        index = self._read_json(self._index_file)
        for s in reversed(index["steps"]):
            if s["status"] == "error":
                print(f"\n  ✗ Step {s['step']} ({s['name']}) failed.")
                print(f"  Error: {s.get('error_message', 'unknown')}")
                print(f"  Fix and reset status to 'pending' to retry.")
                sys.exit(1)
            if s["status"] == "blocked":
                print(f"\n  ⏸ Step {s['step']} ({s['name']}) blocked.")
                print(f"  Reason: {s.get('blocked_reason', 'unknown')}")
                print(f"  Resolve and reset status to 'pending' to retry.")
                sys.exit(2)
            if s["status"] != "pending":
                break

    def _ensure_created_at(self):
        index = self._read_json(self._index_file)
        if "created_at" not in index:
            index["created_at"] = self._stamp()
            self._write_json(self._index_file, index)

    # ------------------------------------------------------------------
    # Top-level index
    # ------------------------------------------------------------------

    def _update_top_index(self, status: str):
        if not self._top_index_file.exists():
            return
        top = self._read_json(self._top_index_file)
        ts = self._stamp()
        for phase in top.get("phases", []):
            if phase.get("dir") == self._phase_dir_name:
                phase["status"] = status
                ts_key = {
                    "completed": "completed_at",
                    "error":     "failed_at",
                    "blocked":   "blocked_at",
                }.get(status)
                if ts_key:
                    phase[ts_key] = ts
                break
        self._write_json(self._top_index_file, top)

    # ------------------------------------------------------------------
    # Git & Commits
    # ------------------------------------------------------------------

    def _checkout_branch(self):
        branch = f"feat-{self._phase_name}"

        r = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        if r.returncode != 0:
            print(f"  ERROR: git을 사용할 수 없거나 git repo가 아닙니다.")
            print(f"  {r.stderr.strip()}")
            sys.exit(1)

        if r.stdout.strip() == branch:
            return

        r = self._run_git("rev-parse", "--verify", branch)
        r = (self._run_git("checkout", branch)
             if r.returncode == 0
             else self._run_git("checkout", "-b", branch))

        if r.returncode != 0:
            print(f"  ERROR: 브랜치 '{branch}' checkout 실패.")
            print(f"  {r.stderr.strip()}")
            print(f"  Hint: 변경사항을 stash하거나 commit한 후 다시 시도하세요.")
            sys.exit(1)

        print(f"  Branch: {branch}")

    def _commit_step(self, step_num: int, step_name: str,
                     lock: Optional[threading.Lock] = None):
        """thread-safe 2단계 커밋. lock 미제공 시 self._commit_lock 사용."""
        actual_lock = lock if lock is not None else self._commit_lock
        with actual_lock:
            output_rel = f"phases/{self._phase_dir_name}/step{step_num}-output.json"
            index_rel  = f"phases/{self._phase_dir_name}/index.json"

            self._run_git("add", "-A")
            self._run_git("reset", "HEAD", "--", output_rel)
            self._run_git("reset", "HEAD", "--", index_rel)

            if self._run_git("diff", "--cached", "--quiet").returncode != 0:
                msg = self.FEAT_MSG.format(
                    phase=self._phase_name, num=step_num, name=step_name)
                r = self._run_git("commit", "-m", msg)
                if r.returncode == 0:
                    print(f"  Commit: {msg}")
                else:
                    print(f"  WARN: 코드 커밋 실패: {r.stderr.strip()}")

            self._run_git("add", "-A")
            if self._run_git("diff", "--cached", "--quiet").returncode != 0:
                msg = self.CHORE_MSG.format(phase=self._phase_name, num=step_num)
                r = self._run_git("commit", "-m", msg)
                if r.returncode != 0:
                    print(f"  WARN: housekeeping 커밋 실패: {r.stderr.strip()}")

    def _auto_reset(self):
        """Auto-Healing (#5): 최종 실패 시 부분 변경을 git reset --hard로 정리한다."""
        print("  Auto-Healing: git reset --hard HEAD (부분 변경 정리)...")
        r = self._run_git("reset", "--hard", "HEAD")
        if r.returncode == 0:
            print("  ✓ 작업 디렉토리 정리 완료.")
        else:
            print(f"  WARN: reset 실패: {r.stderr.strip()}")

    # ------------------------------------------------------------------
    # DAG helpers (#2)
    # ------------------------------------------------------------------

    def _get_runnable_steps(self, index: dict) -> list[dict]:
        """
        depends_on 기반 DAG에서 현재 실행 가능한 pending step 목록을 반환한다.
        depends_on 필드가 없으면 빈 배열로 간주(즉시 실행 가능).
        """
        completed_ids = {
            s["step"] for s in index["steps"] if s["status"] == "completed"
        }
        return [
            s for s in index["steps"]
            if s["status"] == "pending"
            and all(d in completed_ids for d in s.get("depends_on", []))
        ]

    def _mark_started(self, step_num: int):
        index = self._read_json(self._index_file)
        for s in index["steps"]:
            if s["step"] == step_num and "started_at" not in s:
                s["started_at"] = self._stamp()
                self._write_json(self._index_file, index)
                break

    # ------------------------------------------------------------------
    # Execution loop — DAG-based (#2)
    # ------------------------------------------------------------------

    def _execute_all_steps(self, guardrails: str):
        """
        DAG 기반 실행 루프.
        depends_on이 모두 completed인 step들을 ThreadPoolExecutor로 동시 실행한다.
        """
        while True:
            # 매 루프 시작 시 DAG 그래프 업데이트
            self._generate_dag_graph()
            
            index    = self._read_json(self._index_file)
            runnable = self._get_runnable_steps(index)

            if not runnable:
                pending = [s for s in index["steps"] if s["status"] == "pending"]
                if not pending:
                    print("\n  All steps completed!")
                    return
                # 교착 상태: pending이 있으나 실행 가능한 step이 없음
                print("\n  ERROR: 실행 가능한 step이 없지만 pending이 남아 있습니다.")
                print("  depends_on 설정을 확인하세요.")
                sys.exit(1)

            for s in runnable:
                self._mark_started(s["step"])

            if len(runnable) == 1:
                result = self._execute_single_step(runnable[0], guardrails)
            else:
                names = [s["name"] for s in runnable]
                print(f"\n  ⚡ Parallel: {len(runnable)} steps 동시 실행 → {names}")
                result = self._execute_parallel(runnable, guardrails)

            if result == "error":
                sys.exit(1)
            if result == "blocked":
                sys.exit(2)

    def _execute_parallel(self, steps: list[dict], guardrails: str) -> str:
        """여러 step을 ThreadPoolExecutor로 동시 실행한다. 최악 상태를 반환."""
        results: list[str] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(steps)) as executor:
            future_to_step = {
                executor.submit(
                    self._execute_single_step, s, guardrails, self._commit_lock
                ): s
                for s in steps
            }
            for future in concurrent.futures.as_completed(future_to_step):
                step = future_to_step[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    print(f"  ERROR: Step {step['step']} 스레드 예외: {exc}")
                    results.append("error")

        if "error"   in results: return "error"
        if "blocked" in results: return "blocked"
        return "completed"

    def _execute_single_step(self, step: dict, guardrails: str,
                             lock: Optional[threading.Lock] = None) -> str:
        """
        단일 step 실행 (재시도 포함).
        반환값: "completed" | "error" | "blocked"

        Auto-Healing (#5): MAX_RETRIES 소진 후 git reset --hard 자동 실행.
        """
        if lock is None:
            lock = self._commit_lock

        step_num, step_name = step["step"], step["name"]
        done      = sum(1 for s in self._read_json(self._index_file)["steps"]
                        if s["status"] == "completed")
        prev_error: Optional[str] = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            index        = self._read_json(self._index_file)
            step_context = self._build_step_context(index)
            preamble     = self._build_preamble(guardrails, step_context, prev_error)

            tag = f"Step {step_num}/{self._total - 1} ({done} done): {step_name}"
            if attempt > 1:
                tag += f" [retry {attempt}/{self.MAX_RETRIES}]"

            with progress_indicator(tag) as pi:
                self._invoke_claude(step, preamble)
                elapsed = int(pi.elapsed)

            index  = self._read_json(self._index_file)
            status = next(
                (s.get("status", "pending") for s in index["steps"]
                 if s["step"] == step_num),
                "pending",
            )
            ts = self._stamp()

            if status == "completed":
                for s in index["steps"]:
                    if s["step"] == step_num:
                        s["completed_at"] = ts
                self._write_json(self._index_file, index)
                
                # Simulation 모드일 경우 Git Commit 건너뜀
                if not self._simulate:
                    self._commit_step(step_num, step_name, lock)
                
                print(f"  ✓ Step {step_num}: {step_name} [{elapsed}s]")
                return "completed"

            if status == "blocked":
                for s in index["steps"]:
                    if s["step"] == step_num:
                        s["blocked_at"] = ts
                self._write_json(self._index_file, index)
                reason = next(
                    (s.get("blocked_reason", "") for s in index["steps"]
                     if s["step"] == step_num),
                    "",
                )
                print(f"  ⏸ Step {step_num}: {step_name} blocked [{elapsed}s]")
                print(f"    Reason: {reason}")
                self._update_top_index("blocked")
                return "blocked"

            err_msg = next(
                (s.get("error_message", "Step did not update status")
                 for s in index["steps"] if s["step"] == step_num),
                "Step did not update status",
            )

            if attempt < self.MAX_RETRIES:
                for s in index["steps"]:
                    if s["step"] == step_num:
                        s["status"] = "pending"
                        s.pop("error_message", None)
                self._write_json(self._index_file, index)
                prev_error = err_msg
                print(f"  ↻ Step {step_num}: retry {attempt}/{self.MAX_RETRIES} — {err_msg}")
            else:
                for s in index["steps"]:
                    if s["step"] == step_num:
                        s["status"]        = "error"
                        s["error_message"] = f"[{self.MAX_RETRIES}회 시도 후 실패] {err_msg}"
                        s["failed_at"]     = ts
                self._write_json(self._index_file, index)
                
                if not self._simulate:
                    self._commit_step(step_num, step_name, lock)
                
                print(f"  ✗ Step {step_num}: {step_name} failed after "
                      f"{self.MAX_RETRIES} attempts [{elapsed}s]")
                print(f"    Error: {err_msg}")

                # Auto-Healing: 부분 변경 정리 후 종료
                if not self._simulate:
                    self._auto_reset()
                self._update_top_index("error")
                return "error"

        return "error"  # unreachable

    # ------------------------------------------------------------------
    # Finalize
    # ------------------------------------------------------------------

    def _finalize(self):
        index = self._read_json(self._index_file)
        index["completed_at"] = self._stamp()
        self._write_json(self._index_file, index)
        self._update_top_index("completed")

        self._run_git("add", "-A")
        if self._run_git("diff", "--cached", "--quiet").returncode != 0:
            msg = f"chore({self._phase_name}): mark phase completed"
            r = self._run_git("commit", "-m", msg)
            if r.returncode == 0:
                print(f"  ✓ {msg}")

        if self._auto_push:
            branch = f"feat-{self._phase_name}"
            r = self._run_git("push", "-u", "origin", branch)
            if r.returncode != 0:
                print(f"\n  ERROR: git push 실패: {r.stderr.strip()}")
                sys.exit(1)
            print(f"  ✓ Pushed to origin/{branch}")

        print(f"\n{'='*60}")
        print(f"  Phase '{self._phase_name}' completed!")
        print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Harness Step Executor")
    parser.add_argument("phase_dir", help="Phase directory name (e.g. 0-setup)")
    parser.add_argument("--push",      action="store_true",
                        help="Push branch after completion")
    parser.add_argument("--preflight", action="store_true",
                        help="Run Socratic pre-flight check before execution")
    parser.add_argument("--preflight-yes", action="store_true",
                        help="Pre-flight 질문은 출력하되 stdin 입력 없이 자동 통과 (CI/agent용)")
    parser.add_argument("--simulate",  action="store_true",
                        help="Run in simulation mode (Shadow writes, No real AWS)")
    args = parser.parse_args()

    # --preflight-yes 는 --preflight 를 암묵 활성화 (편의)
    preflight = args.preflight or args.preflight_yes

    StepExecutor(args.phase_dir,
                 auto_push=args.push,
                 preflight=preflight,
                 preflight_yes=args.preflight_yes,
                 simulate=args.simulate).run()


if __name__ == "__main__":
    main()
