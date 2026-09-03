"""Read migration counts from private RDS and write a redacted JSON evidence file."""

from __future__ import annotations

import json
import os
import sys

import boto3
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext


def _secret(secret_arn: str) -> dict[str, str]:
    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))
    value = client.get_secret_value(SecretId=secret_arn).get("SecretString")
    if not value:
        raise RuntimeError("migration secret has no SecretString")
    return json.loads(value)


def _quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> None:
    args = getResolvedOptions(
        sys.argv,
        ["JOB_NAME", "JDBC_URL", "SECRET_ARN", "BATCH_ID", "ATTEMPT_ID", "OUTPUT_PATH"],
    )
    sc = SparkContext.getOrCreate()
    glue_context = GlueContext(sc)
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)
    secret = _secret(args["SECRET_ARN"])
    batch_id = _quoted(args["BATCH_ID"])
    attempt_id = _quoted(args["ATTEMPT_ID"])
    query = f"""
      SELECT
        (SELECT COUNT(*) FROM robot_telemetry_migration_stg WHERE batch_id = {batch_id} AND attempt_id = {attempt_id}) AS staged_rows,
        (SELECT COUNT(*) FROM robot_telemetry WHERE event_id IN (
          SELECT event_id FROM robot_telemetry_migration_stg WHERE batch_id = {batch_id} AND attempt_id = {attempt_id}
        )) AS target_rows_for_batch,
        (SELECT COUNT(*) FROM robot_telemetry) AS target_total_rows,
        (SELECT COUNT(DISTINCT event_id) FROM robot_telemetry) AS target_distinct_event_ids,
        (SELECT source_rows FROM robot_telemetry_migration_audit WHERE batch_id = {batch_id} AND attempt_id = {attempt_id}) AS audit_source_rows,
        (SELECT accepted_rows FROM robot_telemetry_migration_audit WHERE batch_id = {batch_id} AND attempt_id = {attempt_id}) AS audit_accepted_rows,
        (SELECT rejected_rows FROM robot_telemetry_migration_audit WHERE batch_id = {batch_id} AND attempt_id = {attempt_id}) AS audit_rejected_rows,
        (SELECT status FROM robot_telemetry_migration_audit WHERE batch_id = {batch_id} AND attempt_id = {attempt_id}) AS audit_status,
        (SELECT merged_rows FROM robot_telemetry_migration_audit WHERE batch_id = {batch_id} AND attempt_id = {attempt_id}) AS merged_rows
    """
    result = (
        glue_context.spark_session.read.format("jdbc")
        .options(
            url=args["JDBC_URL"],
            user=secret["username"],
            password=secret["password"],
            driver="com.mysql.cj.jdbc.Driver",
            dbtable=f"({query}) AS migration_verification",
        )
        .load()
        .first()
    )
    payload = {
        "batch_id": args["BATCH_ID"],
        "attempt_id": args["ATTEMPT_ID"],
        "region": os.getenv("AWS_REGION", "ap-northeast-2"),
        "counts": result.asDict() if result else {},
    }
    bucket, _, key = args["OUTPUT_PATH"][5:].partition("/")
    boto3.client("s3", region_name=os.getenv("AWS_REGION", "ap-northeast-2")).put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    job.commit()


if __name__ == "__main__":
    main()
