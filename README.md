# Secure App - Flask on AWS App Runner

A modern Flask application deployed to AWS App Runner using Infrastructure as Code (Terraform). The application loads data from an S3 bucket and is fully containerized.

## Architecture

- **Flask Application**: Python web application with S3 integration
- **Docker**: Containerized application using Docker
- **AWS App Runner**: Serverless container service for running the application
- **AWS S3**: Object storage for application data
- **AWS ECR**: Container registry for Docker images
- **Terraform**: Infrastructure as Code for repeatable deployments
- **IAM Roles**: Secure access to S3 bucket with least privilege

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform >= 1.0 installed
- Docker installed
- Python 3.11+ (for local development)
- Make (optional, for using Makefile commands)

## AWS Account Setup

### 1. Configure AWS CLI

```bash
aws configure --profile prod
# Or: aws configure sso --profile prod
export AWS_PROFILE=prod
aws sts get-caller-identity  # Verify access
```

### 2. Required IAM Permissions

Your IAM user/role needs permissions for:
- **S3**: Create buckets, manage objects (for app data and Terraform state)
- **ECR**: Full access for container registry
- **App Runner**: Full access for service deployment
- **IAM**: Create roles and policies (for App Runner service roles)
- **DynamoDB**: For Terraform state locking (optional but recommended)
- **CloudWatch Logs**: For application logging

**Quick Option**: Attach `PowerUserAccess` managed policy (for development/testing).

**Production Option**: Use the complete policy in `terraform/iam-policy-terraform-user.json`.

### 3. Terraform State Storage (Recommended)

For production, store Terraform state in S3 with DynamoDB locking:

```bash
./scripts/setup-terraform-backend.sh
```

This creates an S3 bucket and DynamoDB table for state management.

### 4. Verify Setup

```bash
./scripts/verify-aws-setup.sh
```

## Quick Start

### 1. Configure Terraform Variables

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` and set:
- `s3_bucket_name`: Must be globally unique
- `aws_region`: Your preferred AWS region (App Runner available in: us-east-1, us-west-2, eu-west-1, ap-southeast-1)

### 2. Deploy Infrastructure

```bash
make terraform-init
make terraform-plan
make terraform-apply
```

Or manually:
```bash
cd terraform
terraform init
terraform plan
terraform apply
```

### 3. Build and Deploy Application

```bash
make deploy
```

Or manually:
```bash
docker build -t secure-app:latest .
ECR_REPO=$(cd terraform && terraform output -raw ecr_repository_url)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $ECR_REPO
docker tag secure-app:latest $ECR_REPO:latest
docker push $ECR_REPO:latest
```

### 4. Access Your Application

```bash
cd terraform
terraform output app_runner_service_url
```

## Local Development

### Run with Docker

```bash
docker build -t secure-app:latest .
docker run -p 8000:8000 \
  -e S3_BUCKET_NAME=your-bucket-name \
  -e AWS_ACCESS_KEY_ID=your-key \
  -e AWS_SECRET_ACCESS_KEY=your-secret \
  secure-app:latest
```

### Run with Python

```bash
pip install -r requirements.txt
export S3_BUCKET_NAME=your-bucket-name
export AWS_ACCESS_KEY_ID=your-key
export AWS_SECRET_ACCESS_KEY=your-secret
python app.py
```

Visit `http://localhost:8000` to see the application.

## Application Endpoints

- `GET /` - Homepage with S3 bucket information
- `GET /health` - Health check endpoint
- `GET /api/files` - List all files in S3 bucket
- `GET /api/files/<filename>` - Get file content from S3

## Infrastructure Components

### IAM Roles

1. **App Runner Instance Role**: Used by the running application to access S3
2. **App Runner Access Role**: Used by App Runner to pull images from ECR

### S3 Bucket

- Versioning enabled
- Server-side encryption (AES256)
- Public access blocked

### App Runner Service

- Auto-deployment enabled
- Health checks on `/health` endpoint
- Environment variables: `S3_BUCKET_NAME`, `AWS_REGION`

## Updating the Application

1. Make changes to `app.py` or other files
2. Build and push: `make push`
3. App Runner automatically deploys the new image

## Cleanup

```bash
make terraform-destroy
```

**Note**: This deletes the S3 bucket and all contents. Backup important data first.

## Troubleshooting

### Access Denied Errors

- **IAM Permissions**: Ensure your user has S3, ECR, App Runner, IAM, and DynamoDB permissions. See `terraform/iam-policy-terraform-user.json` for complete policy.
- **Service Control Policies (SCPs)**: If in AWS Organizations, ensure SCPs allow required services. Contact your organization administrator.
- **PassRole**: Verify `iam:PassRole` permission with service restriction for App Runner.

### Service Not Available

- App Runner may not be in your region. Use: `us-east-1`, `us-west-2`, `eu-west-1`, or `ap-southeast-1`.

### Bucket Name Exists

- S3 bucket names are globally unique. Choose a unique name in `terraform.tfvars`.

### App Runner Service Fails

- Check CloudWatch logs
- Verify IAM role permissions
- Ensure Docker image is accessible in ECR
- Check health check endpoint responds

### Image Pull Errors

- Verify ECR repository exists
- Check App Runner access role has ECR permissions
- Ensure image tag matches (default: `latest`)

## Security Considerations

- IAM roles follow least privilege (read-only S3 access)
- S3 bucket has public access blocked
- Container images scanned on push to ECR
- All resources tagged for cost tracking

## Cost Optimization

- App Runner: ~$0.007 per vCPU-hour + $0.0008 per GB-hour
- ECR: $0.10 per GB/month
- S3: $0.023 per GB/month
- Estimated small app: ~$50-100/month

## License

This project is provided as-is for demonstration purposes.
