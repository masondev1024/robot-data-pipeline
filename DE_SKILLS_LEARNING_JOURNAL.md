# 🚀 Data Engineering Skills & Learning Journal

이 문서는 `robot-data-pipeline` 프로젝트를 구축하며 발생한 기술적 의사결정, 핵심 개념, 그리고 데이터 엔지니어로서 갖춰야 할 실무 스킬들을 정리한 기술 노트입니다.

---

## 📂 [Phase 0] Infrastructure & Architecture

### 1. EKS Node Selection: t3.large를 선택한 이유 (Cost vs Stability)
- **Concept**: Kubernetes Node Sizing & Memory Management
- **Decision**: `t3.medium` (4GB RAM) 대신 `t3.large` (8GB RAM) 선택.
- **Rationale**:
    - **System Overhead**: K8s 관리용 Pod(`aws-node`, `coredns` 등)이 노드당 약 1GB를 기본 점유함.
    - **App Requirements**: Airflow(Webserver, Scheduler, Worker) 구동에는 최소 4GB 이상의 여유 메모리가 필수적임.
    - **Risk Management**: 메모리 부족(OOM)으로 인한 노드 다운 및 서비스 장애를 방지하기 위한 최소 마지노선임.
- **DE Skill**: 애플리케이션의 워크로드를 분석하여 인프라 비용과 안정성 사이의 최적점을 찾는 능력.

### 2. Kinesis Shard Throughput 설계 (Data Scale-out)
- **Concept**: Stream Processing Throughput Calculation
- **Requirement**: 가상 로봇 10,000대 × 1 rec/sec = 10,000 records/sec
- **Constraint**: Kinesis Shard 1개당 입력 한도 = 1,000 records/sec
- **Calculation**: $10,000 \div 1,000 = 10 \text{ Shards}$
- **Decision**: 메인 스트림에 **10개의 샤드**를 할당하여 데이터 병목 현상 방지.
- **DE Skill**: 데이터 발생량을 기반으로 서비스 중단 없는 인프라 용량(Capacity Planning)을 산정하는 수치적 감각.

### 3. VPC Endpoint (PrivateLink)를 이용한 비용 최적화
- **Concept**: Private Networking & Data Transfer Cost
- **Decision**: S3 Gateway 및 Kinesis Interface VPC Endpoint 적용.
- **Rationale**:
    - **Security**: 트래픽이 퍼블릭 인터넷을 타지 않고 AWS 내부망 내에서만 이동함.
    - **Cost**: NAT Gateway를 통한 데이터 처리 비용($0.045/GB)을 제거하여 대용량 스트리밍 트래픽 전송 비용을 90% 이상 절감함.
- **DE Skill**: 클라우드 네트워크 아키텍처를 이해하고 데이터 전송 비용(Egress/Data Transfer)을 관리하는 능력.

### 4. IRSA (IAM Role for Service Accounts)
- **Concept**: Cloud Native Security & Principle of Least Privilege
- **Decision**: EC2 노드에 통권한을 주는 대신, Pod별 전용 IAM Role 부여.
- **Rationale**: 특정 Pod(예: Generator)이 탈취되어도 다른 리소스(예: SageMaker)에 접근하지 못하도록 격리함.
- **DE Skill**: "최소 권한 원칙"에 기반한 보안 설계 능력.

---

## 🔍 Deep Dive: 핵심 개념 상세 분석

### 1. IRSA vs Node IAM Role
- **Node Role**: 노드(EC2)에 권한을 부여. 노드 내 모든 Pod이 동일 권한 공유 (보안 취약).
- **IRSA**: Pod의 Service Account와 IAM Role을 1:1 매핑. 앱 단위 권한 격리 (보안 강화).
- **Practical Tip**: 면접에서 "EKS 보안을 어떻게 강화했나?"라는 질문에 "IRSA를 통해 Pod 간 권한을 분리했다"라고 답변할 것.

### 2. Watermark: 스트리밍 데이터의 '기다림'
- **Problem**: 이벤트 발생 시간(Event Time)과 도착 시간(Processing Time)의 시차 발생.
- **Solution**: "X초까지는 늦게 와도 받아줄게"라는 임계값(Watermark) 설정.
- **Trade-off**: 많이 기다리면 정확도가 올라가지만 지연시간(Latency)이 길어짐. 적게 기다리면 속도는 빠르지만 데이터 유실 가능성 있음.

### 3. 배치 처리의 멱등성 (Idempotency)
- **질문**: "중복 체크해서 넣으면 되는데 왜 굳이 덮어쓰기(Overwrite)를 하나요?"
- **답변**:
    - **Scale**: 데이터 레이크(S3)는 RDB처럼 실시간 유니크 체크가 불가능하거나 매우 비쌈.
    - **Reliability**: 에러 발생 후 재시도 시, 상태를 체크하는 복잡한 로직보다 파티션 전체를 교체하는 것이 '무조건 성공'을 보장함.
    - **Simplicity**: `INSERT OVERWRITE`는 복잡한 `UPSERT` 로직 없이도 데이터 정합성을 유지하는 가장 확실한 방법.

---

## 🛠️ Upcoming Learning Points (To-be)
- [ ] **GitHub Actions OIDC**: 비밀 키 관리 없는 안전한 배포.
- [ ] **Medallion Architecture**: Raw(Bronze) -> Silver -> Gold 가공 단계의 의미.
- [ ] **Idempotency (멱등성)**: Airflow DAG 재실행 시 데이터 중복 방지 로직.
- [ ] **Watermark**: Flink 실시간 처리 시 지연 데이터 처리 전략.

---
*마지막 업데이트: 2026-04-26*
