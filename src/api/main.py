import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.common.athena import run_query
from src.common.aws import get_client
from src.common.bedrock import invoke_claude

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Robot Telemetry AI Query API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

_gold_cache: str = ""
_cache_updated_at: str = ""
_data_date: str = ""
_cache_ready: bool = False
_grafana_url: str | None = None


def _get_grafana_url() -> str:
    """Late-binding: post-deploy.yml이 ALB DNS를 SSM에 저장한 뒤 첫 호출 시 1회 조회 + 모듈 캐시.
    SSM 값이 trailing slash 보유 시 portal.html 이 `${grafanaUrl}/d/...` 로 합쳐 `//d/...` (404)
    를 만드는 것을 방지하기 위해 rstrip('/') 적용 — single source of truth 로 정리."""
    global _grafana_url
    if _grafana_url is None:
        try:
            value = get_client("ssm").get_parameter(
                Name="/robot-telemetry/grafana-url"
            )["Parameter"]["Value"]
        except Exception as e:
            print(f"SSM get_parameter /robot-telemetry/grafana-url failed: {str(e)}")
            value = os.environ.get("GRAFANA_URL", "http://localhost:3000")
        _grafana_url = value.rstrip("/")
    return _grafana_url


async def refresh_cache():
    """Athena Gold 테이블 최신 파티션 조회 → _gold_cache 갱신."""
    global _gold_cache, _cache_updated_at, _data_date

    database = os.environ.get("ATHENA_DATABASE", "robot_telemetry_db")
    workgroup = os.environ.get("ATHENA_WORKGROUP", "robot-telemetry-workgroup")
    output_location = os.environ.get(
        "ATHENA_OUTPUT_LOCATION",
        "s3://de-ai-06-smartfactory-bucket/project-athena-results/",
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
            lambda: run_query(
                query,
                database=database,
                workgroup=workgroup,
                output_location=output_location,
            ),
        )
        if rows:
            header = ",".join(rows[0].keys())
            data_lines = "\n".join(",".join(r.values()) for r in rows)
            _gold_cache = f"{header}\n{data_lines}"
        else:
            _gold_cache = "(데이터 없음)"
        _cache_updated_at = datetime.now(timezone.utc).isoformat()
        _data_date = yesterday
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
    scheduler.add_job(refresh_cache, "cron", hour=hour, minute=0, timezone="Asia/Seoul")
    scheduler.start()


@app.get("/healthz")
async def healthz():
    if not _cache_ready:
        raise HTTPException(status_code=503, detail="cache not ready")
    return {"status": "ok", "cached_at": _cache_updated_at}


@app.get("/api/status")
async def status():
    return {
        "data_date": _data_date,
        "cached_at": _cache_updated_at,
        "cache_ready": _cache_ready,
    }


class ChatRequest(BaseModel):
    question: str


@app.post("/api/chat")
@limiter.limit("10/minute")
async def chat(request: Request, req: ChatRequest):
    if not _gold_cache:
        raise HTTPException(status_code=503, detail="캐시가 아직 준비되지 않았습니다.")

    system_prompt = (
        "로봇 ID 언급 시 반드시 [ROBOT-XXXXX] 형식(대괄호+5자리 숫자)으로 표기하라. "
        "응답은 200자 이내, 점검 우선순위 위주로 답하라."
    )
    user_prompt = f"다음은 공장 로봇 상태 데이터야:\n{_gold_cache}\n\n질문: {req.question}"

    loop = asyncio.get_event_loop()
    try:
        response_text = await loop.run_in_executor(
            None,
            lambda: invoke_claude(user_prompt, system=system_prompt),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bedrock 호출 실패: {exc}")

    links = []
    robot_id_pattern = r"\[ROBOT-(\d{5})\]"
    for match in re.finditer(robot_id_pattern, response_text):
        robot_id = f"ROBOT-{match.group(1)}"
        links.append({
            "label": f"{robot_id} 차트",
            "url": f"/?robot_id={robot_id}"
        })

    return {
        "answer": response_text,
        "cached_at": _cache_updated_at,
        "data_date": _data_date,
        "links": links
    }


sagemaker_runtime = get_client("sagemaker-runtime")
ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "robot-failure-predictor")


class PredictRequest(BaseModel):
    robot_id: str
    avg_motor_temp: float
    max_motor_temp: float
    battery_drain: int
    active_hours: int
    max_temp_load_ratio: float


@app.post("/api/predict")
@limiter.limit("20/minute")
async def predict_failure(request: Request, body: PredictRequest):
    features = f"{body.avg_motor_temp},{body.max_motor_temp},{body.battery_drain},{body.active_hours},{body.max_temp_load_ratio}"
    loop = asyncio.get_event_loop()
    try:
        response = await loop.run_in_executor(
            None,
            lambda: sagemaker_runtime.invoke_endpoint(
                EndpointName=ENDPOINT_NAME,
                ContentType="text/csv",
                Body=features,
            ),
        )
        # SageMaker XGBoost 1.7 응답 형식: text/csv → "0.0319" / application/json → "[0.0319]"
        # 두 형식 모두 안전 파싱.
        raw = response["Body"].read().decode().strip()
        failure_prob = float(json.loads(raw)[0]) if raw.startswith("[") else float(raw)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SageMaker 호출 실패: {exc}")
    return {
        "robot_id": body.robot_id,
        "failure_probability": round(failure_prob, 4),
        "risk_level": "high" if failure_prob > 0.7 else "medium" if failure_prob > 0.4 else "low",
    }


@app.get("/", response_class=HTMLResponse)
async def portal(request: Request, robot_id: str = ""):
    return templates.TemplateResponse(
        request,
        "portal.html",
        {
            "robot_id": robot_id,
            "GRAFANA_URL": _get_grafana_url(),
        },
    )
