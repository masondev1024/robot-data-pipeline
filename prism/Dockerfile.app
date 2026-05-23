# PRISM Streamlit 운영 콘솔 컨테이너.
# build context = repo root (docker-compose 에서 ../ 로 지정).

FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 — dowhy 가 graphviz 헤더 필요시 대비
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY prism/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# PRISM core: apps + src + assets + data
COPY apps /app/apps
COPY src /app/src
COPY assets /app/assets
COPY data /app/data
COPY .streamlit /app/.streamlit

ENV PYTHONHASHSEED=2026 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PRISM_MODE=demo

EXPOSE 8502

CMD ["streamlit", "run", "apps/prism_demo.py", \
     "--server.port=8502", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
