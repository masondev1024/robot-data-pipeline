# Step 2: bedrock-report

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/PRD.md`
- `/sql/gold_ddl.sql`
- `/dags/robot_daily_etl.py`

## 작업

`dags/robot_daily_etl.py`의 `generate_bedrock_report` Task가 아직 없다면 추가하고, 이미 있다면 아래 명세와 일치하는지 검증·수정하라.

### `generate_bedrock_report` PythonOperator 명세 확인

아래 사항을 모두 만족해야 한다:

1. **Athena 조회**:
   - DB: `robot_telemetry_db`
   - Table: `gold_robot_daily_stats`
   - Workgroup: `robot-telemetry-workgroup`
   - Output: `s3://de-ai-06-827913617635-ap-northeast-2-an/project-athena-results/`

2. **Bedrock 호출**:
   - Model: `os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")`
   - 프롬프트: `"다음은 오늘({ds}) 공장 로봇들의 상태 지표야. [데이터] 이를 분석해서 가장 점검이 시급한 로봇 3대와 그 이유를 정비반장에게 보내는 형식으로 300자 이내로 요약해."`
   - `max_tokens = 512`

3. **S3 저장**:
   - 경로: `s3://de-ai-06-827913617635-ap-northeast-2-an/reports/{ds}.txt`

4. **의존성**: `silver_to_gold >> generate_bedrock_report`

## Acceptance Criteria

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from dags.robot_daily_etl import dag
ids = dag.task_ids
assert 'generate_bedrock_report' in ids, f'Task not found. IDs: {ids}'
t = dag.get_task('generate_bedrock_report')
assert any(u.task_id == 'silver_to_gold' for u in t.upstream_list), 'Wrong dependency'
print('OK. Full chain:', [t.task_id for t in dag.topological_sort()])
"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - Athena 조회 시 DB=`robot_telemetry_db`, Table=`gold_robot_daily_stats` 사용?
   - Workgroup=`robot-telemetry-workgroup` 사용?
   - Bedrock model이 환경변수로 관리되는가?
   - 리포트가 `reports/{ds}.txt` 경로에 저장되는가?
   - 의존성 체인 `bronze_to_silver >> silver_to_gold >> generate_bedrock_report` 완성?
3. `phases/3-realtime/index.json` step 2 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "DAG 전체 체인 완성: bronze_to_silver >> silver_to_gold >> generate_bedrock_report(Bedrock Haiku → S3 reports/)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- `gold_robot_stats`처럼 테이블명을 축약하지 마라. 이유: 확정값 `gold_robot_daily_stats`
- Slack 전송 코드를 추가하지 마라. 이유: Phase 4 Task 4.1에서 별도 처리
- `generate_bedrock_report`를 S3 리포트 저장 없이 로그만 출력하고 완료 처리하지 마라
