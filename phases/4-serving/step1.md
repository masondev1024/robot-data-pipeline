# Step 1: grafana-helm

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-006: Grafana)
- `/terraform/addons.tf`
- `/sql/silver_ddl.sql`
- `/sql/gold_ddl.sql`

## 작업

### `terraform/addons.tf` 업데이트
기존 파일에 Grafana Helm Release를 추가하라:
```hcl
resource "aws_helm_release" "grafana" {
  name             = "grafana"
  repository       = "https://grafana.github.io/helm-charts"
  chart            = "grafana"
  namespace        = "monitoring"
  create_namespace = true
  depends_on       = [aws_eks_node_group.main]

  set {
    name  = "adminPassword"
    value = var.grafana_admin_password  # variables.tf에 sensitive 변수 추가
  }
  set {
    name  = "service.type"
    value = "ClusterIP"
  }
  set {
    name  = "persistence.enabled"
    value = "true"
  }
}

variable "grafana_admin_password" { sensitive = true }
```

### `grafana/dashboards/robot_fleet.json`
로봇 Fleet 현황 대시보드 JSON 초안:
- 패널: 로봇별 최신 `avg_motor_temp` 상위 10대 (Bar chart)
- 패널: `battery_drain` 최대 로봇 Top 10 (Table)
- Data source: Athena Plugin (`robot_telemetry_db.gold_robot_daily_stats`)
- Refresh: 1h (배치성 대시보드이므로 실시간 불필요)
- 파티션 필터: `dt = current_date - interval 1 day`

### `grafana/dashboards/anomaly_timeline.json`
이상치 탐지 타임라인:
- 패널: 시간대별 이상 탐지 건수 시계열 (Time series)
- Data source: Athena Plugin (`robot_telemetry_db.bronze_robot_telemetry`, `motor_temp > 90` WHERE 조건)
- 파티션 필터: 최근 24시간 hour 범위

### `grafana/dashboards/pipeline_health.json`
파이프라인 헬스:
- 패널: Kinesis `IncomingRecords` (CloudWatch Metric)
- 패널: Kinesis Firehose `DeliveryToS3.Records` (CloudWatch Metric)
- 패널: EKS Pod CPU/Memory (CloudWatch Container Insights)
- Data source: CloudWatch

각 JSON은 Grafana dashboard export 형식 (`{"uid": "...", "panels": [...], "title": "..."}`).
실제 Data Source UID는 플레이스홀더 `"${DS_ATHENA}"`, `"${DS_CLOUDWATCH}"`로 두고 주석으로 교체 방법을 안내한다.

## Acceptance Criteria

```bash
terraform fmt -check terraform/addons.tf
ls grafana/dashboards/robot_fleet.json grafana/dashboards/anomaly_timeline.json grafana/dashboards/pipeline_health.json
python3 -c "
import json, sys
for f in ['grafana/dashboards/robot_fleet.json', 'grafana/dashboards/anomaly_timeline.json', 'grafana/dashboards/pipeline_health.json']:
    d = json.load(open(f))
    assert 'panels' in d, f'{f}: panels missing'
    assert 'title' in d, f'{f}: title missing'
print('OK: all dashboards valid JSON with panels')
"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - addons.tf에 grafana helm release가 있는가?
   - `grafana_admin_password`가 sensitive 변수로 관리되는가?
   - 3개 대시보드 JSON이 모두 존재하고 파싱 가능한가?
   - fleet/anomaly 대시보드가 Athena Plugin Data Source를 참조하는가?
   - pipeline_health 대시보드가 CloudWatch를 참조하는가?
3. `phases/4-serving/index.json` step 1 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "addons.tf Grafana Helm 추가 + grafana/dashboards/ 3개 JSON(fleet, anomaly, pipeline_health)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- `grafana_admin_password`를 하드코딩하지 마라. 이유: `var.grafana_admin_password` sensitive 변수로만 관리
- `service.type = "LoadBalancer"`로 설정하지 마라. 이유: ClusterIP + ALB Ingress를 통해 노출 (비용 절약)
- Athena 쿼리 결과를 Grafana Dashboard JSON에 하드코딩하지 마라. 이유: 동적 파라미터($__from, $__to)를 사용해야 한다
