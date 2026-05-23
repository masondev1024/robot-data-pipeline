# Karpenter Configuration

## Overview
이 디렉토리는 Karpenter의 **NodePool** 설정을 포함합니다.

- `nodepool.yaml`: Karpenter NodePool 및 EC2NodeClass 정의

## 배포 순서

1. **Terraform으로 Karpenter Helm 차트 설치** (terraform apply)
   ```bash
   cd terraform
   terraform apply
   # → karpenter namespace, controller, RBAC가 배포됨
   ```

2. **K8s NodePool 매니페스트 적용** (kubectl apply)
   ```bash
   kubectl apply -f k8s/karpenter/nodepool.yaml
   # → Karpenter가 NodePool을 인식하고 노드 프로비저닝 시작
   ```

## NodePool 특징

### 프로비저닝 정책
- **Capacity Type**: On-demand (비용 안정성 우선)
- **Instance Types**: t3.large, t3.xlarge, t3a.large, t3a.xlarge
- **최대 리소스**: CPU 100, Memory 100Gi

### 자동 스케일다운 (Disruption)
- Consolidation: 30초마다 최적화 검토
- 점진적 축소: 매주 월-금 9시 AM에 10% 노드 축소
- 미사용 Pod 기반 스케일다운: Underutilized/Empty 노드 우선

### Taints
```yaml
taints:
  - key: workload
    value: batch
    effect: NoSchedule
```
**주의**: 이 Taint를 tolerate하지 않는 Pod는 Karpenter 노드에 스케줄되지 않음!

## Toleration 설정 (필요시)

만약 특정 Pod을 Karpenter 노드에서 실행하려면 toleration 추가:

```yaml
tolerations:
  - key: workload
    operator: Equal
    value: batch
    effect: NoSchedule
```

예를 들어 Airflow Worker:
```yaml
# k8s/api/deployment.yaml 또는 Helm values에서
tolerations:
  - key: workload
    operator: Equal
    value: batch
    effect: NoSchedule
```

## 모니터링

```bash
# Karpenter 컨트롤러 로그
kubectl logs -f deployment/karpenter -n karpenter

# NodePool 상태 확인
kubectl get nodepools

# 프로비저닝된 노드 확인 (karpenter 라벨)
kubectl get nodes -L karpenter.sh/capacity-type
```

## 문제 해결

### Pod가 Pending 상태일 때
1. Toleration 확인: `kubectl describe pod <pod-name>`
2. NodePool 리소스 확인: `kubectl get nodepools`
3. Karpenter 로그 확인: `kubectl logs deployment/karpenter -n karpenter`

### 노드가 프로비저닝되지 않음
1. Karpenter controller 상태: `kubectl get deployment karpenter -n karpenter`
2. EC2NodeClass 이름 확인: nodepool.yaml의 `nodeClassRef.name`이 EC2NodeClass의 metadata.name과 일치하는지 확인
3. IAM 권한 확인: karpenter-controller role에 필요한 IAM 권한 있는지 확인
