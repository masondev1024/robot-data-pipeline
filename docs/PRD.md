# PRD: 스마트 팩토리 로봇 텔레메트리 파이프라인

## 목표
Kaggle AI4I 2020 Predictive Maintenance 데이터를 Seed로 가상 로봇 10,000대를 시뮬레이션하여, 실시간 이상 탐지 알림 · Grafana 운영 대시보드 · 대화형 AI 정비 분석까지 갖춘 엔터프라이즈급 스마트 팩토리 IoT 모니터링 플랫폼을 AWS 위에 구축한다.

## 사용자
- **데이터 엔지니어**: Terraform 인프라, Airflow DAG, Kinesis/Flink 파이프라인 관리 담당
- **운영 관리자**: Grafana 대시보드에서 로봇 Fleet 현황·파이프라인 헬스를 실시간 모니터링
- **현장 작업자**: Flink이 이상 감지 시 Slack 채널에서 즉시 알림 수신
- **현장 정비반장**: 대화형 AI에 자연어로 질문하여 점검 우선순위 및 원인 분석 수신

## 핵심 기능
1. **데이터 수집 (Generator)**: AI4I 2020 CSV Seed 기반 asyncio로 가상 로봇 10,000대 초당 1건 시뮬레이션 → Kinesis Data Streams 전송
2. **Medallion 배치 ETL**: Airflow가 매일 00:00 KST에 Bronze(Raw Parquet) → Silver(정제) → Gold(집계) 자동 처리
3. **실시간 이상 탐지 (Flink)**: motor_temp > 90°C 로봇을 1분 Tumbling Window로 실시간 감지
4. **실시간 Slack 알림**: Flink 이상 탐지 이벤트 → SNS → Slack Webhook으로 즉시 운영 채널 알림
5. **Grafana 운영 대시보드**: 로봇 Fleet 상태, 이상치 타임라인, 파이프라인 처리량을 Athena·CloudWatch 기반으로 시각화
6. **LLM 배치 리포트 (Bedrock)**: Gold 데이터 기반, Claude 3 모델이 매일 점검 우선순위 리포트 자동 생성 → S3 저장
7. **대화형 AI 정비 분석 (Bedrock Chat)**: FastAPI 서버가 사용자 질문을 받아 Athena Gold 테이블 조회 후 Claude 3에 전달 → 자연어 답변 반환 (채팅 UI 제공)

## MVP 제외 사항
- RDS / Bastion 호스트 (이번 프로젝트 범위 외)
- Blue/Green 배포, Argo Rollouts (Generator·API 서버는 단순 Daemon Deployment 사용)
- Grafana 알림(Alert Rule) 고도화 (기본 대시보드 시각화만 구현)

## 디자인
- AWS 클라우드 네이티브 서비스 우선 (Kinesis, Firehose, Athena, Managed Flink, Bedrock, EKS)
- 하드코딩 금지 — 모든 설정값은 `variables.tf` 또는 `.env` 파일로 분리
- 데이터 레이어: Medallion Architecture (Bronze / Silver / Gold)
- 데드라인: 2026-05-01
