data "aws_availability_zones" "available" {
  state = "available"
}

resource "random_id" "suffix" {
  byte_length = 3
}

locals {
  name = "${var.project_name}-${random_id.suffix.hex}"
  common_tags = {
    Project     = var.project_name
    Environment = "short-lived-validation"
    ManagedBy   = "terraform"
    CostProfile = "s3-glue-rds-minimal"
  }
  bucket_arn = aws_s3_bucket.lab.arn
}

resource "aws_vpc" "lab" {
  cidr_block           = "10.44.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.common_tags, { Name = "${local.name}-vpc" })
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.lab.id
  cidr_block        = cidrsubnet(aws_vpc.lab.cidr_block, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]
  tags              = merge(local.common_tags, { Name = "${local.name}-private-${count.index + 1}" })
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.lab.id
  tags   = merge(local.common_tags, { Name = "${local.name}-private-rt" })
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "endpoints" {
  name        = "${local.name}-endpoints"
  description = "HTTPS from Glue ENI to AWS API interface endpoints"
  vpc_id      = aws_vpc.lab.id
  ingress {
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = [aws_vpc.lab.cidr_block]
  }
  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = local.common_tags
}

resource "aws_security_group" "glue" {
  name        = "${local.name}-glue"
  description = "Glue ENI egress and RDS client identity"
  vpc_id      = aws_vpc.lab.id
  # AWS Glue requires the job ENIs to communicate with one another.  The source is
  # restricted to this SG; it is not an internet-facing all-source rule.
  ingress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    self        = true
    description = "Glue ENI internal communication"
  }
  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = local.common_tags
}

resource "aws_security_group" "rds" {
  name        = "${local.name}-rds"
  description = "Only Glue ENIs may connect to the private lab database"
  vpc_id      = aws_vpc.lab.id
  ingress {
    protocol        = "tcp"
    from_port       = 3306
    to_port         = 3306
    security_groups = [aws_security_group.glue.id]
    description     = "Glue JDBC"
  }
  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = local.common_tags
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.lab.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = merge(local.common_tags, { Name = "${local.name}-s3-endpoint" })
}

resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = aws_vpc.lab.id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private[0].id]
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
  tags                = merge(local.common_tags, { Name = "${local.name}-secrets-endpoint" })
}

resource "aws_vpc_endpoint" "logs" {
  vpc_id              = aws_vpc.lab.id
  service_name        = "com.amazonaws.${var.aws_region}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private[0].id]
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
  tags                = merge(local.common_tags, { Name = "${local.name}-logs-endpoint" })
}

resource "aws_db_subnet_group" "lab" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
  tags       = merge(local.common_tags, { Name = "${local.name}-db-subnets" })
}

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "aws_db_instance" "lab" {
  identifier                   = local.name
  engine                       = "mysql"
  instance_class               = var.rds_instance_class
  allocated_storage            = 20
  max_allocated_storage        = 20
  storage_type                 = "gp3"
  db_name                      = "telemetry"
  username                     = var.db_username
  password                     = random_password.db.result
  db_subnet_group_name         = aws_db_subnet_group.lab.name
  vpc_security_group_ids       = [aws_security_group.rds.id]
  publicly_accessible          = false
  multi_az                     = false
  backup_retention_period      = 0
  deletion_protection          = false
  skip_final_snapshot          = true
  copy_tags_to_snapshot        = true
  storage_encrypted            = true
  apply_immediately            = true
  auto_minor_version_upgrade   = true
  monitoring_interval          = 0
  performance_insights_enabled = false
  tags                         = local.common_tags
}

