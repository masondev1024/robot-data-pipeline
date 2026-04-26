# Architecture Decision Records

## 철학
데드라인(2026-05-08) 내 핵심 비즈니스 로직 우선. CI/CD 완성도보다 데이터 가공·LLM 연동에 리소스를 집중한다. AWS 관리형 서비스를 최대한 활용하여 운영 부담을 최소화한다.

---

### ADR-001: Lambda Architecture 채택 (vs Kappa Architecture)
**결정**: Speed Layer(Kinesis+Flink)와 Batch Layer(Firehose+S3+Athena) 병렬 운용
**이유**: 실시간 이상 탐지(1분 윈도우)와 대용량 일별 집계를 동시에 요구. Kappa는 스트림 재처리 비용이 높고, Batch 경로가 현 팀 역량 기준 더 안정적
**트레이드오프**: Speed/Batch 레이어 간 데이터 일관성 관리 필요. 인프라 복잡도 증가

### ADR-002: Amazon Kinesis Data Streams 채택 (vs Apache Kafka on MSK)
**결정**: KDS Provisioned Mode, **Shard 10개**, 데이터 보존 24시간
**이유**: AWS 관리형 서비스로 운영 부담 없음. 가상 로봇 10,000대 × 1 rec/sec = 10,000 rec/sec, 레코드당 ~1KB → 10 MB/sec 처리량 요구. KDS Shard 1개 한도(1,000 rec/sec, 1 MB/sec)에서 Shard 10개가 필요. enterprise IoT 플릿 스케일 시뮬레이션으로 파이프라인 처리 능력 실증. MSK는 클러스터 설정·운영 비용 과다
**트레이드오프**: Kafka 대비 파티션 전략 유연성 낮음. Shard 10개 비용($0.015/hr × 10 = $0.15/hr) 발생

### ADR-003: S3 + Parquet + Athena + Partition Projection 채택 (vs Redshift / EMR)
**결정**: S3를 Data Lakehouse로, Athena로 서버리스 쿼리, Partition Projection으로 스캔 비용 최적화
**이유**: 현재 데이터 볼륨은 Redshift를 정당화하기에 부족. EMR은 운영 복잡도 과다. Athena는 스캔 데이터 기준 과금이므로 파티셔닝으로 비용 최소화 가능
**트레이드오프**: Athena 동시 쿼리 한도. 복잡한 JOIN·집계 성능은 Redshift 대비 낮음

### ADR-004: Amazon Bedrock (Claude 3) 채택 (vs OpenAI API)
**결정**: Bedrock의 Claude 3 Sonnet 또는 Haiku 모델 사용
**이유**: AWS VPC 내 데이터 이동으로 외부 유출 없음(데이터 프라이버시). IAM 기반 인증으로 별도 API 키 관리 불필요. AWS 과금 통합
**트레이드오프**: OpenAI 대비 모델 선택 폭 좁음. 일부 언어 지시 따르기 성능 차이 가능

### ADR-005: EKS + IRSA 채택 (vs EC2 직접 배포)
**결정**: Generator를 EKS Deployment로 배포, IRSA로 Kinesis PutRecord 권한 부여
**이유**: Daemon형 상시 구동에 컨테이너 자동 재시작·헬스체크 필요. IRSA는 AWS 자격증명을 코드에 하드코딩하지 않는 AWS 베스트 프랙티스
**트레이드오프**: EKS 클러스터 운영 비용 발생(최소 2노드). Karpenter 초기 설정 복잡도

### ADR-006: Grafana (EKS Helm) 채택 (vs 커스텀 Flask 대시보드)
**결정**: Grafana를 EKS에 Helm으로 배포, Athena Plugin + CloudWatch를 데이터 소스로 연결
**이유**: 코딩 없이 시각화 완성도가 압도적으로 높음. Athena Plugin이 Silver/Gold 테이블을 직접 조회하므로 별도 API 레이어 불필요. `addons.tf`에 Helm release 한 줄 추가로 기존 EKS 배포 패턴과 일관성 유지
**트레이드오프**: Grafana 자체 학습 곡선 존재. Athena Plugin 쿼리 응답 속도가 실시간 스트리밍보다 느림(배치성 대시보드에 적합). 완전한 커스텀 UI는 불가

### ADR-007: Flink → Alert KDS → Lambda → SNS → Slack 채택
**결정**: Flink Sink는 `robot-anomaly-alert-stream`(KDS)으로 한정. Lambda(`robot-anomaly-alert-lambda`)가 KDS 트리거로 SNS Publish → Slack Webhook 전달
**이유**: Flink(AWS Managed Flink 포함)에는 SNS Native Sink 커넥터가 없음. 커스텀 Async I/O로 구현 시 Java/Scala 필요 — 데드라인 위협. KDS Native Sink는 공식 지원. Lambda를 Fan-out 브리지로 두면 추후 이메일·PagerDuty 구독 추가도 용이. Slack Webhook URL은 `.env`로 주입
**트레이드오프**: Lambda 추가로 리소스 1개 증가. KDS → Lambda 폴링 지연(최대 수 초) 발생 가능. 단, 이상 감지 알림 특성상 수 초 지연은 허용 범위

