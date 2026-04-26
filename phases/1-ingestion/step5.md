# Step 5: generator-k8s

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-005: IRSA)
- `/src/generator/app.py`
- `/data/seed_data_sample.csv`
- `/terraform/modules/data_pipeline/iam.tf`

## 작업

세 가지 파일을 작성하라: **Dockerfile**, **K8s Deployment**, **ConfigMap (Seed CSV 마운트)**

---

### `src/generator/Dockerfile`
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

# Seed CSV는 ConfigMap으로 마운트되므로 /data 디렉토리만 생성
RUN mkdir /data

USER 65534
CMD ["python3", "app.py"]
```

---

### `k8s/generator/configmap.yaml`
Seed CSV를 ConfigMap으로 관리하여 Pod에 마운트한다:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: generator-seed
  namespace: robot-telemetry
data:
  seed_data_sample.csv: |
    # data/seed_data_sample.csv 내용을 여기에 그대로 붙여넣는다
    # (generate_sample.py 실행 후 생성된 CSV)
    UDI,Product ID,Type,...
```

---

### `k8s/generator/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: robot-telemetry-generator
  namespace: robot-telemetry
spec:
  replicas: 1
  selector:
    matchLabels:
      app: robot-telemetry-generator
  template:
    metadata:
      labels:
        app: robot-telemetry-generator
    spec:
      serviceAccountName: generator-sa
      containers:
        - name: generator
          image: <ECR_URL>/robot-telemetry-generator:latest
          # 실제 ECR URL: terraform output ecr_generator_url
          env:
            - name: ROBOT_COUNT
              value: "10000"
            - name: KINESIS_STREAM_NAME
              value: "robot-telemetry-stream"
            - name: KINESIS_ALERT_STREAM_NAME
              value: "robot-anomaly-alert-stream"
            - name: AWS_DEFAULT_REGION
              value: "ap-northeast-2"
            - name: SEED_CSV_PATH
              value: "/data/seed_data_sample.csv"
          volumeMounts:
            - name: seed-data
              mountPath: /data
              readOnly: true
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              cpu: "2"
              memory: "2Gi"
      volumes:
        - name: seed-data
          configMap:
            name: generator-seed
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: generator-sa
  namespace: robot-telemetry
  annotations:
    eks.amazonaws.com/role-arn: <IRSA_ROLE_ARN_PLACEHOLDER>
    # 실제 ARN: terraform output -module=data_pipeline generator_irsa_role_arn
```

---

## Acceptance Criteria

```bash
python3 -m py_compile src/generator/app.py

grep -q "namespace: robot-telemetry" k8s/generator/deployment.yaml && echo "OK: namespace"
grep -q "SEED_CSV_PATH" k8s/generator/deployment.yaml && echo "OK: seed csv env"
grep -q "ROBOT_COUNT" k8s/generator/deployment.yaml && echo "OK: robot count"
grep -q "robot-telemetry-stream" k8s/generator/deployment.yaml && echo "OK: stream name"
grep -q "configMap" k8s/generator/deployment.yaml && echo "OK: configmap volume"
grep -q "memory.*2Gi" k8s/generator/deployment.yaml && echo "OK: memory limit"
grep -q "seed_data_sample.csv" k8s/generator/configmap.yaml && echo "OK: configmap has csv"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - 네임스페이스가 `robot-telemetry`인가? (`default`면 IRSA 실패)
   - Seed CSV가 ConfigMap으로 마운트되는가? (Secret 불필요 — 공개 데이터)
   - `SEED_CSV_PATH=/data/seed_data_sample.csv`인가?
   - 메모리 limit이 2Gi 이상인가? (asyncio 10,000 태스크)
   - ServiceAccount에 IRSA ARN 플레이스홀더가 있는가?
3. `phases/1-ingestion/index.json` step 5 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "Dockerfile + configmap.yaml(seed CSV) + deployment.yaml: ns=robot-telemetry, ConfigMap 마운트, IRSA SA, ROBOT_COUNT=10000, 2Gi"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- 네임스페이스를 `default`로 쓰지 마라. 이유: IRSA Condition이 `robot-telemetry`로 고정
- `kind: ArgoRollout`을 쓰지 마라. 이유: Generator는 Daemon형 상시 구동
- Seed CSV를 Secret으로 마운트하지 마라. 이유: 공개 데이터셋이므로 ConfigMap이 적합
- 메모리 limits를 512Mi 이하로 설정하지 마라. 이유: asyncio 10,000 코루틴 + boto3 KDS 버퍼링
