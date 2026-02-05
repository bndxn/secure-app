output "app_runner_service_url" {
  description = "URL of the App Runner service"
  value       = aws_apprunner_service.app.service_url
}

output "app_runner_service_arn" {
  description = "ARN of the App Runner service"
  value       = aws_apprunner_service.app.arn
}

output "s3_bucket_name" {
  description = "Name of the S3 bucket"
  value       = aws_s3_bucket.app_data.bucket
}

output "s3_bucket_arn" {
  description = "ARN of the S3 bucket"
  value       = aws_s3_bucket.app_data.arn
}

output "ecr_repository_url" {
  description = "URL of the ECR repository"
  value       = aws_ecr_repository.app_repo.repository_url
}

output "apprunner_instance_role_arn" {
  description = "ARN of the App Runner instance role"
  value       = aws_iam_role.apprunner_role.arn
}

# Garmin Lambda Outputs
output "garmin_lambda_arn" {
  description = "ARN of the Garmin analyzer Lambda function"
  value       = aws_lambda_function.garmin_analyzer.arn
}

output "garmin_lambda_name" {
  description = "Name of the Garmin analyzer Lambda function"
  value       = aws_lambda_function.garmin_analyzer.function_name
}

output "garmin_lambda_ecr_url" {
  description = "ECR repository URL for the Garmin analyzer Lambda"
  value       = aws_ecr_repository.lambda_repo.repository_url
}

output "garmin_secret_arn" {
  description = "ARN of the Secrets Manager secret for Garmin credentials"
  value       = aws_secretsmanager_secret.garmin_credentials.arn
}

output "garmin_secret_name" {
  description = "Name of the Secrets Manager secret for Garmin credentials"
  value       = aws_secretsmanager_secret.garmin_credentials.name
}