resource "aws_s3_bucket" "lab" {
  bucket        = local.name
  force_destroy = true
  tags          = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "lab" {
  bucket                  = aws_s3_bucket.lab.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lab" {
  bucket = aws_s3_bucket.lab.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "lab" {
  bucket = aws_s3_bucket.lab.id
  rule {
    id     = "expire-lab-data"
    status = "Enabled"
    filter {}
    expiration {
      days = 1
    }
  }
}

resource "aws_secretsmanager_secret" "rds" {
  name                    = "${local.name}/rds"
  recovery_window_in_days = 0
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret_version" "rds" {
  secret_id = aws_secretsmanager_secret.rds.id
  secret_string = jsonencode({
    engine   = "mysql"
    host     = aws_db_instance.lab.address
    port     = 3306
    dbname   = "telemetry"
    username = var.db_username
    password = random_password.db.result
  })
}

resource "aws_glue_catalog_database" "lab" {
  name = replace(local.name, "-", "_")
  tags = local.common_tags
}

resource "aws_glue_catalog_table" "bronze" {
  name          = "robot_telemetry_bronze"
  database_name = aws_glue_catalog_database.lab.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { classification = "parquet" }
  storage_descriptor {
    location      = "s3://${aws_s3_bucket.lab.bucket}/bronze/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }
    dynamic "columns" {
      for_each = {
        robot_id      = "string"
        pos_x         = "double"
        pos_y         = "double"
        battery_level = "double"
        current_load  = "double"
        motor_temp    = "double"
        timestamp     = "string"
        failure_type  = "string"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
  depends_on = [aws_s3_bucket_server_side_encryption_configuration.lab]
}

data "aws_iam_policy_document" "glue_assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "glue" {
  name               = "${local.name}-glue-role"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

data "aws_iam_policy_document" "glue_lab" {
  statement {
    sid       = "ReadWriteLabBucket"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload", "s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.lab.arn, "${aws_s3_bucket.lab.arn}/*"]
  }
  statement {
    sid       = "ReadDatabaseSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.rds.arn]
  }
  statement {
    sid    = "GlueNetworkInterfaces"
    effect = "Allow"
    actions = [
      "ec2:CreateNetworkInterface",
      "ec2:DeleteNetworkInterface",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeVpcEndpoints",
      "ec2:DescribeRouteTables",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "glue_lab" {
  name   = "${local.name}-glue-lab-policy"
  role   = aws_iam_role.glue.id
  policy = data.aws_iam_policy_document.glue_lab.json
}

resource "aws_glue_connection" "rds" {
  name            = "${local.name}-rds-connection"
  connection_type = "JDBC"
  connection_properties = {
    JDBC_CONNECTION_URL = "jdbc:mysql://${aws_db_instance.lab.address}:3306/telemetry"
    SECRET_ID           = aws_secretsmanager_secret.rds.arn
  }
  physical_connection_requirements {
    availability_zone      = data.aws_availability_zones.available.names[0]
    security_group_id_list = [aws_security_group.glue.id]
    subnet_id              = aws_subnet.private[0].id
  }
}

resource "aws_s3_object" "contract" {
  bucket       = aws_s3_bucket.lab.id
  key          = "jobs/s3_to_rds_contract.py"
  source       = "${path.module}/../../src/migration/s3_to_rds_contract.py"
  content_type = "text/x-python"
  etag         = filemd5("${path.module}/../../src/migration/s3_to_rds_contract.py")
}

resource "aws_s3_object" "extract" {
  bucket       = aws_s3_bucket.lab.id
  key          = "jobs/s3_to_rds.py"
  source       = "${path.module}/../../jobs/glue/s3_to_rds.py"
  content_type = "text/x-python"
  etag         = filemd5("${path.module}/../../jobs/glue/s3_to_rds.py")
}

resource "aws_s3_object" "bootstrap" {
  bucket       = aws_s3_bucket.lab.id
  key          = "jobs/bootstrap_schema.py"
  source       = "${path.module}/../../jobs/glue/bootstrap_schema.py"
  content_type = "text/x-python"
  etag         = filemd5("${path.module}/../../jobs/glue/bootstrap_schema.py")
}

resource "aws_s3_object" "promote" {
  bucket       = aws_s3_bucket.lab.id
  key          = "jobs/promote_batch_spark.py"
  source       = "${path.module}/../../jobs/glue/promote_batch_spark.py"
  content_type = "text/x-python"
  etag         = filemd5("${path.module}/../../jobs/glue/promote_batch_spark.py")
}

resource "aws_s3_object" "verify" {
  bucket       = aws_s3_bucket.lab.id
  key          = "jobs/verify_counts.py"
  source       = "${path.module}/../../jobs/glue/verify_counts.py"
  content_type = "text/x-python"
  etag         = filemd5("${path.module}/../../jobs/glue/verify_counts.py")
}

resource "aws_s3_object" "schema" {
  bucket       = aws_s3_bucket.lab.id
  key          = "jobs/robot_telemetry_schema.sql"
  source       = "${path.module}/../../jobs/glue/sql/robot_telemetry_schema.sql"
  content_type = "application/sql"
  etag         = filemd5("${path.module}/../../jobs/glue/sql/robot_telemetry_schema.sql")
}

resource "aws_glue_job" "bootstrap" {
  name              = "${local.name}-bootstrap"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 10
  connections       = [aws_glue_connection.rds.name]
  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${aws_s3_bucket.lab.bucket}/${aws_s3_object.bootstrap.key}"
  }
  default_arguments = {
    "--job-language"                     = "python"
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--JDBC_URL"                         = "jdbc:mysql://${aws_db_instance.lab.address}:3306/telemetry"
    "--SECRET_ARN"                       = aws_secretsmanager_secret.rds.arn
    "--SCHEMA_PATH"                      = "s3://${aws_s3_bucket.lab.bucket}/${aws_s3_object.schema.key}"
  }
  execution_property {
    max_concurrent_runs = 1
  }
  depends_on = [aws_iam_role_policy_attachment.glue_service, aws_iam_role_policy.glue_lab]
}

resource "aws_glue_job" "extract" {
  name              = "${local.name}-s3-to-rds"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 10
  connections       = [aws_glue_connection.rds.name]
  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${aws_s3_bucket.lab.bucket}/${aws_s3_object.extract.key}"
  }
  default_arguments = {
    "--job-language"                     = "python"
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--extra-py-files"                   = "s3://${aws_s3_bucket.lab.bucket}/${aws_s3_object.contract.key}"
    "--JDBC_URL"                         = "jdbc:mysql://${aws_db_instance.lab.address}:3306/telemetry"
    "--SECRET_ARN"                       = aws_secretsmanager_secret.rds.arn
    "--STAGING_TABLE"                    = "robot_telemetry_migration_stg"
    "--AUDIT_TABLE"                      = "robot_telemetry_migration_audit"
  }
  execution_property {
    max_concurrent_runs = 1
  }
  depends_on = [aws_glue_job.bootstrap]
}

resource "aws_glue_job" "promote" {
  name              = "${local.name}-promote"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 10
  connections       = [aws_glue_connection.rds.name]
  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${aws_s3_bucket.lab.bucket}/${aws_s3_object.promote.key}"
  }
  default_arguments = {
    "--job-language"                     = "python"
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--JDBC_URL"                         = "jdbc:mysql://${aws_db_instance.lab.address}:3306/telemetry"
    "--SECRET_ARN"                       = aws_secretsmanager_secret.rds.arn
    "--STAGING_TABLE"                    = "robot_telemetry_migration_stg"
    "--TARGET_TABLE"                     = "robot_telemetry"
    "--AUDIT_TABLE"                      = "robot_telemetry_migration_audit"
  }
  execution_property {
    max_concurrent_runs = 1
  }
  depends_on = [aws_glue_job.extract]
}

resource "aws_glue_job" "verify" {
  name              = "${local.name}-verify"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 10
  connections       = [aws_glue_connection.rds.name]
  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${aws_s3_bucket.lab.bucket}/${aws_s3_object.verify.key}"
  }
  default_arguments = {
    "--job-language"                     = "python"
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--JDBC_URL"                         = "jdbc:mysql://${aws_db_instance.lab.address}:3306/telemetry"
    "--SECRET_ARN"                       = aws_secretsmanager_secret.rds.arn
  }
  execution_property {
    max_concurrent_runs = 1
  }
  depends_on = [aws_glue_job.promote]
}
