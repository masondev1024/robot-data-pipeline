FROM python:3.11-slim
WORKDIR /app

COPY src/generator/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/__init__.py /app/src/__init__.py
COPY src/generator/__init__.py /app/src/generator/__init__.py
COPY src/generator/app.py /app/src/generator/app.py
COPY src/generator/schema_validator.py /app/src/generator/schema_validator.py
COPY src/generator/backfill.py /app/src/generator/backfill.py

RUN mkdir /data

USER 65534
CMD ["python3", "-m", "src.generator.app"]
