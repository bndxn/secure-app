terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
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

# IAM policy for App Runner to invoke Bedrock (format recent runs with LLM)
resource "aws_iam_policy" "apprunner_bedrock_policy" {
  name        = "${var.app_name}-apprunner-bedrock-policy"
  description = "Policy for App Runner to invoke Bedrock for formatting"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/*"
        ]
      }
    ]
  })

  tags = {
    Name        = "${var.app_name}-apprunner-bedrock-policy"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_iam_role_policy_attachment" "apprunner_bedrock" {
  role       = aws_iam_role.apprunner_role.name
  policy_arn = aws_iam_policy.apprunner_bedrock_policy.arn
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

# Custom domain for running.bendixon.net
resource "aws_apprunner_custom_domain_association" "run_domain" {
  service_arn = aws_apprunner_service.app.arn
  domain_name = var.custom_domain_run
  # enable_www_subdomain = false  # set to true if you also want www.running.bendixon.net
}

# =============================================================================
# GARMIN RUN ANALYZER LAMBDA
# =============================================================================

# Secrets Manager secret for Garmin credentials
resource "aws_secretsmanager_secret" "garmin_credentials" {
  name        = var.garmin_secret_name
  description = "Garmin Connect credentials for the run analyzer Lambda"

  tags = {
    Name        = var.garmin_secret_name
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM role for Lambda function
resource "aws_iam_role" "lambda_role" {
  name = "${var.app_name}-garmin-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "${var.app_name}-garmin-lambda-role"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM policy for Lambda to access Secrets Manager
resource "aws_iam_policy" "lambda_secrets_policy" {
  name        = "${var.app_name}-lambda-secrets-policy"
  description = "Policy for Lambda to access Garmin credentials in Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.garmin_credentials.arn
      }
    ]
  })

  tags = {
    Name        = "${var.app_name}-lambda-secrets-policy"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM policy for Lambda to access S3
resource "aws_iam_policy" "lambda_s3_policy" {
  name        = "${var.app_name}-lambda-s3-policy"
  description = "Policy for Lambda to read/write to S3 bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]
        Resource = "${aws_s3_bucket.app_data.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = aws_s3_bucket.app_data.arn
      }
    ]
  })

  tags = {
    Name        = "${var.app_name}-lambda-s3-policy"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM policy for Lambda to invoke Bedrock
resource "aws_iam_policy" "lambda_bedrock_policy" {
  name        = "${var.app_name}-lambda-bedrock-policy"
  description = "Policy for Lambda to invoke Claude via Bedrock"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/*",
          "arn:aws:bedrock:eu-west-1:${data.aws_caller_identity.current.account_id}:inference-profile/eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "aws-marketplace:ViewSubscriptions",
          "aws-marketplace:Subscribe",
          "aws-marketplace:Unsubscribe",
          "aws-marketplace:GetEntitlements"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = "bedrock:*"
        Resource = "*"
      }
    ]
  })

  tags = {
    Name        = "${var.app_name}-lambda-bedrock-policy"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM policy for Lambda CloudWatch Logs
resource "aws_iam_policy" "lambda_logs_policy" {
  name        = "${var.app_name}-lambda-logs-policy"
  description = "Policy for Lambda to write CloudWatch Logs"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.app_name}-garmin-analyzer:*"
      }
    ]
  })

  tags = {
    Name        = "${var.app_name}-lambda-logs-policy"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# Attach policies to Lambda role
resource "aws_iam_role_policy_attachment" "lambda_secrets" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_secrets_policy.arn
}

resource "aws_iam_role_policy_attachment" "lambda_s3" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_s3_policy.arn
}

resource "aws_iam_role_policy_attachment" "lambda_bedrock" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_bedrock_policy.arn
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_logs_policy.arn
}

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${var.app_name}-garmin-analyzer"
  retention_in_days = 14

  tags = {
    Name        = "${var.app_name}-garmin-analyzer-logs"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# ECR repository for Lambda container image
resource "aws_ecr_repository" "lambda_repo" {
  name                 = "${var.app_name}-garmin-analyzer"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name        = "${var.app_name}-garmin-analyzer-ecr"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# ECR lifecycle policy for Lambda repo
resource "aws_ecr_lifecycle_policy" "lambda_repo" {
  repository = aws_ecr_repository.lambda_repo.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 5 images"
        selection = {
          tagStatus     = "any"
          countType     = "imageCountMoreThan"
          countNumber   = 5
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# Lambda function using container image
resource "aws_lambda_function" "garmin_analyzer" {
  function_name = "${var.app_name}-garmin-analyzer"
  role          = aws_iam_role.lambda_role.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.lambda_repo.repository_url}:latest"
  timeout       = 60
  memory_size   = 512

  environment {
    variables = {
      GARMIN_SECRET_ARN    = aws_secretsmanager_secret.garmin_credentials.arn
      S3_BUCKET_NAME       = aws_s3_bucket.app_data.bucket
      TRAINING_PLAN_S3_KEY = var.training_plan_s3_key
      AWS_REGION_OVERRIDE  = var.aws_region
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_secrets,
    aws_iam_role_policy_attachment.lambda_s3,
    aws_iam_role_policy_attachment.lambda_bedrock,
    aws_iam_role_policy_attachment.lambda_logs,
    aws_cloudwatch_log_group.lambda_logs
  ]

  tags = {
    Name        = "${var.app_name}-garmin-analyzer"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# EventBridge rule to trigger Lambda every 12 hours
resource "aws_cloudwatch_event_rule" "garmin_analyzer_schedule" {
  name                = "${var.app_name}-garmin-analyzer-schedule"
  description         = "Trigger Garmin analyzer Lambda every 12 hours"
  schedule_expression = "rate(12 hours)"

  tags = {
    Name        = "${var.app_name}-garmin-analyzer-schedule"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# EventBridge target for Lambda
resource "aws_cloudwatch_event_target" "garmin_analyzer_target" {
  rule      = aws_cloudwatch_event_rule.garmin_analyzer_schedule.name
  target_id = "GarminAnalyzerLambda"
  arn       = aws_lambda_function.garmin_analyzer.arn
}

# Permission for EventBridge to invoke Lambda
resource "aws_lambda_permission" "eventbridge_invoke" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.garmin_analyzer.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.garmin_analyzer_schedule.arn
}

# =============================================================================
# APP RUNNER SCHEDULER (8am–6pm UK only, to reduce cost)
# =============================================================================

data "archive_file" "apprunner_scheduler" {
  type        = "zip"
  source_file = "${path.module}/../src/lambda/apprunner_scheduler/main.py"
  output_path = "${path.module}/apprunner_scheduler.zip"
}

resource "aws_iam_role" "apprunner_scheduler_role" {
  name = "${var.app_name}-apprunner-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "apprunner_scheduler_policy" {
  name   = "apprunner-pause-resume"
  role   = aws_iam_role.apprunner_scheduler_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["apprunner:PauseService", "apprunner:ResumeService"]
        Resource = aws_apprunner_service.app.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.app_name}-apprunner-scheduler:*"
      }
    ]
  })
}

resource "aws_lambda_function" "apprunner_scheduler" {
  filename         = data.archive_file.apprunner_scheduler.output_path
  function_name    = "${var.app_name}-apprunner-scheduler"
  role             = aws_iam_role.apprunner_scheduler_role.arn
  handler          = "main.lambda_handler"
  runtime          = "python3.11"
  source_code_hash = data.archive_file.apprunner_scheduler.output_base64sha256
  timeout          = 30
  environment {
    variables = {
      APPRUNNER_SERVICE_ARN = aws_apprunner_service.app.arn
    }
  }
}

# Run at 07:00, 08:00, 17:00, 18:00 UTC to catch 8am and 6pm UK (GMT/BST)
resource "aws_cloudwatch_event_rule" "apprunner_scheduler" {
  name                = "${var.app_name}-apprunner-scheduler"
  description         = "Trigger App Runner pause/resume at 8am and 6pm UK"
  schedule_expression = "cron(0 7,8,17,18 * * ? *)"
}

resource "aws_cloudwatch_event_target" "apprunner_scheduler_target" {
  rule      = aws_cloudwatch_event_rule.apprunner_scheduler.name
  target_id = "AppRunnerScheduler"
  arn       = aws_lambda_function.apprunner_scheduler.arn
}

resource "aws_lambda_permission" "apprunner_scheduler_events" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.apprunner_scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.apprunner_scheduler.arn
}
