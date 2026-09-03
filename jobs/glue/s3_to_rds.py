"""AWS Glue 5 Spark job: Bronze Parquet on S3 -> private RDS staging.

This file is intentionally an executable Glue entrypoint.  The pure contract module
is supplied through ``--extra-py-files`` so local tests do not need Glue or Spark.
The job fails closed when the batch contains invalid rows; this prevents a partial
promotion from being mistaken for a successful migration.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import LongType, StringType, StructField, StructType, TimestampType

from s3_to_rds_contract import REQUIRED_FIELDS


LOGGER = logging.getLogger("s3-to-rds")
LOGGER.setLevel(logging.INFO)


def _arguments() -> dict[str, str]:
    return getResolvedOptions(
        sys.argv,
        [
            "JOB_NAME",
            "SOURCE_PATH",
            "JDBC_URL",
            "SECRET_ARN",
            "BATCH_ID",
            "ATTEMPT_ID",
            "REJECT_PATH",
            "STAGING_TABLE",
            "AUDIT_TABLE",
        ],
    )


def _secret(secret_arn: str) -> dict[str, str]:
    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))
    response = client.get_secret_value(SecretId=secret_arn)
    value = response.get("SecretString")
    if not value:
        raise RuntimeError("migration secret has no SecretString")
    payload = json.loads(value)
    for key in ("username", "password"):
        if not payload.get(key):
            raise RuntimeError(f"migration secret is missing {key}")
    return payload


def _validate_columns(source: DataFrame) -> None:
    missing = sorted(set(REQUIRED_FIELDS) - set(source.columns))
    if missing:
        raise RuntimeError(f"source schema is missing required columns: {missing}")


def _prepare(source: DataFrame, batch_id: str, attempt_id: str) -> tuple[DataFrame, DataFrame]:
    """Return valid and rejected frames using distributed Spark expressions."""

    _validate_columns(source)
    typed = source.select(
        *[F.col(field) for field in REQUIRED_FIELDS],
        F.to_timestamp("timestamp").alias("event_time"),
    )
    for field in ("pos_x", "pos_y", "battery_level", "current_load", "motor_temp"):
        typed = typed.withColumn(field, F.col(field).cast("double"))

    reason = F.when(F.col("robot_id").isNull() | (F.length(F.trim("robot_id")) == 0), F.lit("MISSING_ROBOT_ID"))
    for field, (lower, upper) in {
        "pos_x": (-1_000_000.0, 1_000_000.0),
        "pos_y": (-1_000_000.0, 1_000_000.0),
        "battery_level": (0.0, 100.0),
        "current_load": (0.0, 100.0),
        "motor_temp": (-40.0, 200.0),
    }.items():
        reason = reason.when(
            F.col(field).isNull() | (F.col(field) < lower) | (F.col(field) > upper),
            F.lit(f"INVALID_{field.upper()}"),
        )
    reason = reason.when(F.col("event_time").isNull(), F.lit("INVALID_TIMESTAMP"))
    reason = reason.when(
        ~F.upper(F.trim(F.col("failure_type"))).isin("NONE", "HDF", "PWF", "OSF", "TWF", "RNF"),
        F.lit("INVALID_FAILURE_TYPE"),
    )

    with_reason = typed.withColumn("reject_reason", reason)
    invalid = with_reason.filter(F.col("reject_reason").isNotNull())
    valid = with_reason.filter(F.col("reject_reason").isNull()).drop("reject_reason")

    canonical = F.to_json(
        F.struct(
            F.trim("robot_id").alias("robot_id"),
            F.col("pos_x"),
            F.col("pos_y"),
            F.col("battery_level"),
            F.col("current_load"),
            F.col("motor_temp"),
            F.date_format("event_time", "yyyy-MM-dd'T'HH:mm:ss.SSSXXX").alias("timestamp"),
            F.upper(F.trim("failure_type")).alias("failure_type"),
        )
    )
    valid = (
        valid.withColumn("robot_id", F.trim("robot_id"))
        .withColumn("failure_type", F.upper(F.trim("failure_type")))
        .withColumn("event_id", F.sha2(canonical, 256))
        .withColumn("batch_id", F.lit(batch_id))
        .withColumn("attempt_id", F.lit(attempt_id))
        .withColumn("source_path", F.input_file_name())
        .withColumn("ingested_at", F.current_timestamp())
        .withColumn("source_event_time", F.col("event_time"))
        .select(
            "event_id",
            "batch_id",
            "attempt_id",
            "robot_id",
            "pos_x",
            "pos_y",
            "battery_level",
            "current_load",
            "motor_temp",
            "source_event_time",
            "failure_type",
            "source_path",
            "ingested_at",
        )
    )
    return valid.dropDuplicates(["event_id"]), invalid


def _jdbc_options(secret: dict[str, str], jdbc_url: str) -> dict[str, str]:
    return {
        "url": jdbc_url,
        "user": secret["username"],
        "password": secret["password"],
        "driver": "com.mysql.cj.jdbc.Driver",
    }


def _write_audit(
    glue_context: GlueContext,
    secret: dict[str, str],
    jdbc_url: str,
    audit_table: str,
    args: dict[str, str],
    status: str,
    source_rows: int,
    accepted_rows: int,
    rejected_rows: int,
    error_message: str | None = None,
) -> None:
    audit_schema = StructType(
        [
            StructField("batch_id", StringType(), False),
            StructField("attempt_id", StringType(), False),
            StructField("source_path", StringType(), False),
            StructField("source_rows", LongType(), False),
            StructField("accepted_rows", LongType(), False),
            StructField("rejected_rows", LongType(), False),
            StructField("staged_rows", LongType(), False),
            StructField("status", StringType(), False),
            StructField("error_message", StringType(), True),
            StructField("started_at", TimestampType(), False),
            StructField("completed_at", TimestampType(), False),
        ]
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = [
        (
            args["BATCH_ID"],
            args["ATTEMPT_ID"],
            args["SOURCE_PATH"],
            int(source_rows),
            int(accepted_rows),
            int(rejected_rows),
            int(accepted_rows if status == "STAGED" else 0),
            status,
            error_message,
            now,
            now,
        )
    ]
    audit_df = glue_context.spark_session.createDataFrame(row, schema=audit_schema)
    audit_df.write.format("jdbc").options(**_jdbc_options(secret, jdbc_url)).option("dbtable", audit_table).mode("append").save()


def main() -> None:
    args = _arguments()
    sc = SparkContext.getOrCreate()
    glue_context = GlueContext(sc)
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)
    secret = _secret(args["SECRET_ARN"])
    source = glue_context.spark_session.read.parquet(args["SOURCE_PATH"])
    valid, invalid = _prepare(source, args["BATCH_ID"], args["ATTEMPT_ID"])
    source_rows = source.count()
    rejected_rows = invalid.count()
    accepted_rows = valid.count()
    LOGGER.info(
        "migration_quality batch_id=%s attempt_id=%s source_rows=%d accepted_rows=%d rejected_rows=%d",
        args["BATCH_ID"],
        args["ATTEMPT_ID"],
        source_rows,
        accepted_rows,
        rejected_rows,
    )

    if rejected_rows:
        invalid.write.mode("overwrite").parquet(args["REJECT_PATH"])
        _write_audit(
            glue_context,
            secret,
            args["JDBC_URL"],
            args["AUDIT_TABLE"],
            args,
            "REJECTED",
            source_rows,
            accepted_rows,
            rejected_rows,
            "data contract validation failed; staging was not written",
        )
        raise RuntimeError("data contract validation failed; see reject path and audit table")

    valid.write.format("jdbc").options(**_jdbc_options(secret, args["JDBC_URL"])).option("dbtable", args["STAGING_TABLE"]).mode("append").save()
    _write_audit(
        glue_context,
        secret,
        args["JDBC_URL"],
        args["AUDIT_TABLE"],
        args,
        "STAGED",
        source_rows,
        accepted_rows,
        rejected_rows,
    )
    job.commit()


if __name__ == "__main__":
    main()
