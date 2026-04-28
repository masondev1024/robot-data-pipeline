# 왜 SageMaker가 필요한가

> **TL;DR** — Phase 1-4 까지만 만들면 "BI 대시보드 + 알림" 수준에서 멈춘다. SageMaker(Phase 5)가 들어가야 시스템이 **사후 대응**에서 **사전 예방**으로, 즉 **AIOps / Predictive Maintenance** 시스템으로 격상된다.

---

## 1. 현재 시스템의 한계 — 모두 "사후 대응"

| 컴포넌트 | 시점 | 역할 |
|---|---|---|
| Flink real-time | 지금 이 순간 motor_temp 비정상 | "방금 이상해졌어요" — 이미 spike 발생 |
| Bedrock 일일 리포트 | 어제 데이터 LLM 분석 | "어제 이런 로봇이 위험했어요" — 이미 끝난 일 |
| Grafana 대시보드 | 현재/과거 메트릭 | "지금 보이는 상태" — 진단 도구 |

문제는 명백하다. 공장 로봇이 실제로 멈추면 라인 정지 → 시간당 손실. 알람이 와도 그 시점엔 늦었음.

---

## 2. SageMaker가 해결하는 것 — "사전 예방"

```
어제까지 누적된 패턴 → SageMaker 모델 → "내일 ROBOT-00123이 고장 날 확률 0.78"
                                              ↓
                                   정비반장이 미리 출동 → 라인 정지 0건
```

**입력 (gold 테이블 4개 feature):**
- `avg_motor_temp` — 일평균 모터 온도 (누적 가열 패턴)
- `max_motor_temp` — 일최고 모터 온도 (스파이크 빈도)
- `battery_drain` — 일 배터리 소모량 (부하 정도)
- `active_hours` — 일 가동 시간 (사용량)

**출력**: 고장 확률 (0~1)

**라벨 (학습용)**: `CASE WHEN max_motor_temp > 90 THEN 1 ELSE 0` — 룰 기반.
실제 환경에선 정비 이력 데이터(maintenance log)를 라벨로 사용.

---

## 3. 메달리온 아키텍처가 비로소 완성됨

지금까지 만든 흐름:
```
Bronze (raw)   → Silver (정제)   → Gold (집계)   → ???
```

Gold가 그냥 BI 차트용으로 끝나면 메달리온이 미완성. **Gold의 진짜 정체는 "ML feature store"**:

```
Bronze → Silver → Gold (Feature Store) ─┬─→ Grafana (현재 시각화)
                                          ├─→ Bedrock (LLM 일일 요약)
                                          └─→ SageMaker (예측 모델) ★
                                                    ↓
                                              Endpoint
                                                    ↓
                                              API /api/predict
                                                    ↓
                                              Portal 화면에 위험도 표시
```

매일 자정 Airflow DAG가 돌면서 Gold가 갱신되면 → 매주 월요일 SageMaker 재학습(`dags/robot_daily_etl.py:_is_monday` 분기) → 모델이 점점 똑똑해짐. **이게 production data pipeline 의 종착점.**

---

## 4. 데모/포트폴리오 측면에서의 위치

| Phase 1-4 까지만 | Phase 5 SageMaker 포함 |
|---|---|
| "AWS 데이터 파이프라인 빌더" | "AIOps / Predictive Maintenance 시스템" |
| BI 대시보드 + 알림 | + ML 추론 → 의사결정 자동화 |
| 데이터 엔지니어 작업물 | 데이터 엔지니어 + ML Ops 작업물 |

발표 자리에서 "그래서 이게 뭘 하는 거예요?"라는 질문이 왔을 때:
- Phase 1-4 까지: "공장 로봇 데이터 모아서 보여주는 시스템이에요"
- Phase 5 포함: "공장 로봇이 **언제 고장 날지 예측해서 미리 정비하게 해주는** 시스템이에요"

후자가 압도적으로 임팩트 있음.

---

## 5. SageMaker 를 쓰는 이유 (다른 ML 대비)

| 옵션 | 장단점 |
|---|---|
| **SageMaker** ← 채택 | AWS 생태계 통합 (S3/Athena/IAM 자연스러움), Training+Endpoint+Monitoring 통합, IRSA 패턴 학습 가치 |
| sklearn 로컬 모델 | 간단하지만 production 배포·모니터링 패턴 학습 못함 |
| GCP Vertex AI / Azure ML | 가능하지만 이미 AWS 인프라 위에 있음 → cross-cloud 복잡도 |
| ML 안 쓰고 룰 기반만 | "max_temp > 90 이면 위험" 같은 if문 — 패턴 학습 없음, 새로운 고장 모드 발견 못함 |

---

## 6. 학습자 관점에서 SageMaker 가 주는 것

데이터 엔지니어링 학습자에게 SageMaker 작업이 가르쳐주는 것:

1. **IAM PassRole 패턴** — User 가 SageMaker 에게 임시 권한 위임
2. **Training Job lifecycle** — 일회성 컴퓨팅 vs 영속 endpoint 분리
3. **Athena → S3 → SageMaker 데이터 전달** — 클라우드 서비스 간 S3 brokerage 패턴
4. **Endpoint 를 API 에서 호출** — `/api/predict` → 실제 ML serving 경험
5. **Gold table 을 feature view 로 활용** — feature engineering 이 ETL 의 일부라는 사고

---

## 7. 결론

- **SageMaker 없으면**: 데이터 파이프라인 "빌더" 수준에서 끝남.
- **SageMaker 있으면**: 데이터로 의사결정하는 **자동화된 의사결정 시스템**.

지금까지 만든 인프라 다 SageMaker 를 위한 사전 작업.
Generator → KDS → Firehose → Athena → Gold 가 다 학습 데이터 만드는 파이프라인이고,
API 와 Portal 이 다 추론 결과를 사람에게 보여주는 인터페이스.

**빠지면 미완성품, 들어가면 완제품.**

---

## 부록 — 실행 시 필요한 권한

`de-ai-06` IAM User 에 `AmazonSageMakerFullAccess` managed policy 한 개로 충분:

```bash
aws iam attach-user-policy \
  --user-name de-ai-06 \
  --policy-arn arn:aws:iam::aws:policy/AmazonSageMakerFullAccess
```

SageMaker execution role (`robot-telemetry-sagemaker-role`) 은 이미 `terraform/modules/data_pipeline/sagemaker.tf` 에 있고 `sagemaker.amazonaws.com` 신뢰 정책이 잡혀 있어 추가 작업 불필요.

학습 실행:
```bash
set -a && source .env && set +a
export SAGEMAKER_ROLE_ARN=arn:aws:iam::827913617635:role/robot-telemetry-sagemaker-role
pip install sagemaker xgboost pandas
python3 src/ml/train.py
```

소요 시간: 학습 ~5-10분 + endpoint 배포 ~7-10분 = **약 15분**.

⚠️ 엔드포인트는 시간당 ~$0.07 청구. 데모 끝나면:
```bash
aws sagemaker delete-endpoint --endpoint-name robot-failure-predictor --region eu-west-1
aws sagemaker delete-endpoint-config --endpoint-config-name robot-failure-predictor --region eu-west-1
```
