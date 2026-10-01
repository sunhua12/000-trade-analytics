resource "aws_s3_bucket" "raw" {
  bucket        = var.raw_bucket_name
  force_destroy = false
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = aws_s3_bucket.raw.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    bucket_key_enabled       = true
    blocked_encryption_types = ["SSE-C"]
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_ecr_repository" "ingestion" {
  name                 = var.repository_name
  image_tag_mutability = var.image_tag_mutability
  force_delete         = false
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "ingestion" {
  count      = var.ecr_lifecycle_policy == null ? 0 : 1
  repository = aws_ecr_repository.ingestion.name
  policy     = var.ecr_lifecycle_policy
}

resource "aws_iam_role" "lambda" {
  name        = var.execution_role_name
  description = "Allows Lambda functions to call AWS services on your behalf."
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy_attachment" "logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "s3" {
  name = var.s3_policy_name
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadWriteTradeV2Objects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.raw.arn}/${var.raw_prefix}/v2/*"
      },
      {
        Sid      = "RecognizeMissingObjectsInTradeBucket"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.raw.arn
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_lambda_function" "ingestion" {
  function_name                  = var.function_name
  role                           = aws_iam_role.lambda.arn
  package_type                   = "Image"
  image_uri                      = var.image_uri
  architectures                  = ["x86_64"]
  memory_size                    = var.memory_size
  timeout                        = var.timeout
  reserved_concurrent_executions = var.reserved_concurrency
  environment {
    variables = merge(var.lambda_environment, {
      RAW_BUCKET = aws_s3_bucket.raw.id
      RAW_PREFIX = var.raw_prefix
    })
  }
  ephemeral_storage {
    size = 512
  }
  tracing_config {
    mode = "PassThrough"
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.lambda.name
  }
  depends_on = [aws_iam_role_policy.s3, aws_iam_role_policy_attachment.logs]
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = startswith(var.image_uri, "${aws_ecr_repository.ingestion.repository_url}@sha256:")
      error_message = "The image must belong to the managed ECR repository."
    }
  }
}
