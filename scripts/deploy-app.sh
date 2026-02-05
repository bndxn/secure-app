#!/bin/bash
#
# Manually trigger App Runner deployment
#
# This script manually triggers a deployment of the App Runner service
# after pushing a new image to ECR.
#
# Usage: ./scripts/deploy-app.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TERRAFORM_DIR="$PROJECT_ROOT/terraform"

AWS_PROFILE="${AWS_PROFILE:-prod}"
AWS_REGION="${AWS_REGION:-eu-west-1}"

echo "Triggering App Runner deployment..."

# Get the service ARN from Terraform
cd "$TERRAFORM_DIR"
SERVICE_ARN=$(terraform output -raw app_runner_service_arn 2>/dev/null || echo "")

if [ -z "$SERVICE_ARN" ]; then
    echo "Error: Could not get App Runner service ARN from Terraform"
    echo "Make sure you've run 'terraform apply' first"
    exit 1
fi

echo "Service ARN: $SERVICE_ARN"
echo ""

# Start a manual deployment
echo "Starting manual deployment..."
aws apprunner start-deployment \
    --service-arn "$SERVICE_ARN" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE"

echo ""
echo "✅ Deployment triggered successfully!"
echo ""
echo "To check deployment status, run:"
echo "  aws apprunner describe-service \\"
echo "    --service-arn $SERVICE_ARN \\"
echo "    --region $AWS_REGION \\"
echo "    --profile $AWS_PROFILE \\"
echo "    --query 'Service.Status' \\"
echo "    --output text"
