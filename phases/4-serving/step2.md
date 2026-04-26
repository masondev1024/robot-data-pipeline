# Step 2: api-server

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-008: Bedrock 대화형 Query)
- `/docs/PRD.md`
- `/sql/gold_ddl.sql`
- `/terraform/modules/data_pipeline/iam.tf`

## 작업

FastAPI AI Query API 서버 전체를 작성하라.

### `src/api/main.py`

**설계 핵심: in-memory 캐시 패턴**
- Athena 조회를 매 요청마다 실행하지 않는다 (응답 지연 수 초 방지)
- 앱 시작 시 + 매일 `CACHE_REFRESH_HOUR`(기본 01:00 KST)에 Gold 테이블 최신 파티션을 한 번 조회하여 전역 변수에 저장
- `apscheduler.schedulers.asyncio.AsyncIOScheduler` 사용

```python
# 전역 캐시
_gold_cache: str = ""
_cache_updated_at: str = ""

async def refresh_cache():
    """Athena 조회 → _gold_cache 갱신. 앱 시작 + 스케줄러 호출."""
    global _gold_cache, _cache_updated_at
    # boto3 Athena client
    # DB: robot_telemetry_db, Table: gold_robot_daily_stats
    # Workgroup: robot-telemetry-workgroup
    # Output: s3://.../project-athena-results/
    # 어제 날짜 파티션 조회, 결과 CSV 파싱 → 문자열로 변환
    ...

@app.on_event("startup")
async def startup():
    await refresh_cache()
    scheduler = AsyncIOScheduler()
    hour = int(os.environ.get("CACHE_REFRESH_HOUR", "1"))
    scheduler.add_job(refresh_cache, "cron", hour=hour, minute=0)
    scheduler.start()
```

**`POST /api/chat`**:
```python
class ChatRequest(BaseModel):
    question: str

@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not _gold_cache:
        raise HTTPException(503, "캐시가 아직 준비되지 않았습니다.")
    prompt = f"다음은 공장 로봇 상태 데이터야:\n{_gold_cache}\n\n질문: {req.question}"
    # Bedrock InvokeModel (BEDROCK_MODEL_ID 환경변수)
    # Messages API 형식, max_tokens=512
    return {"answer": response_text, "cached_at": _cache_updated_at}
```

**`GET /`**: `src/api/templates/chat.html` 정적 서빙 (Jinja2 또는 HTMLResponse)

### `src/api/templates/chat.html`
- 단순 채팅 UI: 질문 입력 → POST /api/chat → 답변 표시
- 외부 CDN 없이 인라인 CSS/JS (네트워크 의존성 최소화)
- 캐시 갱신 시각 표시

### `src/api/Dockerfile`
- Base: `python:3.11-slim`
- `uvicorn[standard]` 포함
- `CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]`

### `k8s/api/deployment.yaml`
```yaml
namespace: robot-telemetry
serviceAccountName: api-sa
env:
  - BEDROCK_MODEL_ID (env value from plan.md)
  - ATHENA_DATABASE=robot_telemetry_db
  - ATHENA_WORKGROUP=robot-telemetry-workgroup
  - ATHENA_OUTPUT_LOCATION=s3://.../project-athena-results/
  - CACHE_REFRESH_HOUR=1
  - AWS_DEFAULT_REGION=ap-northeast-2
resources: { requests: "200m/256Mi", limits: "1/1Gi" }
```

**ServiceAccount** `api-sa` (ns: robot-telemetry): IRSA 어노테이션 플레이스홀더 포함

### `terraform/modules/data_pipeline/iam.tf` 업데이트
AI API Pod용 IRSA Role 추가:
- ServiceAccount: `system:serviceaccount:robot-telemetry:api-sa`
- 권한:
  - Athena: `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults`
  - S3: `s3:GetObject`, `s3:PutObject` (Athena 결과 버킷)
  - Glue: `glue:GetTable`, `glue:GetDatabase`
  - Bedrock: `bedrock:InvokeModel`

## Acceptance Criteria

```bash
python3 -m py_compile src/api/main.py
grep -q "robot-telemetry" k8s/api/deployment.yaml && echo "OK: namespace"
grep -q "CACHE_REFRESH_HOUR" k8s/api/deployment.yaml && echo "OK: cache refresh"
grep -q "api-sa" k8s/api/deployment.yaml && echo "OK: service account"
grep -q "bedrock:InvokeModel" terraform/modules/data_pipeline/iam.tf && echo "OK: Bedrock IAM"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - `POST /api/chat`이 캐시에서 데이터를 읽는가? (Athena 실시간 조회 금지)
   - apscheduler로 매일 `CACHE_REFRESH_HOUR`에 캐시가 갱신되는가?
   - IAM에 `bedrock:InvokeModel` 권한이 있는가?
   - SA 네임스페이스가 `robot-telemetry`인가?
   - Athena DB/Workgroup/Output이 모두 plan.md 확정값인가?
3. `phases/4-serving/index.json` step 2 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "src/api/main.py(FastAPI+캐시), templates/chat.html, Dockerfile, k8s/api/deployment.yaml, iam.tf API IRSA 추가"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- `POST /api/chat`에서 매 요청마다 Athena 실시간 조회를 실행하지 마라. 이유: Athena 쿼리는 수 초 걸려 채팅 UX를 망친다. 반드시 캐시에서 읽어라
- `BEDROCK_MODEL_ID`를 코드에 하드코딩하지 마라. 이유: 환경변수로 관리
- AWS 자격증명을 코드에 직접 넣지 마라. 이유: IRSA로 자동 주입
- `service.type = "LoadBalancer"`로 설정하지 마라. 이유: ClusterIP만, 노출은 ALB Ingress에서
