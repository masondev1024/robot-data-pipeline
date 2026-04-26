# Step 4: dag-fix

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (특히 ADR-003: Partition Projection)
- `/sql/bronze_ddl.sql` (파티션 키: year/month/day/hour)
- `/sql/silver_ddl.sql` (파티션 키: dt DATE)
- `/sql/gold_ddl.sql` (스키마: active_hours INT, dt DATE 파티션)
- `/dags/robot_daily_etl.py` (현재 DAG)
- `/phases/2-batch/index.json`

## 배경

Step 0(athena-ddl)에서 작성된 Bronze/Silver/Gold DDL과 현재 DAG 사이에 정합성 불일치가 있다. Step 0의 spec이 정합성의 source of truth이므로 **DAG를 DDL 스펙에 맞춰 정정**한다. 반대 방향(DDL을 DAG에 맞춰 변경)은 금지한다.

발견된 불일치 3건:

1. **Bronze WHERE 절 파티션 키 불일치**
   - `bronze_robot_telemetry` 파티션: `(year INT, month INT, day INT, hour INT)`
   - 현재 DAG (`_bronze_to_silver`, line 75): `WHERE dt = '{dt}'`
   - bronze 테이블에 `dt` 컬럼이 없어 Athena 쿼리 즉시 실패.

2. **Gold INSERT 컬럼 불일치**
   - `gold_robot_daily_stats` DDL 컬럼: `robot_id, avg_motor_temp, max_motor_temp, battery_start, battery_end, battery_drain, active_hours` (+ `dt` 파티션)
   - 현재 DAG (`_silver_to_gold`, line 91-106) INSERT 컬럼: `robot_id, avg_motor_temp, max_motor_temp, battery_start, battery_end, battery_drain, operation_ratio, battery_drain_rate, dt`
   - DDL에 없는 `operation_ratio`/`battery_drain_rate` 가 INSERT, DDL에 있는 `active_hours` 미산출 → 컬럼 매칭 실패.

3. **Bedrock 리포트 SELECT 컬럼 불일치**
   - `_bedrock_report` (line 117-123): `SELECT robot_id, avg_motor_temp, max_motor_temp, battery_drain_rate, operation_ratio FROM gold_robot_daily_stats`
   - Gold 테이블에 `battery_drain_rate`, `operation_ratio` 없음 → 쿼리 실패.

## 작업

### `dags/robot_daily_etl.py` 수정

#### 1. Bronze → Silver 쿼리 (`_bronze_to_silver`)

`WHERE dt = '{dt}'` 부분을 bronze 파티션 키(`year`, `month`, `day`)로 정정한다. 시그니처:

```python
def _bronze_to_silver(**ctx):
    execution_date = ctx["execution_date"]
    dt = execution_date.strftime("%Y-%m-%d")
    year, month, day = execution_date.year, execution_date.month, execution_date.day
    # 쿼리의 WHERE 절을:
    #   WHERE year = {year} AND month = {month} AND day = {day}
    # 그리고 SELECT 시 dt 파티션 컬럼 값은 '{dt}' 그대로 유지.
```

`hour` 파티션은 일 단위 ETL이므로 WHERE 절에 포함하지 않는다(하루치 모든 시간 데이터를 조회해야 함).

#### 2. Silver → Gold 쿼리 (`_silver_to_gold`)

INSERT 컬럼을 Gold DDL 스키마에 맞춘다:

```sql
INSERT INTO gold_robot_daily_stats
SELECT
    robot_id,
    AVG(motor_temp)                          AS avg_motor_temp,
    MAX(motor_temp)                          AS max_motor_temp,
    MAX(battery_level)                       AS battery_start,
    MIN(battery_level)                       AS battery_end,
    MAX(battery_level) - MIN(battery_level)  AS battery_drain,
    CAST(COUNT(DISTINCT date_trunc('hour', from_iso8601_timestamp(timestamp))) AS INTEGER)  AS active_hours,
    DATE '{dt}'                              AS dt
FROM silver_robot_telemetry
WHERE dt = DATE '{dt}'
GROUP BY robot_id
```

