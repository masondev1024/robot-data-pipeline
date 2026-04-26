import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone

import boto3
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Robot Telemetry AI Query API")

_gold_cache: str = ""
_cache_updated_at: str = ""
_cache_ready: bool = False


def _run_athena_query(query: str, database: str, workgroup: str, output_location: str) -> list[dict]:
    """Synchronous Athena query execution. Returns list of row dicts."""
    client = boto3.client("athena", region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-2"))

    response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": database},
        WorkGroup=workgroup,
        ResultConfiguration={"OutputLocation": output_location},
    )
    execution_id = response["QueryExecutionId"]

    for _ in range(60):
        result = client.get_query_execution(QueryExecutionId=execution_id)
        state = result["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = result["QueryExecution"]["Status"].get("StateChangeReason", "unknown")
            raise RuntimeError(f"Athena query {state}: {reason}")
        time.sleep(2)
    else:
        raise TimeoutError("Athena query timed out after 120 seconds")

    paginator = client.get_paginator("get_query_results")
    rows = []
    columns = None
    for page in paginator.paginate(QueryExecutionId=execution_id):
        result_rows = page["ResultSet"]["Rows"]
        if columns is None:
            columns = [col["VarCharValue"] for col in result_rows[0]["Data"]]
            result_rows = result_rows[1:]
        for row in result_rows:
            values = [cell.get("VarCharValue", "") for cell in row["Data"]]
            rows.append(dict(zip(columns, values)))
    return rows


async def refresh_cache():
    """Athena Gold 테이블 최신 파티션 조회 → _gold_cache 갱신."""
    global _gold_cache, _cache_updated_at

    database = os.environ.get("ATHENA_DATABASE", "robot_telemetry_db")
    workgroup = os.environ.get("ATHENA_WORKGROUP", "robot-telemetry-workgroup")
    output_location = os.environ.get(
        "ATHENA_OUTPUT_LOCATION",
        "s3://de-ai-06-827913617635-ap-northeast-2-an/project-athena-results/",
    )

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    query = f"""
SELECT robot_id, avg_motor_temp, max_motor_temp,
       battery_start, battery_end, battery_drain, active_hours, dt
FROM gold_robot_daily_stats
WHERE dt = DATE '{yesterday}'
ORDER BY avg_motor_temp DESC
LIMIT 100
"""

    loop = asyncio.get_event_loop()
    try:
        rows = await loop.run_in_executor(
            None,
            lambda: _run_athena_query(query, database, workgroup, output_location),
        )
        if rows:
            header = ",".join(rows[0].keys())
            data_lines = "\n".join(",".join(r.values()) for r in rows)
            _gold_cache = f"{header}\n{data_lines}"
        else:
            _gold_cache = "(데이터 없음)"
        _cache_updated_at = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        print(f"[refresh_cache] 실패: {exc}")
        if not _gold_cache:
            _gold_cache = ""
    else:
        global _cache_ready
        _cache_ready = True


@app.on_event("startup")
async def startup():
    for attempt in range(3):
        await refresh_cache()
        if _cache_ready:
            break
        if attempt < 2:
            await asyncio.sleep(10)
    scheduler = AsyncIOScheduler()
    hour = int(os.environ.get("CACHE_REFRESH_HOUR", "1"))
    scheduler.add_job(refresh_cache, "cron", hour=hour, minute=0)
    scheduler.start()


@app.get("/healthz")
async def healthz():
    if not _cache_ready:
        raise HTTPException(status_code=503, detail="cache not ready")
    return {"status": "ok", "cached_at": _cache_updated_at}


class ChatRequest(BaseModel):
    question: str


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not _gold_cache:
        raise HTTPException(status_code=503, detail="캐시가 아직 준비되지 않았습니다.")

    model_id = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
    prompt = f"다음은 공장 로봇 상태 데이터야:\n{_gold_cache}\n\n질문: {req.question}"

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": prompt}],
    })

    loop = asyncio.get_event_loop()
    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-2"),
    )

    try:
        response = await loop.run_in_executor(
            None,
            lambda: bedrock.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=body,
            ),
        )
        response_body = json.loads(response["body"].read())
        response_text = response_body["content"][0]["text"]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bedrock 호출 실패: {exc}")

    return {"answer": response_text, "cached_at": _cache_updated_at}


@app.get("/", response_class=HTMLResponse)
async def index():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "chat.html")
    with open(template_path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())
