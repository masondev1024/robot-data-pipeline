# Step 5: portal-and-ux-bugs (FastAPI 통합 관제 포털 + UX 버그 6건 수정)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-008 — Bedrock 대화형 Query)
- `/docs/UI_GUIDE.md` (Dark Mode 원칙, Touch Target 44px 등 — 있을 시)
- `/src/api/main.py` (step 2 산출물 — 보강 대상)
- `/src/api/templates/chat.html` (step 2 산출물 — 참조용, 삭제하지 않고 portal.html과 공존)
- `/k8s/api/deployment.yaml` (step 2 산출물 — ConfigMap env 추가 대상)
- `/requirements.txt` (slowapi 추가 대상)
- `/plan.md` Task 4.3 + Task 4.3.5(6개 버그) — **읽기만, 수정 금지**

## 작업

다음 4종 산출물을 한 번에 처리한다 (모두 같은 main.py·portal.html·deployment 영역). 산출물 간 일관성 필수.

### A) `src/api/main.py` 보강 (덮어쓰기)

기존 chat 엔드포인트는 유지하면서 다음을 모두 적용:

> **⚠️ Idempotent 처리 주의:** step 2 worker가 일부 항목(`_data_date`, `_cache_ready`, `slowapi` import, `pytz.timezone("Asia/Seoul")`, `hpa.yaml minReplicas:1`)을 이미 구현했을 수 있다. **각 항목을 grep으로 먼저 확인하고 이미 있으면 건드리지 말 것.** 누락된 것(Bedrock 모델 ID, `/api/status` 엔드포인트, `system` 필드 분리, `links[]` 응답, portal.html, GET / 라우트 등)만 추가/수정.

1. **Bedrock 모델 ID 기본값 변경 (Sonnet 3.5)**
   ```python
   BEDROCK_MODEL_ID = os.environ.get(
       "BEDROCK_MODEL_ID",
       "anthropic.claude-3-5-sonnet-20241022-v2:0",  # Claude 3.5 Sonnet v2
   )
   ```
   기존 `claude-3-haiku-20240307-v1:0` 기본값이 있으면 위로 교체.

2. **Bedrock body에 `system` 필드 분리** (버그 4B)
   ```python
   system_prompt = (
       "로봇 ID 언급 시 반드시 [ROBOT-XXXXX] 형식(대괄호+5자리 숫자)으로 표기하라. "
       "응답은 200자 이내, 점검 우선순위 위주로 답하라."
   )
   body = {
       "anthropic_version": "bedrock-2023-05-31",
       "max_tokens": 512,
       "system": system_prompt,
       "messages": [{"role": "user", "content": user_prompt}],
   }
   ```

3. **`/api/chat` Rate Limiting** (slowapi)
   ```python
   from slowapi import Limiter
   from slowapi.util import get_remote_address
   limiter = Limiter(key_func=get_remote_address)
   app.state.limiter = limiter

   @app.post("/api/chat")
   @limiter.limit("10/minute")
   async def chat(request: Request, req: ChatRequest):
       ...
   ```
   - 기존 `/api/predict` (있으면)에도 동일 limit 유지 (이미 적용된 경우 변경 없음).

4. **응답 JSON에 `links[]` 필드** (Task 4.3 딥링크)
   - Bedrock 답변 텍스트에서 `[ROBOT-XXXXX]` 패턴을 정규식으로 추출
   - 각 매칭에 대해 `{"label": "ROBOT-00123 차트", "url": "/?robot_id=ROBOT-00123"}` 형태로 list 생성
   - `return {"answer": text, "cached_at": ..., "data_date": ..., "links": links}`

5. **`GET /api/status`** (버그 1A) — 즉시 반환:
   ```python
   @app.get("/api/status")
   async def status():
       return {
           "data_date": _data_date,
           "cached_at": _cache_updated_at,
           "cache_ready": _cache_ready,
       }
   ```

6. **`_data_date` 전역변수 추가** (버그 1B) — `refresh_cache` 안에서 yesterday `dt = (date.today() - timedelta(days=1)).isoformat()` 같은 값을 저장. `/api/chat`/`/api/status` 응답에 포함.

