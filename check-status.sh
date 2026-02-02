#!/bin/bash

# Quick script to check App Runner service status

export AWS_PROFILE=prod
REGION="eu-west-1"

SERVICE_ARN=$(aws apprunner list-services --region $REGION --query 'ServiceSummaryList[?ServiceName==`secure-app`].ServiceArn' --output text 2>/dev/null)

if [ -z "$SERVICE_ARN" ]; then
    echo "Service not found"
    exit 1
fi

STATUS=$(aws apprunner describe-service --service-arn "$SERVICE_ARN" --region $REGION --query 'Service.Status' --output text)
URL=$(aws apprunner describe-service --service-arn "$SERVICE_ARN" --region $REGION --query 'Service.ServiceUrl' --output text)

echo "Status: $STATUS"
echo "URL: https://$URL"

if [ "$STATUS" = "RUNNING" ]; then
    echo ""
    echo "✅ Service is running! You can access it at: https://$URL"
elif [ "$STATUS" = "CREATE_FAILED" ] || [ "$STATUS" = "OPERATION_FAILED" ]; then
    echo ""
    echo "❌ Service creation failed. Check logs for details."
elif [ "$STATUS" = "OPERATION_IN_PROGRESS" ]; then
    echo ""
    echo "⏳ Service is still being created. This typically takes 3-5 minutes."
    echo "   Started: $(aws apprunner list-operations --service-arn "$SERVICE_ARN" --region $REGION --max-results 1 --query 'OperationSummaryList[0].StartedAt' --output text)"
fi
