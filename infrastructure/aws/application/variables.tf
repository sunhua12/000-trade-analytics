variable "aws_region" {
  type = string
}
variable "aws_account_id" {
  type = string
}
variable "raw_bucket_name" {
  type = string
}
variable "repository_name" {
  type = string
}
variable "function_name" {
  type = string
}
variable "execution_role_name" {
  type = string
}
variable "s3_policy_name" {
  type    = string
  default = "TradeAnalyticsS3Access"
}
variable "image_uri" {
  type = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image_uri))
    error_message = "Use an immutable ECR image digest, not a tag."
  }
}
variable "raw_prefix" {
  type    = string
  default = "un_comtrade"
}
variable "lambda_environment" {
  type      = map(string)
  default   = {}
  sensitive = true
}
variable "memory_size" {
  type    = number
  default = 512
}
variable "timeout" {
  type    = number
  default = 180
}
variable "reserved_concurrency" {
  type    = number
  default = -1
}
variable "log_retention_days" {
  type    = number
  default = 30
}
variable "image_tag_mutability" {
  type    = string
  default = "MUTABLE"
}
variable "ecr_lifecycle_policy" {
  description = "Optional reviewed policy. Null preserves all existing images."
  type        = string
  default     = null
}