`active_hours`는 "그 날 데이터가 한 건 이상 발생한 distinct 시간 수"로 계산. timestamp 컬럼은 STRING 이므로 `from_iso8601_timestamp`로 변환 후 시간 단위 truncate.

#### 3. Bedrock 리포트 쿼리 (`_bedrock_report`)

SELECT 컬럼 및 표시 문자열을 Gold 스키마에 맞춘다:

```sql
SELECT robot_id, avg_motor_temp, max_motor_temp, battery_drain, active_hours
FROM gold_robot_daily_stats
WHERE dt = DATE '{dt}'
ORDER BY avg_motor_temp DESC
LIMIT 20
```

프롬프트 데이터 요약 라인도 새 컬럼명 기준으로 변경:

```python
data_summary = "\n".join(
    f"{r['robot_id']}: 평균온도={r['avg_motor_temp']}°C, 최고온도={r['max_motor_temp']}°C, "
    f"배터리소모={r['battery_drain']}, 가동시간={r['active_hours']}h"
    for r in rows
)
```

## Acceptance Criteria

```bash
# 1. WHERE 절 정합성
grep -q "WHERE year = " dags/robot_daily_etl.py && echo "OK: bronze WHERE uses partition keys"
! grep -q "FROM bronze_robot_telemetry" dags/robot_daily_etl.py | grep "WHERE dt" && echo "OK: no dt filter on bronze"

# 2. Gold INSERT 컬럼이 DDL 스키마와 일치
grep -q "AS active_hours" dags/robot_daily_etl.py && echo "OK: active_hours produced"
! grep -q "AS operation_ratio" dags/robot_daily_etl.py && echo "OK: operation_ratio removed"
! grep -q "AS battery_drain_rate" dags/robot_daily_etl.py && echo "OK: battery_drain_rate removed"

# 3. Bedrock SELECT 컬럼이 Gold DDL 컬럼만 사용
! grep -E "SELECT.*battery_drain_rate|SELECT.*operation_ratio" dags/robot_daily_etl.py && echo "OK: bedrock SELECT clean"

# 4. Python 문법 OK
python3 -c "import ast; ast.parse(open('dags/robot_daily_etl.py').read())" && echo "OK: python syntax"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - bronze WHERE 절이 `year/month/day` 파티션 키를 사용하는가? (Partition Projection 비용 절감 효과 유지)
   - gold INSERT 컬럼 순서·이름·개수가 `sql/gold_ddl.sql`과 정확히 일치하는가?
   - bedrock SELECT 컬럼이 모두 gold DDL에 존재하는가?
   - 멱등성: 재실행 시에도 동일 파티션을 덮어쓰는 의미가 보존되는가? (현재 `INSERT INTO`는 중복 누적 위험 — 별도 이슈로 추적, 본 step 범위 외)
3. `phases/2-batch/index.json` step 4 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "DAG ↔ DDL 정합성 정정 (bronze WHERE 파티션 키, gold active_hours, bedrock SELECT)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- `sql/bronze_ddl.sql`, `sql/silver_ddl.sql`, `sql/gold_ddl.sql`을 수정하지 마라. 이유: step 0이 정합성의 source of truth이며, 본 step은 DAG 측을 DDL에 맞춘다.
- `operation_ratio`/`battery_drain_rate` 컬럼을 DDL에 추가하지 마라. 이유: plan.md Task 2.3 spec은 `active_hours`를 명시했고, ML 학습용 feature(operation_ratio 등)는 Phase 5의 책임이다.
- `INSERT INTO`를 `INSERT OVERWRITE`로 변경하지 마라. 이유: 멱등성 개선은 별도 step에서 다룬다 (검증 절차 §2 마지막 항목 참고). 본 step의 범위는 컬럼/파티션 키 불일치 정정에 한정한다.
- `hour` 파티션을 WHERE 절에 추가하지 마라. 이유: 일 단위 ETL은 24시간 전체를 조회해야 하며, hour 필터를 걸면 일부 데이터가 누락된다.
