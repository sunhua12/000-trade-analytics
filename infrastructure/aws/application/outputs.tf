output "function_name" {
  value = aws_lambda_function.ingestion.function_name
}
output "image_uri" {
  value = aws_lambda_function.ingestion.image_uri
}
output "raw_bucket" {
  value = aws_s3_bucket.raw.id
}
