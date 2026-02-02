#!/bin/bash

# Deployment script for Secure App
# This script automates the deployment process

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
AWS_REGION=${AWS_REGION:-us-east-1}
APP_NAME=${APP_NAME:-secure-app}

echo -e "${GREEN}Starting deployment of ${APP_NAME}...${NC}"

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

if ! command -v terraform &> /dev/null; then
    echo -e "${RED}Error: Terraform is not installed${NC}"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed${NC}"
    exit 1
fi

if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI is not installed${NC}"
    exit 1
fi

# Check if terraform.tfvars exists
if [ ! -f "terraform/terraform.tfvars" ]; then
    echo -e "${YELLOW}Warning: terraform.tfvars not found. Creating from example...${NC}"
    cp terraform/terraform.tfvars.example terraform/terraform.tfvars
    echo -e "${RED}Please edit terraform/terraform.tfvars and set your S3 bucket name (must be globally unique)${NC}"
    exit 1
fi

# Step 1: Initialize Terraform
echo -e "${GREEN}Step 1: Initializing Terraform...${NC}"
cd terraform
terraform init

# Step 2: Plan Terraform changes
echo -e "${GREEN}Step 2: Planning Terraform changes...${NC}"
terraform plan

# Ask for confirmation
read -p "Do you want to apply these changes? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Deployment cancelled${NC}"
    exit 1
fi

# Step 3: Apply Terraform
echo -e "${GREEN}Step 3: Applying Terraform changes...${NC}"
terraform apply -auto-approve

# Get ECR repository URL
ECR_REPO=$(terraform output -raw ecr_repository_url)
if [ -z "$ECR_REPO" ]; then
    echo -e "${RED}Error: Could not get ECR repository URL${NC}"
    exit 1
fi

cd ..

# Step 4: Build Docker image
echo -e "${GREEN}Step 4: Building Docker image...${NC}"
docker build -t ${APP_NAME}:latest .

# Step 5: Login to ECR
echo -e "${GREEN}Step 5: Logging in to ECR...${NC}"
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_REPO}

# Step 6: Tag and push image
echo -e "${GREEN}Step 6: Pushing Docker image to ECR...${NC}"
docker tag ${APP_NAME}:latest ${ECR_REPO}:latest
docker push ${ECR_REPO}:latest

# Step 7: Get service URL
echo -e "${GREEN}Step 7: Deployment complete!${NC}"
SERVICE_URL=$(cd terraform && terraform output -raw app_runner_service_url)
echo -e "${GREEN}Your application is available at: ${SERVICE_URL}${NC}"
echo -e "${YELLOW}Note: It may take a few minutes for App Runner to deploy the new image${NC}"
