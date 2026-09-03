"""Glue Python Shell entrypoint for transactional staging-to-target promotion."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3
import mysql.connector
from awsglue.utils import getResolvedOptions


LOGGER = logging.getLogger("promote-batch")
LOGGER.setLevel(logging.INFO)


def _arguments() -> dict[str, str]:
    return getResolvedOptions(
        sys.argv,
        ["JOB_NAME", "SECRET_ARN", "BATCH_ID", "ATTEMPT_ID", "STAGING_TABLE", "TARGET_TABLE", "AUDIT_TABLE"],
    )


def _secret(secret_arn: str) -> dict[str, str]:
    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))
    value = client.get_secret_value(SecretId=secret_arn).get("SecretString")
    if not value:
        raise RuntimeError("migration secret has no SecretString")
    return json.loads(value)


def main() -> None:
    args = _arguments()
    secret = _secret(args["SECRET_ARN"])
    connection = mysql.connector.connect(
        host=secret["host"],
        port=int(secret.get("port", 3306)),
        user=secret["username"],
        password=secret["password"],
        database=secret["dbname"],
    )
    cursor = connection.cursor()
    started_at = datetime.now(timezone.utc)
    try:
        cursor.execute(
            f"""
            INSERT INTO {args['TARGET_TABLE']} (
                event_id, robot_id, pos_x, pos_y, battery_level, current_load,
                motor_temp, event_time, failure_type, batch_id, source_path, ingested_at
            )
            SELECT s.event_id, s.robot_id, s.pos_x, s.pos_y, s.battery_level, s.current_load,
                   s.motor_temp, s.source_event_time, s.failure_type, s.batch_id,
                   s.source_path, s.ingested_at
            FROM {args['STAGING_TABLE']} AS s
            WHERE s.batch_id = %s AND s.attempt_id = %s
            GROUP BY s.event_id, s.robot_id, s.pos_x, s.pos_y, s.battery_level, s.current_load,
                     s.motor_temp, s.source_event_time, s.failure_type, s.batch_id,
                     s.source_path, s.ingested_at
            ON DUPLICATE KEY UPDATE event_id = event_id
            """,
            (args["BATCH_ID"], args["ATTEMPT_ID"]),
        )
        merged_rows = cursor.rowcount
        cursor.execute(
            f"""
            UPDATE {args['AUDIT_TABLE']}
            SET status = 'PROMOTED', merged_rows = %s, completed_at = %s
            WHERE batch_id = %s AND attempt_id = %s
            """,
            (merged_rows, datetime.now(timezone.utc), args["BATCH_ID"], args["ATTEMPT_ID"]),
        )
        connection.commit()
        LOGGER.info(
            "migration_promoted batch_id=%s attempt_id=%s merged_rows=%d duration_seconds=%.3f",
            args["BATCH_ID"],
            args["ATTEMPT_ID"],
            merged_rows,
            (datetime.now(timezone.utc) - started_at).total_seconds(),
        )
    except Exception as exc:
        connection.rollback()
        cursor.execute(
            f"""
            UPDATE {args['AUDIT_TABLE']}
            SET status = 'PROMOTION_FAILED', error_message = %s, completed_at = %s
            WHERE batch_id = %s AND attempt_id = %s
            """,
            (str(exc)[:1000], datetime.now(timezone.utc), args["BATCH_ID"], args["ATTEMPT_ID"]),
        )
        connection.commit()
        raise
    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
