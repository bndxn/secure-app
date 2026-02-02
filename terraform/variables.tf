variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Name of the application"
  type        = string
  default     = "secure-app"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "s3_bucket_name" {
  description = "Name of the S3 bucket for application data"
  type        = string
  default     = "secure-app-data-bucket"
}

variable "cpu" {
  description = "CPU units for App Runner instance (0.25, 0.5, 1, 2, 4)"
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Memory for App Runner instance (0.5, 1, 2, 3, 4, 6, 8 GB)"
  type        = string
  default     = "2"
}

variable "auto_deploy_enabled" {
  description = "Enable automatic deployments on image push"
  type        = bool
  default     = true
}
