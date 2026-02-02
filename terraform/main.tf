terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = "prod"
}

# Data source for current AWS account
data "aws_caller_identity" "current" {}

# Data source for current AWS region
data "aws_region" "current" {}

# S3 bucket for application data
resource "aws_s3_bucket" "app_data" {
  bucket = var.s3_bucket_name

  tags = {
    Name        = "Secure App Data Bucket"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# S3 bucket versioning
resource "aws_s3_bucket_versioning" "app_data" {
  bucket = aws_s3_bucket.app_data.id
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 bucket server-side encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "app_data" {
  bucket = aws_s3_bucket.app_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 bucket public access block
resource "aws_s3_bucket_public_access_block" "app_data" {
  bucket = aws_s3_bucket.app_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# IAM role for App Runner service
resource "aws_iam_role" "apprunner_role" {
  name = "${var.app_name}-apprunner-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "build.apprunner.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
      {
        Effect = "Allow"
        Principal = {
          Service = "tasks.apprunner.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "${var.app_name}-apprunner-role"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM policy for App Runner to access S3
resource "aws_iam_policy" "apprunner_s3_policy" {
  name        = "${var.app_name}-apprunner-s3-policy"
  description = "Policy for App Runner to access S3 bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.app_data.arn,
          "${aws_s3_bucket.app_data.arn}/*"
        ]
      }
    ]
  })

  tags = {
    Name        = "${var.app_name}-apprunner-s3-policy"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# Attach S3 policy to App Runner role
resource "aws_iam_role_policy_attachment" "apprunner_s3" {
  role       = aws_iam_role.apprunner_role.name
  policy_arn = aws_iam_policy.apprunner_s3_policy.arn
}

# IAM role for App Runner access role (for ECR if using container registry)
resource "aws_iam_role" "apprunner_access_role" {
  name = "${var.app_name}-apprunner-access-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "build.apprunner.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "${var.app_name}-apprunner-access-role"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM policy for App Runner access role to pull from ECR
resource "aws_iam_policy" "apprunner_ecr_policy" {
  name        = "${var.app_name}-apprunner-ecr-policy"
  description = "Policy for App Runner to pull images from ECR"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      }
    ]
  })

  tags = {
    Name        = "${var.app_name}-apprunner-ecr-policy"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# Attach ECR policy to App Runner access role
resource "aws_iam_role_policy_attachment" "apprunner_ecr" {
  role       = aws_iam_role.apprunner_access_role.name
  policy_arn = aws_iam_policy.apprunner_ecr_policy.arn
}

# ECR repository for Docker images
resource "aws_ecr_repository" "app_repo" {
  name                 = var.app_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name        = "${var.app_name}-ecr-repo"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# ECR lifecycle policy to manage image retention
resource "aws_ecr_lifecycle_policy" "app_repo" {
  repository = aws_ecr_repository.app_repo.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus     = "any"
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# App Runner service
resource "aws_apprunner_service" "app" {
  service_name = var.app_name

  source_configuration {
    image_repository {
      image_configuration {
        port = "8000"
        runtime_environment_variables = {
          PORT           = "8000"
          S3_BUCKET_NAME = aws_s3_bucket.app_data.bucket
          AWS_REGION     = var.aws_region
        }
      }
      image_identifier      = "${aws_ecr_repository.app_repo.repository_url}:latest"
      image_repository_type = "ECR"
    }
    
    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_access_role.arn
    }
    
    auto_deployments_enabled = var.auto_deploy_enabled
  }

  instance_configuration {
    cpu               = "${var.cpu} vCPU"
    memory            = "${var.memory} GB"
    instance_role_arn = aws_iam_role.apprunner_role.arn
  }

  health_check_configuration {
    healthy_threshold   = 1
    interval            = 20
    path                = "/health"
    protocol            = "HTTP"
    timeout             = 20
    unhealthy_threshold = 5
  }

  tags = {
    Name        = var.app_name
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}
