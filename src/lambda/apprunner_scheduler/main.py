"""
Lambda: pause App Runner at 6pm UK, resume at 8am UK to reduce cost.
Uses Europe/London so BST is handled correctly.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3

UK_TZ = ZoneInfo("Europe/London")
RESUME_HOUR = 8   # 8am UK
PAUSE_HOUR = 18  # 6pm UK


def lambda_handler(event, context):
    service_arn = os.environ["APPRUNNER_SERVICE_ARN"]
    client = boto3.client("apprunner")
    now_uk = datetime.now(UK_TZ)
    hour = now_uk.hour

    if hour == RESUME_HOUR:
        client.resume_service(ServiceArn=service_arn)
        return {"action": "resume", "reason": "8am UK"}
    if hour == PAUSE_HOUR:
        client.pause_service(ServiceArn=service_arn)
        return {"action": "pause", "reason": "6pm UK"}
    return {"action": "none", "hour_uk": hour}
