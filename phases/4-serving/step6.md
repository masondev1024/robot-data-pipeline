# Step 6: api-tests (FastAPI 통합 검증 — Mock Bedrock/Athena)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/src/api/main.py` (step 5 산출물 — 검증 대상)
- `/src/lambda/alert_handler.py` (step 3 산출물 — 별도 Lambda 테스트 포함)
- `/tests/conftest.py` (sys.path 패턴)
- `/tests/etl/test_bedrock_report.py` (Mock 패턴 참조 — Athena/Bedrock/S3 boto3.client side_effect 라우팅)
- `/plan.md` Task 4.4 — **읽기만, 수정 금지**

## 작업

`tests/api/` 신규 작성. **모든 boto3 호출은 Mock**. 실 API 호출 0건.

### 산출물 4종

1. `tests/api/__init__.py` (빈 파일)
2. `tests/api/test_chat.py` — `POST /api/chat` 동작 검증
3. `tests/api/test_status.py` — `GET /api/status` + 캐시 갱신 로직 검증
4. `tests/lambda/__init__.py` + `tests/lambda/test_alert_handler.py` — Lambda alert 핸들러 검증 (SSM 캐시 + 메시지 포맷)

### `tests/api/test_chat.py` 케이스 (최소 6건)

`from fastapi.testclient import TestClient` + `from src.api.main import app`로 시작.

| # | 케이스 | 검증 |
|---|---|---|
| 1 | `POST /api/chat` 정상 응답 | mock Bedrock 응답 → 200 + `answer`/`cached_at`/`data_date`/`links` 키 모두 존재 |
| 2 | Bedrock invoke_model 호출 파라미터 | `modelId="anthropic.claude-3-5-sonnet-20241022-v2:0"`, body에 `"system":` 키 + `messages[0].role=="user"` + `max_tokens==512` |
| 3 | `links[]` 추출 | mock 응답 `"점검 시급: [ROBOT-00123], [ROBOT-00456]"` → `links` 길이 2 + 각 url이 `/?robot_id=ROBOT-XXXXX` 형태 |
| 4 | 캐시 미준비 시 503 | `_cache_ready=False` 상태에서 → 503 |
| 5 | Rate Limit (slowapi) | 10회 요청 후 11번째 → 429 |
| 6 | system 필드 검증 | mock invoke 호출 인자의 body JSON에 `"system"` 키 존재 (버그 4B) |

### `tests/api/test_status.py` 케이스 (최소 4건)

| # | 케이스 | 검증 |
|---|---|---|
| 1 | `GET /api/status` 즉시 반환 | mock 캐시 상태 주입 → 200 + `data_date`/`cached_at`/`cache_ready` 키 |
| 2 | data_date 포맷 | yesterday ISO 형식 (예: `"2026-04-26"`) |
| 3 | timezone 검증 | `refresh_cache` 호출 시 APScheduler add_job 인자에 `timezone="Asia/Seoul"` (assert via inspect 또는 mock 캡처) |
| 4 | cache_ready false 시 데이터 비어도 응답은 200 | (status 자체는 항상 응답해야 함, chat과 다름) |

### `tests/lambda/test_alert_handler.py` 케이스 (최소 5건)

| # | 케이스 | 검증 |
|---|---|---|
| 1 | SSM portal_url 1회만 조회 (cold start 캐시) | mock SSM client → handler를 같은 프로세스에서 N회 호출 후 `get_parameter.call_count == 1` |
| 2 | 메시지 포맷 — 헤더 | `[⚠️ 이상 감지]` 또는 `이상 감지` 문자열 포함 |
| 3 | 메시지 포맷 — 딥링크 | `포털:` + `/?robot_id=ROBOT-` 패턴 포함 |
| 4 | window_end 우선, 없으면 timestamp fallback | 두 케이스 모두 메시지에 timestamp 들어감 |
| 5 | SSM 조회 실패 시 SNS publish는 성공 | SSM raise → 메시지에 `포털 URL 조회 실패` 또는 빈 URL → 그래도 SNS publish 호출됨 |

### Mock 패턴

`unittest.mock.patch("src.api.main.boto3.client")` 같은 위치 지정 패턴 사용. service별 분기:

