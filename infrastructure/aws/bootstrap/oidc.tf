variable "github_repository" {
  type    = string
  default = null
  validation {
    condition     = var.github_repository == null ? true : can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use an exact owner/repository, without wildcards."
  }
}
variable "github_deploy_branches" {
  type    = set(string)
  default = ["main"]
  validation {
    condition     = length(var.github_deploy_branches) > 0 && alltrue([for branch in var.github_deploy_branches : can(regex("^[A-Za-z0-9_./-]+$", branch))])
    error_message = "Deployment requires at least one exact branch, without wildcards."
  }
}
variable "github_oidc_subject_prefix" {
  description = "Exact prefix from GitHub's OIDC customization API; new repositories include immutable IDs."
  type        = string
  default     = null
  validation {
    condition     = var.github_oidc_subject_prefix == null ? true : can(regex("^repo:[A-Za-z0-9_.-]+(@[0-9]+)?/[A-Za-z0-9_.-]+(@[0-9]+)?$", var.github_oidc_subject_prefix))
    error_message = "Use the exact repo:owner/repository prefix, with optional immutable IDs."
  }
}
variable "existing_github_oidc_provider_arn" {
  type    = string
  default = null
}
variable "deployment_role_name" {
  type    = string
  default = "trade-analytics-github-deploy"
}
variable "application_state_key" {
  type    = string
  default = "trade-analytics/application/terraform.tfstate"
}
variable "raw_bucket_name" {
  type    = string
  default = null
}
variable "repository_name" {
  type    = string
  default = "trade-analytics-ingestion"
}
variable "function_name" {
  type    = string
  default = "trade-analytics-ingestion"
}
variable "execution_role_name" {
  type    = string
  default = "trade-analytics-lambda-role"
}

locals {
  oidc_enabled   = var.github_repository != null
  subject_prefix = var.github_oidc_subject_prefix != null ? var.github_oidc_subject_prefix : "repo:${var.github_repository == null ? "disabled" : var.github_repository}"
  oidc_arn       = var.existing_github_oidc_provider_arn != null ? var.existing_github_oidc_provider_arn : (local.oidc_enabled ? aws_iam_openid_connect_provider.github[0].arn : null)
  lambda_arn     = "arn:aws:lambda:${var.aws_region}:${var.aws_account_id}:function:${var.function_name}"
  ecr_arn        = "arn:aws:ecr:${var.aws_region}:${var.aws_account_id}:repository/${var.repository_name}"
  logs_arn       = "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/lambda/${var.function_name}:*"
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = local.oidc_enabled && var.existing_github_oidc_provider_arn == null ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "github_deploy" {
  count                = local.oidc_enabled ? 1 : 0
  name                 = var.deployment_role_name
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.oidc_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = [for branch in sort(tolist(var.github_deploy_branches)) : "${local.subject_prefix}:ref:refs/heads/${branch}"]
        }
      }
    }]
  })
  lifecycle {
    precondition {
      condition     = var.raw_bucket_name != null
      error_message = "Set the managed raw bucket when enabling deployment."
    }
  }
}

# Daily deployment changes images only. Infrastructure changes remain bootstrap/admin work.
resource "aws_iam_role_policy" "github_deploy" {
  count = local.oidc_enabled ? 1 : 0
  name  = "TradeAnalyticsImageDeployment"
  role  = aws_iam_role.github_deploy[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ApplicationStateOnly"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = ["${aws_s3_bucket.state.arn}/${var.application_state_key}", "${aws_s3_bucket.state.arn}/${var.application_state_key}.tflock"]
      },
      {
        Sid      = "DeleteLockOnly"
        Effect   = "Allow"
        Action   = "s3:DeleteObject"
        Resource = "${aws_s3_bucket.state.arn}/${var.application_state_key}.tflock"
      },
      {
        Sid       = "LocateApplicationState"
        Effect    = "Allow"
        Action    = "s3:ListBucket"
        Resource  = aws_s3_bucket.state.arn
        Condition = { StringLike = { "s3:prefix" = [var.application_state_key, "${var.application_state_key}.tflock"] } }
      },
      {
        Sid      = "InspectManagedBucket"
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation", "s3:GetBucketVersioning", "s3:GetBucketPublicAccessBlock", "s3:GetEncryptionConfiguration", "s3:GetBucketOwnershipControls", "s3:GetBucketTagging", "s3:ListBucket", "s3:GetBucketPolicy", "s3:GetBucketAcl", "s3:GetBucketCORS", "s3:GetBucketWebsite", "s3:GetAccelerateConfiguration", "s3:GetBucketRequestPayment", "s3:GetBucketLogging", "s3:GetLifecycleConfiguration", "s3:GetReplicationConfiguration", "s3:GetBucketObjectLockConfiguration"]
        Resource = "arn:aws:s3:::${var.raw_bucket_name}"
      },
      {
        Sid      = "ECRLoginRequiresWildcard"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid      = "ManagedRepositoryPushAndRead"
        Effect   = "Allow"
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:DescribeRepositories", "ecr:DescribeImages", "ecr:GetLifecyclePolicy", "ecr:ListTagsForResource"]
        Resource = local.ecr_arn
      },
      {
        Sid      = "LambdaImageOnly"
        Effect   = "Allow"
        Action   = ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionCodeSigningConfig", "lambda:GetRuntimeManagementConfig", "lambda:GetFunctionConcurrency", "lambda:ListVersionsByFunction", "lambda:ListTags", "lambda:UpdateFunctionCode"]
        Resource = local.lambda_arn
      },
      {
        Sid      = "ReadExecutionRole"
        Effect   = "Allow"
        Action   = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies"]
        Resource = "arn:aws:iam::${var.aws_account_id}:role/${var.execution_role_name}"
      },
      {
        Sid       = "PassOnlyLambdaExecutionRole"
        Effect    = "Allow"
        Action    = "iam:PassRole"
        Resource  = "arn:aws:iam::${var.aws_account_id}:role/${var.execution_role_name}"
        Condition = { StringEquals = { "iam:PassedToService" = "lambda.amazonaws.com" } }
      },
      {
        Sid      = "DescribeLogsAndAlarmsRequiresWildcard"
        Effect   = "Allow"
        Action   = ["logs:DescribeLogGroups", "cloudwatch:DescribeAlarms"]
        Resource = "*"
      },
      {
        Sid      = "ReadManagedLogs"
        Effect   = "Allow"
        Action   = ["logs:DescribeMetricFilters", "logs:ListTagsForResource", "logs:ListTagsLogGroup"]
        Resource = [local.logs_arn, trimsuffix(local.logs_arn, ":*")]
      },
      {
        Sid      = "ReadManagedAlarmTags"
        Effect   = "Allow"
        Action   = "cloudwatch:ListTagsForResource"
        Resource = "arn:aws:cloudwatch:${var.aws_region}:${var.aws_account_id}:alarm:${var.function_name}-*"
      },
      {
        Sid      = "ReadManagedNotificationTopic"
        Effect   = "Allow"
        Action   = ["sns:GetTopicAttributes", "sns:GetSubscriptionAttributes", "sns:ListTagsForResource", "sns:ListSubscriptionsByTopic"]
        Resource = "arn:aws:sns:${var.aws_region}:${var.aws_account_id}:${var.function_name}-alarms"
      }
    ]
  })
}

output "github_deployment_role_arn" {
  value = local.oidc_enabled ? aws_iam_role.github_deploy[0].arn : null
}
