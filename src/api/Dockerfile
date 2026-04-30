FROM python:3.11-slim

WORKDIR /app

# build context = 프로젝트 루트. src.common 모듈을 함께 포함해야
# main.py 의 `from src.common.*` import 가 해소됨.
COPY src/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/__init__.py src/__init__.py
COPY src/common/ src/common/
COPY src/api/ src/api/

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
