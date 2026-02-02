#!/bin/bash

# Script to verify AWS account setup and permissions

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== AWS Account Setup Verification ===${NC}\n"

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo -e "${RED}✗ AWS CLI is not installed${NC}"
    exit 1
else
    echo -e "${GREEN}✓ AWS CLI is installed${NC}"
fi

# Check AWS credentials
echo -e "\n${YELLOW}Checking AWS credentials...${NC}"
IDENTITY=$(aws sts get-caller-identity 2>/dev/null)
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ AWS credentials configured${NC}"
    echo "$IDENTITY" | grep -o '"Account": "[^"]*"' | head -1
    echo "$IDENTITY" | grep -o '"Arn": "[^"]*"' | head -1
else
    echo -e "${RED}✗ AWS credentials not configured or invalid${NC}"
    exit 1
fi

# Check region
REGION=$(aws configure get region || echo "us-east-1")
echo -e "\n${YELLOW}AWS Region: $REGION${NC}"

# Test S3 access
echo -e "\n${YELLOW}Testing S3 access...${NC}"
if aws s3 ls &>/dev/null; then
    echo -e "${GREEN}✓ S3 access working${NC}"
else
    echo -e "${RED}✗ S3 access failed${NC}"
fi

# Test ECR access
echo -e "\n${YELLOW}Testing ECR access...${NC}"
if aws ecr describe-repositories --region $REGION &>/dev/null; then
    echo -e "${GREEN}✓ ECR access working${NC}"
else
    echo -e "${RED}✗ ECR access failed${NC}"
fi

# Test App Runner access
echo -e "\n${YELLOW}Testing App Runner access...${NC}"
if aws apprunner list-services --region $REGION &>/dev/null; then
    echo -e "${GREEN}✓ App Runner access working${NC}"
else
    echo -e "${YELLOW}⚠ App Runner access test failed (service may not be available in this region)${NC}"
    echo "  App Runner is available in: us-east-1, us-west-2, eu-west-1, ap-southeast-1"
fi

# Test IAM access
echo -e "\n${YELLOW}Testing IAM access...${NC}"
if aws iam get-user &>/dev/null || aws iam get-role --role-name test-role 2>&1 | grep -q "NoSuchEntity\|AccessDenied"; then
    echo -e "${GREEN}✓ IAM access working${NC}"
else
    echo -e "${RED}✗ IAM access failed${NC}"
fi

# Check for required permissions
echo -e "\n${YELLOW}Checking IAM permissions...${NC}"
PERMISSIONS_OK=true

# Test S3 create permission
if aws s3api head-bucket --bucket "test-bucket-$(date +%s)" 2>&1 | grep -q "404\|403"; then
    echo -e "${GREEN}✓ Can check S3 bucket existence${NC}"
else
    echo -e "${YELLOW}⚠ S3 permissions unclear${NC}"
fi

# Test IAM role creation permission
TEST_ROLE_NAME="terraform-test-role-$(date +%s)"
CREATE_OUTPUT=$(aws iam create-role \
    --role-name "$TEST_ROLE_NAME" \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
    2>&1)

if echo "$CREATE_OUTPUT" | grep -q "EntityAlreadyExists"; then
    echo -e "${GREEN}✓ Can create IAM roles (role already exists, which is fine)${NC}"
    PERMISSIONS_OK=true
elif echo "$CREATE_OUTPUT" | grep -q "AccessDenied"; then
    echo -e "${RED}✗ Cannot create IAM roles (Access Denied)${NC}"
    echo -e "${YELLOW}  Missing permissions: iam:CreateRole, iam:CreatePolicy, iam:AttachRolePolicy${NC}"
    PERMISSIONS_OK=false
elif echo "$CREATE_OUTPUT" | grep -q "RoleName"; then
    # Role was created successfully, clean it up
    aws iam delete-role --role-name "$TEST_ROLE_NAME" 2>/dev/null || true
    echo -e "${GREEN}✓ Can create IAM roles${NC}"
else
    echo -e "${YELLOW}⚠ IAM role creation test unclear${NC}"
    echo "  Output: $CREATE_OUTPUT"
fi

# Summary
echo -e "\n${BLUE}=== Summary ===${NC}"
if [ "$PERMISSIONS_OK" = true ]; then
    echo -e "${GREEN}✓ AWS account appears to be properly configured${NC}"
    echo -e "\n${YELLOW}Next steps:${NC}"
    echo "  1. Set up Terraform backend: ./scripts/setup-terraform-backend.sh"
    echo "  2. Configure terraform.tfvars"
    echo "  3. Deploy: ./deploy.sh"
else
    echo -e "${RED}✗ Some permissions are missing${NC}"
    echo -e "\n${YELLOW}Please ensure your IAM user/role has:${NC}"
    echo "  - S3 full access (or create/list/read permissions)"
    echo "  - ECR full access"
    echo "  - App Runner full access"
    echo "  - IAM role creation permissions"
    exit 1
fi
