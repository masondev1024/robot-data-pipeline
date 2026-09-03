"""Glue Spark entrypoint for an idempotent, transactional staging promotion.

Using the JDBC driver already present in the Glue runtime keeps this short-lived lab
independent of a package download from PyPI.  Table names are allow-listed because
they are supplied as job arguments and interpolated into SQL identifiers.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys

import boto3
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext


LOGGER = logging.getLogger("promote-batch")
LOGGER.setLevel(logging.INFO)
IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def _secret(secret_arn: str) -> dict[str, str]:
    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))
    value = client.get_secret_value(SecretId=secret_arn).get("SecretString")
    if not value:
        raise RuntimeError("migration secret has no SecretString")
    return json.loads(value)


def _identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value}")
    return value


def main() -> None:
    args = getResolvedOptions(
        sys.argv,
        ["JOB_NAME", "JDBC_URL", "SECRET_ARN", "BATCH_ID", "ATTEMPT_ID", "STAGING_TABLE", "TARGET_TABLE", "AUDIT_TABLE"],
    )
    sc = SparkContext.getOrCreate()
    glue_context = GlueContext(sc)
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)
    secret = _secret(args["SECRET_ARN"])

    staging = _identifier(args["STAGING_TABLE"])
    target = _identifier(args["TARGET_TABLE"])
    audit = _identifier(args["AUDIT_TABLE"])
    jvm = glue_context.spark_session._jvm
    jvm.java.lang.Class.forName("com.mysql.cj.jdbc.Driver")
    connection = jvm.java.sql.DriverManager.getConnection(
        args["JDBC_URL"], secret["username"], secret["password"]
    )
    connection.setAutoCommit(False)
    try:
        promote = connection.prepareStatement(
            f"""
            INSERT INTO {target} (
                event_id, robot_id, pos_x, pos_y, battery_level, current_load,
                motor_temp, event_time, failure_type, batch_id, source_path, ingested_at
            )
            SELECT s.event_id, s.robot_id, s.pos_x, s.pos_y, s.battery_level, s.current_load,
                   s.motor_temp, s.source_event_time, s.failure_type, s.batch_id,
                   s.source_path, s.ingested_at
            FROM {staging} AS s
            WHERE s.batch_id = ? AND s.attempt_id = ?
            GROUP BY s.event_id, s.robot_id, s.pos_x, s.pos_y, s.battery_level, s.current_load,
                     s.motor_temp, s.source_event_time, s.failure_type, s.batch_id,
                     s.source_path, s.ingested_at
            ON DUPLICATE KEY UPDATE event_id = VALUES(event_id)
            """
        )
        promote.setString(1, args["BATCH_ID"])
        promote.setString(2, args["ATTEMPT_ID"])
        merged_rows = promote.executeUpdate()
        promote.close()

        audit_update = connection.prepareStatement(
            f"""
            UPDATE {audit}
            SET status = 'PROMOTED', merged_rows = ?, completed_at = CURRENT_TIMESTAMP(6)
            WHERE batch_id = ? AND attempt_id = ?
            """
        )
        audit_update.setInt(1, merged_rows)
        audit_update.setString(2, args["BATCH_ID"])
        audit_update.setString(3, args["ATTEMPT_ID"])
        audit_update.executeUpdate()
        audit_update.close()
        connection.commit()
        LOGGER.info(
            "migration_promoted batch_id=%s attempt_id=%s merged_rows=%d",
            args["BATCH_ID"],
            args["ATTEMPT_ID"],
            merged_rows,
        )
    except Exception as exc:
        connection.rollback()
        failure = connection.prepareStatement(
            f"""
            UPDATE {audit}
            SET status = 'PROMOTION_FAILED', error_message = ?, completed_at = CURRENT_TIMESTAMP(6)
            WHERE batch_id = ? AND attempt_id = ?
            """
        )
        failure.setString(1, str(exc)[:1000])
        failure.setString(2, args["BATCH_ID"])
        failure.setString(3, args["ATTEMPT_ID"])
        failure.executeUpdate()
        connection.commit()
        raise
    finally:
        connection.close()
    job.commit()


if __name__ == "__main__":
    main()