### ADR-008: Bedrock 대화형 Query (FastAPI + Text-to-Insight 패턴)
**결정**: FastAPI 서버가 사용자 질문 수신 → Athena Gold 테이블 조회 → 데이터+질문을 Bedrock Claude 3에 전달 → 자연어 답변 반환. 채팅 UI는 FastAPI가 정적 HTML로 서빙
**이유**: 별도 프론트엔드 프레임워크(React 등) 없이 FastAPI 단독으로 API + UI를 모두 처리해 복잡도 최소화. Athena 조회 결과를 프롬프트 컨텍스트로 주입하는 방식은 RAG의 경량 구현으로 포트폴리오 차별화 포인트. 기존 Generator의 `boto3` 패턴을 그대로 재사용 가능
**트레이드오프**: Athena 쿼리 응답 지연(2~5초) 문제는 **in-memory 캐시**로 해결 — FastAPI 시작 시 및 매일 `CACHE_REFRESH_HOUR`시(Airflow 배치 완료 후)에 Gold 최신 파티션을 1회 조회하여 전역 캐시에 저장. 채팅 요청은 캐시에서 즉시 읽어 Bedrock 호출. 일별 집계 데이터 특성상 24시간 캐시 유효. 스트리밍 응답(SSE/WebSocket)은 초기 구현에서 제외

### ADR-009: 고도화된 이상 탐지 — Z-Score + 다변량 상관 (vs 단순 임계값)
**결정**: 단순 `motor_temp > 90°C` 단일 임계값을 **두 조건의 OR 결합**으로 고도화한다.
- **Condition 1 (Moving Z-Score)**: 최근 5분간 robot_id별 `motor_temp` 평균 μ, 표준편차 σ를 OVER window로 계산 → `|temp - μ| / σ > 3` 시 통계적 이상
- **Condition 2 (Multivariate Correlation)**: `motor_temp >= 85.0 AND (motor_temp / GREATEST(current_load, 1)) > 1.8` — 부하 대비 과열 (분모 0 division 가드 포함)
- 두 조건 중 하나만 만족해도 alert 발생

**이유**:
- 단순 임계값은 노이즈 한 번에 false positive 발생 → **알람 피로도** 증가, 운영자가 알람 무시
- Z-Score는 로봇별 베이스라인을 학습하므로 "이 로봇에게는 이상"인 신호를 정확히 잡음 (개별 로봇의 정상 운영 온도가 70~95°C 등 다양)
- 다변량 상관은 "고부하인데 온도가 낮으면 정상" / "저부하인데 온도가 높으면 위험" 패턴 검출 → 단순 임계로는 못 잡는 sensor drift / 베어링 마모 등 조기 신호
- AI4I 2020 데이터셋 자체가 다변수 (`Process temperature`, `Rotational speed`, `Tool wear`) 상관 기반 고장 라벨링 → 다변량 검출과 자연스럽게 정합
- 데드라인 내 구현 가능: Flink Table API의 `OVER PARTITION BY robot_id ORDER BY event_time RANGE INTERVAL '5' MINUTE`로 Z-Score 즉시 계산

**트레이드오프**:
- 단순 SQL 1줄 → 이중 조건 + OVER window로 코드/디버깅 복잡도 증가
- OVER window는 robot_id별 state를 유지 → state size 증가 (Managed Flink KPU 비용 약간 증가, 단 10,000 로봇 × 5분 × float = ~100MB 수준으로 미미)
- threshold(`zscore=3.0`, `load_ratio=1.8`)는 운영 데이터로 튜닝 필요 → Flink `environment_properties`의 `property_map`으로 외부화하여 코드 수정 없이 조정 가능

### ADR-010: PyFlink 채택 (vs Flink SQL CLI / Java / Studio Notebook)
**결정**: Managed Flink Application 모드 + **PyFlink (Table API)** 로 이상 탐지 앱 구현. 코드를 ZIP으로 패키징하여 S3에 업로드, Terraform `aws_s3_object`로 추적
**이유**: 팀의 주 언어가 Python (Generator, API, DAG 모두 Python). Java로 통일 시 학습 곡선 + 데드라인 위협. Studio Notebook(Zeppelin)은 운영 배포가 아닌 인터랙티브 분석용으로 부적합. Flink SQL CLI는 standalone 실행만 지원. PyFlink Table API는 SQL을 그대로 임베딩 가능하며 Managed Flink Application의 공식 지원 런타임
**트레이드오프**: PyFlink는 Java 대비 약 5~10% 성능 손실 (PythonVM 브리징). 단, 10,000 rec/sec 스케일에서는 무시 가능. UDF 작성 시 Python ↔ JVM 직렬화 오버헤드 존재 → 본 프로젝트는 SQL OVER window만 사용하므로 영향 없음
