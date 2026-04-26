#!/bin/bash
set -euo pipefail

# Flink Application Builder — anomaly_detection.zip 생성
# 의존성: bash, curl, zip, unzip

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

KINESIS_CONNECTOR_JAR="lib/flink-sql-connector-kinesis-1.18.1.jar"
# Primary: 1.18.1 (for FLINK-1_18), Fallback: 1.16.3 (available on Maven)
KINESIS_CONNECTOR_URL_PRIMARY="https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kinesis/1.18.1/flink-sql-connector-kinesis-1.18.1.jar"
KINESIS_CONNECTOR_URL_FALLBACK="https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kinesis/1.16.3/flink-sql-connector-kinesis-1.16.3.jar"
OUTPUT_ZIP="anomaly_detection.zip"

echo "=== Flink Application Builder ==="

# 1) lib 디렉토리 생성
if [ ! -d "lib" ]; then
    echo "[*] Creating lib/ directory..."
    mkdir -p lib
fi

# 2) Kinesis Connector JAR 다운로드 (없을 때만, idempotent)
if [ ! -f "$KINESIS_CONNECTOR_JAR" ]; then
    echo "[*] Downloading Kinesis Connector JAR..."
    if curl -fsSL -o "$KINESIS_CONNECTOR_JAR" "$KINESIS_CONNECTOR_URL_PRIMARY"; then
        echo "[OK] Downloaded (1.18.1): $KINESIS_CONNECTOR_JAR"
    else
        echo "[WARN] 1.18.1 not available, trying 1.16.3 fallback..."
        if curl -fsSL -o "$KINESIS_CONNECTOR_JAR" "$KINESIS_CONNECTOR_URL_FALLBACK"; then
            echo "[OK] Downloaded (1.16.3 fallback): $KINESIS_CONNECTOR_JAR"
        else
            echo "[ERROR] Failed to download Kinesis Connector JAR"
            exit 1
        fi
    fi
else
    echo "[OK] Kinesis Connector JAR already exists: $KINESIS_CONNECTOR_JAR"
fi

# 3) 기존 ZIP 제거 (재빌드 시)
if [ -f "$OUTPUT_ZIP" ]; then
    echo "[*] Removing old $OUTPUT_ZIP..."
    rm "$OUTPUT_ZIP"
fi

# 4) ZIP 생성 — anomaly_detection.py + requirements.txt + lib/
echo "[*] Building ZIP archive..."
zip -r "$OUTPUT_ZIP" \
    anomaly_detection.py \
    requirements.txt \
    lib/flink-sql-connector-kinesis-1.18.1.jar

# 5) 검증
ZIP_SIZE=$(ls -lh "$OUTPUT_ZIP" | awk '{print $5}')
echo "[OK] Built: $OUTPUT_ZIP ($ZIP_SIZE)"

# 6) ZIP 내용 검증
echo "[*] Verifying ZIP contents..."
unzip -l "$OUTPUT_ZIP" | grep -q "anomaly_detection.py" && echo "  [OK] anomaly_detection.py found"
unzip -l "$OUTPUT_ZIP" | grep -q "requirements.txt" && echo "  [OK] requirements.txt found"
unzip -l "$OUTPUT_ZIP" | grep -q "lib/flink-sql-connector-kinesis-1.18.1.jar" && echo "  [OK] Kinesis connector found"

echo ""
echo "=== Build Complete ==="
echo "Output: $OUTPUT_ZIP"
echo "Size: $ZIP_SIZE"
echo ""
echo "Next step: terraform apply (ensure flink/build.sh completed first)"