7. **APScheduler timezone="Asia/Seoul"** (버그 2A)
   ```python
   scheduler.add_job(refresh_cache, "cron", hour=hour, minute=0, timezone="Asia/Seoul")
   ```

8. **`GET /` portal.html 서빙 + `?robot_id=` 파라미터** (버그 3B + Task 4.3 GET /)
   ```python
   @app.get("/", response_class=HTMLResponse)
   async def portal(request: Request, robot_id: str = ""):
       return templates.TemplateResponse("portal.html", {"request": request, "robot_id": robot_id})
   ```
   - 기존 `chat.html` 서빙 라우트가 있다면 `/legacy/chat` 같은 경로로 옮기거나 삭제 (단, **chat.html 파일 자체는 삭제하지 말 것** — 회귀 시 폴백).

### B) `src/api/templates/portal.html` 신규 작성

UI_GUIDE Dark Mode 원칙 (있을 경우) 준수. 단순 반응형 레이아웃:

- **레이아웃**: 12-column grid. CSS Grid 또는 Flexbox.
  - 좌측 8 col: `<iframe id="grafana-frame" src="${GRAFANA_URL}/d/robot-fleet-001?kiosk=tv&orgId=1">` (GRAFANA_URL은 Jinja 변수 또는 ConfigMap env 주입)
  - 우측 4 col: AI Chat 패널
- **상단 헤더**: `"YYYY-MM-DD 기준 데이터 · HH:MM 갱신"` 표시 — 페이지 로드 시 `fetch('/api/status')` → 즉시 표시.
- **대시보드 탭 전환 버튼**: Fleet / Anomaly / Pipeline 3개. 클릭 시 iframe `src` 교체 (uid: `robot-fleet-001`, `anomaly-timeline-001`, `pipeline-health-001`).
- **AI Chat 패널**:
  - 입력 form → `POST /api/chat`
  - 응답의 `answer`를 채팅 영역에 표시
  - 응답의 `links[]`를 버튼으로 렌더 (`min-height: 44px` Touch Target). 클릭 시 `grafana-frame.src`를 해당 URL로 교체.
- **딥링크 처리**: 페이지 로드 시 `URLSearchParams`로 `robot_id` 파싱 → 존재하면 채팅 입력란에 `"ROBOT-XXXXX의 현재 상태를 분석해줘"` 자동 입력 + 자동 전송.
- **XSS 방어** (버그 4A): `[ROBOT-XXXXX]` → `<button>` 변환 시 `DOMPurify.sanitize(html)` 필수. CDN: `<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>`.

### C) `requirements.txt` 보강

기존 파일에 다음 라이브러리 추가 (기존 라인 삭제 금지):

```
slowapi
```

### D) `k8s/api/deployment.yaml` ConfigMap 보강

기존 Deployment의 env 섹션에 추가 (기존 env 보존):

```yaml
- name: GRAFANA_URL
  valueFrom:
    configMapKeyRef:
      name: api-config
      key: grafana_url
```

ConfigMap 자체도 신규 작성 (deployment.yaml 또는 별도 `k8s/api/configmap.yaml`):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: api-config
  namespace: robot-telemetry
data:
  grafana_url: "https://k8s-monitoring-grafana-PLACEHOLDER.elb.amazonaws.com"
  # 실제 ALB DNS는 GitHub Actions post-deploy job이 SSM /robot-telemetry/grafana-url에 저장.
  # ConfigMap 값은 placeholder — kubectl patch로 갱신하거나 External Secrets/Kustomize overlay 사용.
```

### E) `k8s/api/hpa.yaml` minReplicas: 1 (버그 2B + 5)

`hpa.yaml` 파일이 존재하면 `minReplicas: 1`로 정정. 없으면 본 step에서는 생성하지 않음 (별도 step 책임).

## Acceptance Criteria

```bash
# 1) 컴파일 + 라이브러리
python3 -m py_compile src/api/main.py && echo "OK: py compile"
grep -q "^slowapi" requirements.txt && echo "OK: slowapi in requirements"

# 2) 모델 ID 변경
grep -q "claude-3-5-sonnet-20241022-v2:0" src/api/main.py && echo "OK: sonnet 3.5 default"
! grep -q 'claude-3-haiku-20240307' src/api/main.py && echo "OK: no haiku default"

