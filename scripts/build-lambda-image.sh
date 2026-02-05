#!/bin/bash
#
# Build and Push Lambda Container Image
#
# This script builds the Garmin analyzer Lambda container image
# and pushes it to ECR.
#
# Usage: ./scripts/build-lambda-layer.sh
#
# Prerequisites:
#   - AWS CLI configured with appropriate credentials
#   - Docker installed and running
#   - ECR repository created (run terraform apply first)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LAMBDA_DIR="$PROJECT_ROOT/lambda/garmin_analyzer"

# Configuration
AWS_PROFILE="${AWS_PROFILE:-prod}"
AWS_REGION="${AWS_REGION:-eu-west-1}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "Building Garmin Analyzer Lambda container..."

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --query Account --output text)
if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo "Error: Could not get AWS account ID. Check your AWS credentials."
    exit 1
fi

# ECR repository name (must match Terraform)
ECR_REPO_NAME="secure-app-garmin-analyzer"
ECR_REPO_URL="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME"

echo "AWS Account: $AWS_ACCOUNT_ID"
echo "ECR Repository: $ECR_REPO_URL"
echo ""

# Authenticate Docker to ECR
echo "Authenticating Docker to ECR..."
aws ecr get-login-password --region "$AWS_REGION" --profile "$AWS_PROFILE" | \
    docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# Build the container image using buildx for proper cross-platform support
echo "Building Docker image..."
cd "$LAMBDA_DIR"

# Use buildx to build and push directly (handles cross-platform better on Apple Silicon)
docker buildx build \
    --platform linux/amd64 \
    --provenance=false \
    --push \
    -f Dockerfile.lambda \
    -t "$ECR_REPO_URL:$IMAGE_TAG" \
    .

echo ""
echo "Successfully built and pushed Lambda container image!"
echo "  Image: $ECR_REPO_URL:$IMAGE_TAG"
echo ""
echo "To update the Lambda function, run:"
echo "  aws lambda update-function-code \\"
echo "    --function-name secure-app-garmin-analyzer \\"
echo "    --image-uri $ECR_REPO_URL:$IMAGE_TAG \\"
echo "    --profile $AWS_PROFILE"
