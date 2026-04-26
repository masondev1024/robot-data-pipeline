# Step 2: flink-validation (이상 탐지 단위 테스트)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ADR.md` (ADR-009 — Z-Score / 다변량 알고리즘 명세)
- `/docs/research.md` §4 (threshold 의미, 가드 동작)
- `/flink/anomaly_detection.py` (step 1 산출물 — `compute_zscore`, `compute_load_ratio`, `is_anomaly` 순수 함수)
- `/tests/conftest.py` (sys.path 패턴 참조)

## 작업

`tests/flink/test_anomaly_detection.py`를 작성하라. step 1에서 분리한 순수 함수 3개를 단위 테스트한다.

### 테스트 케이스 명세

#### `compute_zscore(temp, mean, stddev, sigma_floor)` — 5케이스
1. **정상 동작**: `compute_zscore(95, 80, 5, 0.5) == 3.0`
2. **음의 편차 절댓값**: `compute_zscore(65, 80, 5, 0.5) == 3.0`
3. **σ floor 가드 (stddev=0)**: `compute_zscore(81, 80, 0, 0.5) == 2.0` (분모 0.5로 대체)
4. **σ floor 가드 (stddev<floor)**: `compute_zscore(82, 80, 0.1, 0.5) == 4.0`
5. **stddev > floor**: `compute_zscore(95, 80, 10, 0.5) == 1.5`

#### `compute_load_ratio(temp, current_load)` — 4케이스
1. **정상 동작**: `compute_load_ratio(90, 50) == 1.8`
2. **load=0 가드**: `compute_load_ratio(90, 0) == 90.0` (분모 1로 대체)
3. **load=1**: `compute_load_ratio(90, 1) == 90.0`
4. **고부하 정상**: `compute_load_ratio(90, 100) == 0.9`

#### `is_anomaly(...)` — 8케이스
**고정 threshold 인자**: `zscore_thr=3.0, sigma_floor=0.5, load_thr=1.8, min_temp=85.0`

| # | 입력 (temp, mean, stddev, current_load) | 기대 | 발화 조건 |
|---|---|---|---|
| 1 | 95, 80, 5, 100 | `True` | Cond1 (zscore=3.0, 정확히 임계 초과 아니므로 zscore_thr=3.0이면 `> 3.0` False — **수정**: temp=96 으로 zscore=3.2 → True) |
| 2 | 90, 80, 5, 50 | `True` | Cond2 (temp≥85, 90/50=1.8, 그러나 `> 1.8` False — **수정**: load=49 → 1.836 → True) |
| 3 | 80, 80, 5, 100 | `False` | Cond1 zscore=0, Cond2 temp<85 |
| 4 | 84, 80, 5, 40 | `False` | Cond1 zscore=0.8, Cond2 temp<85 |
| 5 | 100, 80, 5, 50 | `True` | 둘 다 발화 (zscore=4.0, 100/50=2.0) |
| 6 | 81, 80, 0, 100 | `False` | σ=0 가드 → zscore=2.0, Cond2 temp<85 |
| 7 | 90, 80, 0, 100 | `True` | σ=0 가드 → zscore=20, Cond1 발화 |
| 8 | 86, 80, 5, 0 | `True` | Cond1 zscore=1.2 (False), Cond2 temp≥85 + 86/1=86 > 1.8 (True) |

> **주의**: 위 표의 #1, #2 boundary를 `>` 비교 동작에 맞게 직접 검증하고 코드를 작성할 때 정확한 입력값을 선택하라. 부동소수점 비교는 `pytest.approx` 사용.

### 추가 케이스 — Threshold 변동
- `is_anomaly(temp=84, ..., min_temp=80.0, ...)` 시 Cond2 활성화되도록 boundary가 dynamic threshold에 정확히 반응하는지 확인 (운영 튜닝 시나리오 검증).

### 파일 구조
```python
# tests/flink/test_anomaly_detection.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "flink"))

import pytest
from anomaly_detection import compute_zscore, compute_load_ratio, is_anomaly

DEFAULT_THRESHOLDS = dict(zscore_thr=3.0, sigma_floor=0.5, load_thr=1.8, min_temp=85.0)

class TestComputeZscore:
    ...

class TestComputeLoadRatio:
    ...

class TestIsAnomaly:
    ...

class TestThresholdTuning:
    """ADR-009 threshold 외부화 — 임계값 변경 시 boundary가 정확히 반응하는지"""
    ...
```

추가로 `tests/flink/__init__.py` (빈 파일)도 작성한다.

## Acceptance Criteria

```bash
# 단위 테스트 통과
pytest tests/flink/test_anomaly_detection.py -v

# 구체 카운트 — 5+4+8+1 = 18건 이상
pytest tests/flink/test_anomaly_detection.py --collect-only -q | grep -E "^[0-9]+ tests" | awk '{print $1}' | head -1
# 위 결과가 18 이상이어야 함

# 명시 케이스 모두 PASSED 확인
pytest tests/flink/test_anomaly_detection.py -v 2>&1 | grep -c "PASSED"
# 위 결과가 18 이상이어야 함
```

## 검증 절차

1. 위 AC 커맨드를 모두 실행, 18건 이상 PASSED 확인.
2. 아키텍처 체크리스트:
   - σ floor (sigma_floor) 가드 케이스가 최소 2건 이상 포함되는가?
   - current_load=0 가드 케이스가 포함되는가?
   - 두 조건 동시 발화/단독 발화/모두 미발화 시나리오가 모두 커버되는가?
   - threshold tuning 케이스로 ADR-009의 외부화 결정이 검증되는가?
3. `phases/3-realtime/index.json` step 2 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "tests/flink/test_anomaly_detection.py: Z-Score/load_ratio/is_anomaly 18케이스(σ guard, load guard, threshold tuning) 전부 PASSED"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- LocalStack / Moto 등으로 실제 KDS/S3를 mock 하지 마라. 이유: 본 step은 **순수 함수 단위 테스트**. 통합 테스트는 운영 인프라 배포 후 별도 (plan.md Task 3.3 통합 검증 항목).
- PyFlink TableEnvironment를 import 하지 마라. 이유: 단위 테스트 환경에 Java JVM 미설치 가정. import 오류로 전체 collection 실패 위험. 순수 함수만 import.
- `compute_zscore`, `compute_load_ratio`, `is_anomaly` 외 함수를 새로 정의하지 마라. 이유: 테스트는 step 1 산출물 검증용. 알고리즘 추가는 `flink/anomaly_detection.py` 수정 작업.
- threshold를 테스트 안에서 hardcoding 하지 마라. 이유: `DEFAULT_THRESHOLDS` 딕셔너리로 한 곳에서 관리해야 ADR-009 외부화 의도가 테스트에도 반영됨.
