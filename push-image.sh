#!/bin/bash

# Script to build and push Docker image to ECR

set -e

export AWS_PROFILE=prod
REGION="eu-west-1"

# Get ECR repository URL from Terraform
cd terraform
ECR_REPO=$(terraform output -raw ecr_repository_url)
cd ..

echo "ECR Repository: $ECR_REPO"
echo "Region: $REGION"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker is not running. Please start Docker Desktop and try again."
    exit 1
fi

# Build the Docker image for linux/amd64 (App Runner requirement)
echo "Building Docker image for linux/amd64..."
docker buildx build --platform linux/amd64 -t secure-app:latest --load .

# Login to ECR
echo "Logging in to ECR..."
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR_REPO

# Tag the image
echo "Tagging image..."
docker tag secure-app:latest $ECR_REPO:latest

# Push the image
echo "Pushing image to ECR..."
docker push $ECR_REPO:latest

echo ""
echo "✅ Image pushed successfully!"
echo "App Runner should automatically deploy the new image (if auto-deploy is enabled)."
echo ""
echo "To check deployment status, run:"
echo "  cd terraform && ./run-terraform.sh output app_runner_service_url"