```python
def make_boto_mock():
    athena_mock = MagicMock()
    bedrock_mock = MagicMock()
    bedrock_mock.invoke_model.return_value = {
        "body": MagicMock(read=lambda: json.dumps({"content": [{"text": "정비 시급: [ROBOT-00123]"}]}).encode())
    }
    def router(service, **kw):
        return {"athena": athena_mock, "bedrock-runtime": bedrock_mock, "s3": MagicMock(), "ssm": MagicMock()}[service]
    return router
```

## Acceptance Criteria

```bash
# 0) 의존성 (slowapi가 step 5에서 추가됐어야 함)
python3 -c "import slowapi" && echo "OK: slowapi installed"

# 1) 디렉토리 구조
ls tests/api/__init__.py tests/api/test_chat.py tests/api/test_status.py
ls tests/lambda/__init__.py tests/lambda/test_alert_handler.py

# 2) 단위 테스트 통과 (실 API 호출 0건)
pytest tests/api/ tests/lambda/ -v --tb=short 2>&1 | tail -40
# 위 결과: 15+ tests PASSED 확인 (chat 6 + status 4 + lambda 5)

# 3) 실 boto3 호출 차단 검증 — 테스트 도중 어떤 외부 API 호출도 발생하지 않았는가?
# (테스트 대상 코드가 boto3.client 호출 시 mock으로 라우팅되므로 외부 호출 0건)
pytest tests/api/ tests/lambda/ -p no:cacheprovider 2>&1 | grep -c "PASSED" | xargs -I{} test {} -ge 15 && echo "OK: 15+ passed"

# 4) 회귀 — 기존 테스트도 전부 통과
pytest tests/ -v --tb=short 2>&1 | tail -5
```

## 검증 절차

1. 위 AC 커맨드 모두 OK.
2. 아키텍처 체크리스트:
   - 모든 boto3.client 호출이 mock 처리됐는가? (실 AWS 호출 0건)
   - chat 6 + status 4 + lambda 5 = **최소 15 케이스 PASSED**?
   - rate limit 케이스(429) 가 mock 환경에서도 동작하는가? (slowapi는 in-process counter라 OK)
   - SSM 1회 조회 캐시 패턴이 검증됐는가?
3. `phases/4-serving/index.json` step 6 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "tests/api/(chat 6 + status 4) + tests/lambda/(alert 5) = 15+ PASSED, 모든 boto3 mock"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

### 🚨 메타 파일 보호 (반드시 준수)

- **`/plan.md` 절대 수정/덮어쓰기/삭제 금지.** 본 step의 출력 산출물은 오직 `tests/api/__init__.py`, `tests/api/test_chat.py`, `tests/api/test_status.py`, `tests/lambda/__init__.py`, `tests/lambda/test_alert_handler.py`, 그리고 `phases/4-serving/index.json`(step 6 entry만) 6종이다.
- 프로젝트 루트의 `*.md` 어떤 것도 수정하지 마라.
- 다른 step 디렉토리나 docs를 수정하지 마라.
- `src/api/main.py`, `src/lambda/alert_handler.py`를 수정하지 마라 — 본 step은 **검증 전용**. 코드 결함 발견 시 step `blocked` 마킹.

### 구현 규칙

- 실 AWS API를 호출하지 마라. 이유: ① CI 비용/flaky ② Bedrock 모델 사용자 계정에 미활성화. 모든 boto3 client는 `unittest.mock.patch`로 mock.
- `LocalStack` / `moto` 같은 통합 mock 라이브러리를 추가하지 마라. 이유: 단위 테스트는 가벼워야 하고 의존성 최소화. `unittest.mock`만 사용.
- Bedrock 응답 형식을 임의로 추측하지 마라. 이유: 실제 Bedrock Messages API 응답은 `{"content": [{"text": "..."}]}` 구조. step 2의 `_bedrock_report` 또는 `tests/etl/test_bedrock_report.py` 패턴 그대로 따라라.
- 5분 안에 완료되지 않으면 mock 누수 의심. 이유: mock 처리된 코드는 즉시 반환. 시간 초과 시 patch 위치 오류 점검.
