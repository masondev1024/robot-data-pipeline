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

RUN groupadd --gid 10001 prism \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/prism prism \
    && mkdir -p /app/data /app/.streamlit \
    && chown -R 10001:10001 /app

# PRISM core: apps + src + assets + data
COPY --chown=10001:10001 apps /app/apps
COPY --chown=10001:10001 src /app/src
COPY --chown=10001:10001 assets /app/assets
COPY --chown=10001:10001 data /app/data
COPY --chown=10001:10001 .streamlit /app/.streamlit
COPY --chown=10001:10001 prism/streamlit-public-config.toml /tmp/streamlit-public-config.toml

ARG PUBLIC_STREAMLIT_CONFIG=false
RUN if [ "$PUBLIC_STREAMLIT_CONFIG" = true ]; then \
        cp /tmp/streamlit-public-config.toml /app/.streamlit/config.toml; \
    fi

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