# 3) Bedrock body 구조
grep -q '"system":' src/api/main.py && echo "OK: system field separated"

# 4) Rate limit
grep -qE 'limiter\.limit\("10/minute"\)|@limiter\.limit' src/api/main.py && echo "OK: rate limit on chat"

# 5) UX 버그 수정
grep -q '/api/status' src/api/main.py && echo "OK: status endpoint"
grep -q "_data_date" src/api/main.py && echo "OK: data_date global"
grep -q 'timezone="Asia/Seoul"' src/api/main.py && echo "OK: scheduler timezone"
grep -q "robot_id" src/api/main.py && echo "OK: robot_id route param"

# 6) Portal HTML
ls src/api/templates/portal.html
grep -q "grafana-frame\|<iframe" src/api/templates/portal.html && echo "OK: grafana iframe"
grep -q "DOMPurify\|purify" src/api/templates/portal.html && echo "OK: DOMPurify CDN"
grep -q "min-height: 44" src/api/templates/portal.html && echo "OK: touch target"
grep -qE "URLSearchParams|robot_id" src/api/templates/portal.html && echo "OK: deeplink JS"

# 7) Deployment ConfigMap
grep -q "GRAFANA_URL" k8s/api/deployment.yaml && echo "OK: GRAFANA_URL env"
grep -q "configMapKeyRef\|kind: ConfigMap" k8s/api/deployment.yaml || ls k8s/api/configmap.yaml && echo "OK: ConfigMap"
```

## 검증 절차

1. 위 AC 커맨드 모두 OK.
2. 아키텍처 체크리스트:
   - Bedrock 모델 기본값이 `anthropic.claude-3-5-sonnet-20241022-v2:0` 인가?
   - `system` 필드가 messages 배열 밖에 분리됐는가?
   - timezone이 `Asia/Seoul`로 명시됐는가?
   - portal.html이 Jinja 또는 ConfigMap env로 GRAFANA_URL을 받는가? (HTML 안 하드코딩 금지)
   - `chat.html` 파일은 그대로 보존됐는가? (회귀 fallback)
3. `phases/4-serving/index.json` step 5 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "main.py 보강(Sonnet 3.5 + system 필드 + slowapi + /api/status + GET / portal + timezone) + portal.html 신규 + ConfigMap GRAFANA_URL + UX 버그 6건 모두 fix"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

### 🚨 메타 파일 보호 (반드시 준수)

- **`/plan.md` 절대 수정/덮어쓰기/삭제 금지.** 본 step의 출력 산출물은 오직 `src/api/main.py`(보강), `src/api/templates/portal.html`(신규), `requirements.txt`(slowapi 추가만), `k8s/api/deployment.yaml`(env 추가만), `k8s/api/configmap.yaml`(있으면 신규), `k8s/api/hpa.yaml`(있으면 minReplicas 정정만), 그리고 `phases/4-serving/index.json`(step 5 entry만) 7종이다.
- 프로젝트 루트의 `*.md` 어떤 것도 수정하지 마라.
- 다른 step 디렉토리나 docs를 수정하지 마라.

### 구현 규칙

- **`src/api/templates/chat.html`을 삭제하지 마라.** 이유: 회귀 fallback 보존 + portal.html과 별도 라우트로 공존 가능.
- 실 Bedrock API를 호출해서 검증하려 하지 마라. 이유: 운영 계정에 모델 활성화 안 됨. **본 step의 검증은 모두 정적 grep + py_compile.** 실 API 호출은 step 6(api-tests)가 Mock으로 처리.
- `BEDROCK_MODEL_ID`를 코드에 직접 하드코딩하지 마라. 이유: env var override 가능해야 함. `os.environ.get("BEDROCK_MODEL_ID", "<default>")` 패턴 유지.
- `slowapi` rate limit을 in-process state로 두는 한계는 인지하고 진행하라. 이유: HPA replica >1 시 IP당 실제 한도가 replica 배수만큼 완화됨 — 본 step에서는 minReplicas:1 정책으로 우회 (별도 Redis 백엔드는 향후 별도 PR).
- `GRAFANA_URL`을 portal.html에 직접 하드코딩하지 마라. 이유: ALB DNS는 deploy time에 미정. ConfigMap 또는 SSM 런타임 조회로 주입.
