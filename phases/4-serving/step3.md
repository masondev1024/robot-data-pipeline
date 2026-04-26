# Step 3: alert-handler-deeplink (Lambda 메시지 포맷 + SSM 런타임 조회)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-007: SNS → Slack)
- `/src/lambda/alert_handler.py` (step 0 산출물 — 보강 대상)
- `/terraform/modules/data_pipeline/lambda.tf` (step 0 산출물 — IAM 정책 위치)
- `/terraform/modules/data_pipeline/iam.tf` (Lambda IRSA Role/Policy 패턴 참조)
- `/terraform/modules/data_pipeline/ssm.tf` (`/robot-telemetry/portal-url` 정의)
- `/plan.md` Task 4.1 (메시지 포맷 + SSM 명세) — **읽기만, 수정 금지**

## 작업

### A) `src/lambda/alert_handler.py` 보강 (덮어쓰기)

**기존 기본 메시지 포맷에 다음을 추가:**

1. **portal_url SSM 런타임 조회** — cold start 시 1회만 boto3 SSM 호출 후 모듈 전역에 캐시. 매 invoke마다 재조회 금지 (Lambda 호출당 ~50ms 추가 비용 + SSM throttling 위험).
   ```python
   _portal_url: str | None = None  # 모듈 전역 캐시

   def _get_portal_url() -> str:
       global _portal_url
       if _portal_url is None:
           ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
           _portal_url = ssm.get_parameter(Name="/robot-telemetry/portal-url")["Parameter"]["Value"]
       return _portal_url
   ```

2. **메시지 포맷 (딥링크 포함)** — Slack 메시지 템플릿:
   ```
   [⚠️ 이상 감지] robot_id: {robot_id} | motor_temp: {temp}°C | 감지: {timestamp}
   🔗 포털: {portal_url}/?robot_id={robot_id}
   ```
   - `portal_url`은 위 `_get_portal_url()` 호출 결과
   - `robot_id`는 KDS 페이로드의 `robot_id` 필드 그대로 (Generator가 이미 `ROBOT-{i:05d}` 패딩으로 생성하므로 URL-safe 보장)
   - `temp`는 페이로드의 `max_motor_temp` 또는 `motor_temp` 중 존재하는 키 우선 (Flink window 결과 vs raw record 둘 다 핸들)
   - `timestamp`는 `window_end` 또는 raw `timestamp` 중 존재하는 키 우선

3. **에러 처리** — SSM 조회 실패 시 (콜드스타트 race condition 등): `_portal_url = ""` 또는 placeholder로 두고 메시지에 `🔗 포털 URL 조회 실패` 표기. Lambda 실패로 떨어뜨리지 말 것 (SNS publish는 성공해야 운영자 알림 도달).

### B) `terraform/modules/data_pipeline/iam.tf` Lambda IRSA에 SSM 권한 추가

기존 Lambda IAM Policy(또는 Role)에 다음 statement **추가** (기존 statement 삭제 금지):

```hcl
{
  Effect   = "Allow"
  Action   = ["ssm:GetParameter"]
  Resource = ["arn:aws:ssm:${var.aws_region}:*:parameter/robot-telemetry/portal-url"]
}
```

기존 Lambda IAM 위치 (kinesis:GetRecords + sns:Publish 등이 있는 곳)을 찾아 그 정책 안에 추가하라. **별도 Role/Policy를 새로 만들지 말 것** — 기존 Lambda Role 하나에 통합.

## Acceptance Criteria

```bash
# 1) Python 컴파일
python3 -m py_compile src/lambda/alert_handler.py && echo "OK: py compile"

# 2) 메시지 포맷 검증
grep -q "이상 감지\|⚠️" src/lambda/alert_handler.py && echo "OK: message header"
grep -q "포털\|portal" src/lambda/alert_handler.py && echo "OK: portal link"
grep -q "robot_id={" src/lambda/alert_handler.py && echo "OK: deep link query"

# 3) SSM 조회 패턴
grep -q "/robot-telemetry/portal-url" src/lambda/alert_handler.py && echo "OK: SSM path"
grep -q "ssm" src/lambda/alert_handler.py && echo "OK: ssm client"

# 4) 모듈 전역 캐시 (cold start 1회 패턴)
grep -qE "_portal_url|@lru_cache|module-level cache" src/lambda/alert_handler.py && echo "OK: cold start cache"

# 5) IAM 권한
grep -q "ssm:GetParameter" terraform/modules/data_pipeline/iam.tf && echo "OK: SSM IAM"
grep -q "robot-telemetry/portal-url" terraform/modules/data_pipeline/iam.tf && echo "OK: SSM ARN"
terraform fmt -check terraform/modules/data_pipeline/iam.tf && echo "OK: tf fmt"
```

## 검증 절차

1. 위 AC 커맨드 모두 OK 확인.
2. 아키텍처 체크리스트:
   - portal_url이 환경변수 / 하드코딩 아닌 SSM 런타임 조회인가?
   - cold start 1회만 SSM 호출 (모듈 전역 캐시 패턴) 인가?
   - 메시지 포맷이 plan.md Task 4.1 명세와 일치하는가?
   - IAM resource ARN이 `/robot-telemetry/portal-url` 단일 파라미터로 한정됐는가? (`*` 와일드카드 금지)
3. `phases/4-serving/index.json` step 3 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "alert_handler.py 보강(SSM portal_url 런타임 조회 + 딥링크 메시지) + iam.tf SSM 권한 추가"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

### 🚨 메타 파일 보호 (반드시 준수)

- **`/plan.md`(프로젝트 루트의 master plan)을 절대 수정/덮어쓰기/삭제하지 마라.** 본 step의 출력 산출물은 오직 `src/lambda/alert_handler.py`(덮어쓰기), `terraform/modules/data_pipeline/iam.tf`(SSM statement 추가), 그리고 `phases/4-serving/index.json`(step 3 entry만) 3종이다.
- 프로젝트 루트의 `*.md`(plan.md, README.md, CLAUDE.md 등) 어떤 것도 수정하지 마라.
- 다른 step 디렉토리나 docs(`/docs/*.md`)를 수정하지 마라.
- `lambda.tf`, `sns.tf`(step 0 산출물)을 수정하지 마라 — 본 step은 코드+IAM만.

### 구현 규칙

- portal_url을 환경변수(`os.environ`)에서 읽지 마라. 이유: ALB DNS는 terraform apply 후에야 확정되므로 deploy time env-var는 PENDING 상태. 반드시 SSM 런타임 조회.
- 매 invoke마다 SSM 호출하지 마라. 이유: cold start는 분당 수회 수준이지만 invoke는 alert 발생 시 초당 수십~수백 건 가능. SSM API 호출당 비용 + throttle 한도 위험.
- IAM resource를 `arn:aws:ssm:*:*:parameter/*` 와일드카드로 두지 마라. 이유: 최소 권한 원칙. `/robot-telemetry/portal-url` 단일 파라미터로 한정.
- SSM 조회 실패를 raise로 처리하지 마라. 이유: 알림 자체는 도달해야 함 (operator가 portal URL 없이도 motor_temp 정보로 대응 가능). placeholder 또는 빈 문자열로 fallback.
