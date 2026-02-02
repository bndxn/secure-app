#!/bin/bash

# Wrapper script to ensure Terraform always uses the prod profile

set -e

export AWS_PROFILE=prod

# Verify we're using the correct account
echo "Verifying AWS account..."
IDENTITY=$(aws sts get-caller-identity)
ACCOUNT=$(echo "$IDENTITY" | grep -o '"Account": "[^"]*"' | cut -d'"' -f4)
ARN=$(echo "$IDENTITY" | grep -o '"Arn": "[^"]*"' | cut -d'"' -f4)

echo "Account: $ACCOUNT"
echo "Identity: $ARN"

if [ "$ACCOUNT" != "462532071155" ]; then
    echo "ERROR: Wrong AWS account! Expected 462532071155, got $ACCOUNT"
    echo "Please check your AWS_PROFILE configuration"
    exit 1
fi

# Run terraform with the provided arguments
cd "$(dirname "$0")"
terraform "$@"
