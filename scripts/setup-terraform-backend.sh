#!/bin/bash

# Script to set up Terraform backend (S3 + DynamoDB)
# This is a one-time setup for your AWS account

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== Terraform Backend Setup ===${NC}\n"

# Get configuration
read -p "AWS Region [us-east-1]: " REGION
REGION=${REGION:-us-east-1}

read -p "S3 bucket name for Terraform state (must be globally unique): " STATE_BUCKET
if [ -z "$STATE_BUCKET" ]; then
    echo -e "${RED}Error: State bucket name is required${NC}"
    exit 1
fi

read -p "DynamoDB table name for state locking [terraform-state-lock]: " STATE_TABLE
STATE_TABLE=${STATE_TABLE:-terraform-state-lock}

# Show available profiles and their accounts
echo -e "${YELLOW}Available AWS profiles:${NC}"
if [ -f ~/.aws/credentials ]; then
    for profile in $(grep -E "^\[.*\]" ~/.aws/credentials | sed 's/\[//g' | sed 's/\]//g'); do
        PROFILE_ACCOUNT=$(AWS_PROFILE=$profile aws sts get-caller-identity --query 'Account' --output text 2>/dev/null || echo "unknown")
        if [ "$profile" = "default" ]; then
            echo "  - default (Account: $PROFILE_ACCOUNT)"
        else
            echo "  - $profile (Account: $PROFILE_ACCOUNT)"
        fi
    done
fi

read -p "AWS Profile [enter 'prod' for ben-terraform account, or press Enter for default]: " AWS_PROFILE_INPUT
# Only set AWS_PROFILE if user provided a value
if [ -n "$AWS_PROFILE_INPUT" ]; then
    export AWS_PROFILE="$AWS_PROFILE_INPUT"
    PROFILE_DISPLAY="$AWS_PROFILE_INPUT"
else
    # Use default profile explicitly
    export AWS_PROFILE="default"
    PROFILE_DISPLAY="default"
fi

# Verify AWS identity before proceeding
echo -e "\n${YELLOW}Verifying AWS credentials...${NC}"
AWS_IDENTITY=$(aws sts get-caller-identity 2>&1)
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to get AWS identity${NC}"
    echo "$AWS_IDENTITY"
    exit 1
fi

AWS_ACCOUNT=$(echo "$AWS_IDENTITY" | grep -o '"Account": "[^"]*"' | cut -d'"' -f4)
AWS_ARN=$(echo "$AWS_IDENTITY" | grep -o '"Arn": "[^"]*"' | cut -d'"' -f4)

echo -e "${GREEN}Current AWS Identity:${NC}"
echo "  Account: $AWS_ACCOUNT"
echo "  ARN: $AWS_ARN"

echo -e "\n${YELLOW}Configuration:${NC}"
echo "  Region: $REGION"
echo "  State Bucket: $STATE_BUCKET"
echo "  Lock Table: $STATE_TABLE"
echo "  AWS Profile: $PROFILE_DISPLAY"

read -p "Continue with this AWS account? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled"
    exit 1
fi

# Verify credentials are still correct before proceeding
CURRENT_IDENTITY=$(aws sts get-caller-identity --query 'Account' --output text 2>/dev/null)
if [ "$CURRENT_IDENTITY" != "$AWS_ACCOUNT" ]; then
    echo -e "${RED}Error: AWS account changed during execution!${NC}"
    echo "  Expected: $AWS_ACCOUNT"
    echo "  Current: $CURRENT_IDENTITY"
    exit 1
fi

# Check if bucket exists
if aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null; then
    echo -e "${YELLOW}Bucket $STATE_BUCKET already exists${NC}"
else
    echo -e "${GREEN}Creating S3 bucket: $STATE_BUCKET${NC}"
    
    # Create bucket (handle different regions)
    if [ "$REGION" = "us-east-1" ]; then
        aws s3api create-bucket \
            --bucket "$STATE_BUCKET" \
            --region "$REGION"
    else
        aws s3api create-bucket \
            --bucket "$STATE_BUCKET" \
            --region "$REGION" \
            --create-bucket-configuration LocationConstraint="$REGION"
    fi
    
    echo -e "${GREEN}Enabling versioning...${NC}"
    aws s3api put-bucket-versioning \
        --bucket "$STATE_BUCKET" \
        --versioning-configuration Status=Enabled
    
    echo -e "${GREEN}Enabling encryption...${NC}"
    aws s3api put-bucket-encryption \
        --bucket "$STATE_BUCKET" \
        --server-side-encryption-configuration '{
            "Rules": [{
                "ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "AES256"
                }
            }]
        }'
    
    echo -e "${GREEN}Blocking public access...${NC}"
    aws s3api put-public-access-block \
        --bucket "$STATE_BUCKET" \
        --public-access-block-configuration \
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
fi

# Check if DynamoDB table exists
if aws dynamodb describe-table --table-name "$STATE_TABLE" --region "$REGION" 2>/dev/null; then
    echo -e "${YELLOW}DynamoDB table $STATE_TABLE already exists${NC}"
else
    echo -e "${GREEN}Creating DynamoDB table: $STATE_TABLE${NC}"
    aws dynamodb create-table \
        --table-name "$STATE_TABLE" \
        --attribute-definitions AttributeName=LockID,AttributeType=S \
        --key-schema AttributeName=LockID,KeyType=HASH \
        --billing-mode PAY_PER_REQUEST \
        --region "$REGION" \
        > /dev/null
    
    echo -e "${YELLOW}Waiting for table to be active...${NC}"
    aws dynamodb wait table-exists \
        --table-name "$STATE_TABLE" \
        --region "$REGION"
fi

# Create backend.tf file
echo -e "\n${GREEN}Creating backend.tf file...${NC}"

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Get the project root (parent of scripts directory)
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_FILE="$PROJECT_ROOT/terraform/backend.tf"

cat > "$BACKEND_FILE" <<EOF
terraform {
  backend "s3" {
    bucket         = "$STATE_BUCKET"
    key            = "secure-app/terraform.tfstate"
    region         = "$REGION"
    dynamodb_table = "$STATE_TABLE"
    encrypt        = true
EOF

if [ -n "$AWS_PROFILE_INPUT" ]; then
    echo "    profile        = \"$AWS_PROFILE_INPUT\"" >> "$BACKEND_FILE"
fi

echo "  }" >> "$BACKEND_FILE"
echo "}" >> "$BACKEND_FILE"

echo -e "\n${GREEN}✓ Backend setup complete!${NC}"
echo -e "\n${YELLOW}Backend configuration created at: $BACKEND_FILE${NC}"
echo -e "\n${YELLOW}Next steps:${NC}"
echo "  1. Review terraform/backend.tf"
echo "  2. Run: cd terraform && terraform init"
echo "  3. Configure terraform.tfvars"
echo "  4. Deploy: ./deploy.sh"
