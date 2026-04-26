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
