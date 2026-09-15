# Existing Console resources. Once imported these blocks are harmless on reruns.
# For a NEW environment remove this file and follow the ECR-first runbook.
import {
  to = aws_s3_bucket.raw
  id = var.raw_bucket_name
}
import {
  to = aws_s3_bucket_versioning.raw
  id = var.raw_bucket_name
}
import {
  to = aws_s3_bucket_public_access_block.raw
  id = var.raw_bucket_name
}
import {
  to = aws_s3_bucket_server_side_encryption_configuration.raw
  id = var.raw_bucket_name
}
import {
  to = aws_s3_bucket_ownership_controls.raw
  id = var.raw_bucket_name
}
import {
  to = aws_ecr_repository.ingestion
  id = var.repository_name
}
import {
  to = aws_iam_role.lambda
  id = var.execution_role_name
}
import {
  to = aws_iam_role_policy_attachment.logs
  id = "${var.execution_role_name}/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
import {
  to = aws_iam_role_policy.s3
  id = "${var.execution_role_name}:${var.s3_policy_name}"
}
import {
  to = aws_cloudwatch_log_group.lambda
  id = "/aws/lambda/${var.function_name}"
}
import {
  to = aws_lambda_function.ingestion
  id = var.function_name
}
