"""Create the migration lab tables through the RDS private connection."""

from __future__ import annotations

import json
import logging
import os
import sys

import boto3
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext


LOGGER = logging.getLogger("bootstrap-schema")
LOGGER.setLevel(logging.INFO)


def _secret(secret_arn: str) -> dict[str, str]:
    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))
    value = client.get_secret_value(SecretId=secret_arn).get("SecretString")
    if not value:
        raise RuntimeError("migration secret has no SecretString")
    return json.loads(value)


def main() -> None:
    args = getResolvedOptions(sys.argv, ["JOB_NAME", "JDBC_URL", "SECRET_ARN", "SCHEMA_PATH"])
    sc = SparkContext.getOrCreate()
    glue_context = GlueContext(sc)
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)

    s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))
    bucket, _, key = args["SCHEMA_PATH"][5:].partition("/")
    schema_sql = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    # Strip full-line SQL comments before splitting statements.  A comment may
    # contain a semicolon (for example ``attempt; target``), which otherwise
    # becomes an invalid SQL fragment sent to MySQL.
    schema_sql = "\n".join(
        line for line in schema_sql.splitlines() if not line.strip().startswith("--")
    )
    secret = _secret(args["SECRET_ARN"])

    jvm = glue_context.spark_session._jvm
    jvm.java.lang.Class.forName("com.mysql.cj.jdbc.Driver")
    connection = jvm.java.sql.DriverManager.getConnection(
        args["JDBC_URL"], secret["username"], secret["password"]
    )
    connection.setAutoCommit(False)
    statement = connection.createStatement()
    try:
        for sql in schema_sql.split(";"):
            sql = sql.strip()
            if sql:
                statement.executeUpdate(sql)
        connection.commit()
        LOGGER.info("schema_bootstrapped")
    except Exception:
        connection.rollback()
        raise
    finally:
        statement.close()
        connection.close()
    job.commit()


if __name__ == "__main__":
    main()
