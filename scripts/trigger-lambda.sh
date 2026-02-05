#!/bin/bash
#
# Manually trigger the Garmin analyzer Lambda function
#
# Usage: ./scripts/trigger-lambda.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TERRAFORM_DIR="$PROJECT_ROOT/terraform"

AWS_PROFILE="${AWS_PROFILE:-prod}"
AWS_REGION="${AWS_REGION:-eu-west-1}"

echo "Triggering Garmin analyzer Lambda..."

# Get the Lambda function name from Terraform
cd "$TERRAFORM_DIR"
FUNCTION_NAME=$(terraform output -raw garmin_lambda_name 2>/dev/null || echo "")

if [ -z "$FUNCTION_NAME" ]; then
    echo "Error: Could not get Lambda function name from Terraform"
    echo "Make sure you've run 'terraform apply' first"
    exit 1
fi

echo "Function: $FUNCTION_NAME"
echo ""

# Invoke the Lambda function
echo "Invoking Lambda function..."
OUTPUT_FILE="/tmp/lambda-invoke-output.json"

aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --payload '{}' \
    "$OUTPUT_FILE"

echo ""
echo "✅ Lambda invocation complete!"
echo ""
echo "Response:"
cat "$OUTPUT_FILE" | python3 -m json.tool 2>/dev/null || cat "$OUTPUT_FILE"
echo ""

# Check for errors
if grep -q '"FunctionError"' "$OUTPUT_FILE"; then
    echo "⚠️  Lambda execution had an error. Check CloudWatch logs for details."
    echo "   Log group: /aws/lambda/$FUNCTION_NAME"
else
    echo "✅ Lambda executed successfully!"
fi
