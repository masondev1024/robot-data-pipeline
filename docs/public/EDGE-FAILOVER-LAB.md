# 멀티리전·멀티CDN Edge Failover Lab

기준일: 2026-08-24

이 문서는 SOOP SRE Engineer 지원 준비에서 부족했던 멀티리전·멀티CDN·실시간 미디어 인프라 관점을 **AWS 리소스 없이** 구현하고 검증한 결정론적 실험이다. 실제 CDN 사업자나 라이브 미디어 트래픽을 운영했다고 주장하는 문서가 아니다.

## 구현 범위

- `ap-northeast-2 / cdn-a` 주 경로
- `eu-west-1 / cdn-b`, `us-east-1 / cdn-b` 보조 경로
- health probe 결과를 캐시하고, 다음 probe까지는 기존 상태를 사용
- 요청 batch가 endpoint capacity를 넘으면 라우팅하지 않는 admission check
- 주 리전 장애를 주입하고 다른 region/CDN으로 failover
- 라우팅 결과를 endpoint, region, CDN, utilization, latency로 구조화

핵심 구현은 [`src/edge_reliability/failover.py`](../../src/edge_reliability/failover.py), 검증 스크립트는 [`scripts/run_edge_failover_lab.py`](../../scripts/run_edge_failover_lab.py), 테스트는 [`tests/test_edge_failover.py`](../../tests/test_edge_failover.py)에 있다.

## 재현

```bash
cd robot-data-pipeline
.venv/bin/python scripts/run_edge_failover_lab.py
```

현재 결정론적 실행 결과:

| 지표 | 결과 |
|---|---:|
| 총 요청 batch | 3,600건 |
| 성공 | 3,000건 |
| 주 리전 장애 시점 | 4초 |
| failover 감지·전환 시점 | 6초 |
| 계산된 failover RTO | 2초 |
| failover 이후 추가 실패 | 0건 |
| lab availability | 83.33% |
| lab p95 latency | 180ms |
| 사용 CDN | `cdn-a → cdn-b` |

장애 순간부터 probe가 상태를 갱신하기 전까지의 600건 실패는 의도적으로 남겼다. 이 값을 숨기지 않고, probe interval을 줄이면 탐지 지연과 probe 비용·오탐 가능성이 어떻게 바뀌는지 토론할 수 있도록 했다. 실제 서비스의 SLO나 RTO로 확대 해석하지 않는다.

## 설계 판단

1. DNS/CDN 레벨의 failover만 가정하지 않고 origin capacity admission을 함께 둔다. 보조 경로가 살아 있어도 capacity가 없으면 5xx를 다른 곳으로 전파할 수 있기 때문이다.
2. health probe interval을 명시적인 정책 값으로 둔다. failover RTO는 “장애가 발생하면 즉시 전환”이라는 가정이 아니라 감지 주기와 라우팅 반영 시간의 합으로 설명한다.
3. region과 CDN을 서로 다른 장애 도메인으로 모델링한다. 한 CDN의 장애가 모든 region의 사용자 경험을 동시에 망가뜨리지 않도록 provider diversity를 topology validation에서 요구한다.
4. 이 랩은 비용 없는 정책 검증 계층이다. 실제 검증으로 승격할 때는 synthetic media segment probe, CDN별 cache hit/miss, origin 4xx/5xx, rebuffering ratio, segment latency, DNS/Anycast 전환 시간을 별도 측정해야 한다.

## 채용 역량과의 연결

| 역량 | 이 저장소의 증거 | 증거 수준 |
|---|---|---|
| 성능·안정성을 데이터로 운영 | Kinesis/Firehose SLO, 100Hz smoke 7,200 records, throttle 0, Parquet 객체 2개 | 실제 단기 AWS 검증 |
| 변경 사전 차단·빠른 복구 | Terraform cost precondition, OIDC 계정 공유 경계, Argo Rollouts analysis/rollback, failure drill | 코드·CI·runbook |
| 멀티리전·멀티CDN·미디어 | region/CDN topology, health probe, capacity admission, outage failover simulation | 무비용 로컬 lab; 실환경 미검증 |

세 번째 항목은 면접에서 “운영했다”고 말하지 않고, “실환경 비용을 발생시키지 않는 결정론적 failover 정책을 구현·테스트했고, 실제 미디어 계층에서 검증해야 할 지표까지 정의했다”고 설명한다.
