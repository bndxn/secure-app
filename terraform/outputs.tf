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
