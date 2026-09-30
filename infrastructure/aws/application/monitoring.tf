locals {
  ingestion_error_categories = toset([
    "ComtradeResponseError",
    "ResponseTruncatedError",
    "StorageConflictError",
  ])
  ingestion_metric_namespace = "TradeAnalytics/${var.function_name}"
}

resource "aws_sns_topic" "ingestion_alarms" {
  name = "${var.function_name}-alarms"
}

resource "aws_sns_topic_policy" "ingestion_alarms" {
  arn = aws_sns_topic.ingestion_alarms.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowAccountAlarmsToPublish"
      Effect    = "Allow"
      Principal = { Service = "cloudwatch.amazonaws.com" }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.ingestion_alarms.arn
      Condition = {
        StringEquals = { "aws:SourceAccount" = var.aws_account_id }
        ArnLike = {
          "aws:SourceArn" = "arn:aws:cloudwatch:${var.aws_region}:${var.aws_account_id}:alarm:${var.function_name}-*"
        }
      }
    }]
  })
}

resource "aws_sns_topic_subscription" "ingestion_email" {
  count     = var.alarm_email_endpoint == null ? 0 : 1
  topic_arn = aws_sns_topic.ingestion_alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email_endpoint
}

resource "aws_cloudwatch_log_metric_filter" "ingestion_error" {
  for_each       = local.ingestion_error_categories
  name           = "${var.function_name}-${each.key}"
  log_group_name = aws_cloudwatch_log_group.lambda.name
  pattern        = "{ $.event = \"ingestion_failed\" && $.error_category = \"${each.key}\" }"

  metric_transformation {
    name          = each.key
    namespace     = local.ingestion_metric_namespace
    value         = "1"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "ingestion_error" {
  for_each            = local.ingestion_error_categories
  alarm_name          = "${var.function_name}-${each.key}"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = aws_cloudwatch_log_metric_filter.ingestion_error[each.key].metric_transformation[0].name
  namespace           = local.ingestion_metric_namespace
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ingestion_alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.function_name}-LambdaErrors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  dimensions          = { FunctionName = aws_lambda_function.ingestion.function_name }
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ingestion_alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_duration" {
  alarm_name          = "${var.function_name}-LambdaDuration"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  dimensions          = { FunctionName = aws_lambda_function.ingestion.function_name }
  period              = 60
  statistic           = "Maximum"
  threshold           = var.alarm_duration_threshold_ms
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ingestion_alarms.arn]

  lifecycle {
    precondition {
      condition     = var.alarm_duration_threshold_ms < var.timeout * 1000
      error_message = "Duration alarm threshold must be below the Lambda timeout."
    }
  }
}
