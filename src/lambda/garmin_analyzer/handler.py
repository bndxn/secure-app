"""
Garmin Run Analyzer Lambda Function

This Lambda function:
1. Retrieves Garmin credentials from AWS Secrets Manager
2. Connects to Garmin Connect and fetches recent activities (last 7 days)
3. If a run occurred in the last 12 hours, triggers analysis
4. Reads the training plan from S3
5. Sends the data to Claude for: (a) review of all runs in last 7 days vs plan, (b) look-ahead next 3 days with suggested paces
6. Saves the analysis output to S3
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from get_from_garmin import get_recent_garmin_activities

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
SECRET_ARN = os.environ.get("GARMIN_SECRET_ARN")
S3_BUCKET = os.environ.get("S3_BUCKET_NAME")
TRAINING_PLAN_KEY = os.environ.get("TRAINING_PLAN_S3_KEY", "training-plan.txt")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "run-analysis/")
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")

# Bedrock model ID for Claude Sonnet 4.5 (EU cross-region inference)
BEDROCK_MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"

# Time windows
TRIGGER_HOURS = 12  # Only analyze if run in last 12 hours
CONTEXT_DAYS = 7    # Include all runs from last 7 days for review and display



def get_garmin_credentials():
    """Retrieve Garmin credentials from AWS Secrets Manager."""
    client = boto3.client("secretsmanager", region_name=AWS_REGION)
    try:
        response = client.get_secret_value(SecretId=SECRET_ARN)
        secret = json.loads(response["SecretString"])
        return secret["username"], secret["password"]
    except ClientError as e:
        logger.error(f"Failed to retrieve Garmin credentials: {e}")
        raise


def set_garmin_env_credentials(username, password):
    """Set Garmin credentials as environment variables for get_from_garmin."""
    os.environ["GARMIN_USERNAME"] = username
    os.environ["GARMIN_PASSWORD"] = password


def filter_activities_by_date(activities, days=CONTEXT_DAYS):
    """Filter activities to only include those from the last N days."""
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
    filtered = []
    for activity in activities:
        start_time_str = activity.get("startTimeLocal")
        if not start_time_str:
            continue
        try:
            start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
            start_time = start_time.replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning(f"Could not parse start time: {start_time_str}")
            continue
        if start_time >= cutoff_time:
            filtered.append(activity)
    return filtered


def filter_recent_runs(activities, hours=TRIGGER_HOURS):
    """Filter activities to only include runs from the last N hours."""
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent_runs = []
    for activity in activities:
        if activity.get("activityType") != "running":
            continue
        start_time_str = activity.get("startTimeLocal")
        if not start_time_str:
            continue
        try:
            start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
            start_time = start_time.replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning(f"Could not parse start time: {start_time_str}")
            continue
        if start_time >= cutoff_time:
            recent_runs.append(activity)
    return recent_runs


def get_training_plan(s3_client):
    """Retrieve the training plan from S3."""
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=TRAINING_PLAN_KEY)
        training_plan = response["Body"].read().decode("utf-8")
        logger.info("Successfully retrieved training plan from S3")
        return training_plan
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            logger.warning("Training plan not found in S3, using default")
            return "No specific training plan provided."
        raise



def format_runs_as_html_bedrock(bedrock_client, running_activities):
    """Format recent runs as HTML ul/li using Bedrock."""
    if not running_activities:
        return "<ul><li>No recent runs.</li></ul>"

    runs_list = [
        {
            "startTimeLocal": a.get("startTimeLocal"),
            "name": a.get("name"),
            "distanceKm": a.get("distanceKm"),
            "durationMin": a.get("durationMin"),
            "intervals": a.get("intervals"),
        }
        for a in running_activities[:15]
    ]
    runs_json = json.dumps(runs_list, indent=2)

    prompt = f"""Convert these running activities into a single HTML unordered list (<ul>). Rules:
- One <li> per run. Format: [Date from startTimeLocal YYYY-MM-DD] - [name], [distanceKm] km, [durationMin] as MM:SS, pace if derivable, avg HR if in intervals.
- If an activity has multiple "Active" intervals (intervals array), output one parent <li> with a nested <ul> of interval lines.
- Output valid HTML only: just the <ul> and <li> elements. No <html>, <head>, <body>. No markdown.
- Convert duration minutes to MM:SS. Omit rest intervals (very short or slow). Use "?" for missing pace/HR.
Activities JSON:
{runs_json}"""

    try:
        response = bedrock_client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            }),
        )
        body = json.loads(response["body"].read())
        html = (body.get("content") or [{}])[0].get("text", "").strip()
        if html.startswith("```"):
            lines = html.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            html = "\n".join(lines)
        return html or "<ul><li>No runs.</li></ul>"
    except ClientError as e:
        logger.warning(f"Bedrock format_runs failed: {e}, using fallback")
        return "<ul><li>Run list unavailable.</li></ul>"


def analyze_runs_with_claude(bedrock_client, all_runs_context, training_plan):
    """
    Send run data to Claude via Bedrock for analysis.

    Args:
        all_runs_context: Formatted string of all runs in the last 7 days
        training_plan: The user's training plan

    Returns the analysis text: (1) short narrative review, (2) "Next three days" list with relative dates.
    """
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%A %d %B")  # e.g. Monday 24 February
    prompt = f"""You are an expert running coach. Today's date: {today_str}.

Training Plan:
{training_plan}

All Runs (Last 7 Days):
{all_runs_context}

Write exactly two parts. Use plain text only (no markdown, no **).

1) The last week: One short paragraph only. Be encouraging. Say how many runs they completed vs how many were planned (e.g. "Good job on completing 5/6 of your runs"). Say if overall paces are in line with the plan. Sometimes the runner might move workouts around or skip a workout. Report on the total distance run and the total distance planned. Mention only 1–2 specific concerns if relevant (e.g. "on your 10K your HR was higher than it should be"). Keep it to 2–3 sentences.

2) The next three days: Start with the line "Next three days:" then list the next 3 calendar days, each on its own line with a dash. Use "today (date)", "tomorrow (date)", and the day name for the third (e.g. "Thursday 26th"). Sometimes the runner might move workouts around or skip a workout. Consider what workouts are scheduled and whether they need to be moved around slightly. For each day give only: the workout type and a brief pace or effort hint (e.g. "16.1km slow pace, e.g. 5-6:00" or "cross-training, relaxed" or "rest: no running"). Do not include warm-up/cool-down instructions or long explanations. One short line per day.

Example style for part 2:
Next three days:
- today (24th): cross-training, relaxed
- tomorrow (25th): 16.1km slow pace, e.g. 5-6:00
- Thursday (26th): easy / recovery

Maximum 250 words total."""

    try:
        response = bedrock_client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 512,  # ~180 words; prompt asks for concise output
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            })
        )
        
        response_body = json.loads(response["body"].read())
        analysis = response_body["content"][0]["text"]
        logger.info("Successfully received analysis from Claude")
        return analysis
        
    except ClientError as e:
        logger.error(f"Failed to invoke Bedrock: {e}")
        raise




def save_analysis_to_s3(s3_client, trigger_run, analysis, all_activities, recent_runs_html=None):
    """Save the analysis output to S3. Stores all runs from last 7 days for display."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    key = f"{OUTPUT_PREFIX}{timestamp}_analysis.json"

    running_activities = [a for a in all_activities if a.get("activityType") == "running"]
    running_activities.sort(
        key=lambda x: x.get("startTimeLocal", ""),
        reverse=True,
    )

    output = {
        "timestamp": timestamp,
        "analyzed_run": trigger_run,
        "recent_runs": running_activities,  # All runs from last 7 days
        "analysis": analysis,
        "suggestion": analysis,  # Web app reads this key
        "context_activities_count": len(running_activities),
    }
    if recent_runs_html:
        output["recent_runs_html"] = recent_runs_html
    
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(output, indent=2),
            ContentType="application/json"
        )
        logger.info(f"Successfully saved analysis to s3://{S3_BUCKET}/{key}")
        return key
    except ClientError as e:
        logger.error(f"Failed to save analysis to S3: {e}")
        raise


def lambda_handler(event, context):
    """Main Lambda handler."""
    logger.info("Starting Garmin Run Analyzer")

    s3_client = boto3.client("s3", region_name=AWS_REGION)
    bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    username, password = get_garmin_credentials()
    set_garmin_env_credentials(username, password)

    logger.info("Fetching recent Garmin activities...")
    activities_json = get_recent_garmin_activities(n_recent=30)
    all_activities_raw = json.loads(activities_json)

    if isinstance(all_activities_raw, dict) and "error" in all_activities_raw:
        logger.error(f"Error fetching activities: {all_activities_raw.get('error')}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": all_activities_raw.get("error")}),
        }
    if not isinstance(all_activities_raw, list):
        logger.error(f"Unexpected response format: {type(all_activities_raw)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Unexpected response format from Garmin API"}),
        }

    all_activities = filter_activities_by_date(all_activities_raw, days=CONTEXT_DAYS)
    logger.info(f"Fetched {len(all_activities_raw)} total activities, {len(all_activities)} from last {CONTEXT_DAYS} days")

    recent_runs = filter_recent_runs(all_activities, hours=TRIGGER_HOURS)
    if not recent_runs:
        logger.info(f"No runs found in the last {TRIGGER_HOURS} hours. Exiting.")
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": f"No runs in the last {TRIGGER_HOURS} hours",
                "runs_analyzed": 0,
                "total_activities_fetched": len(all_activities_raw),
            }),
        }

    training_plan = get_training_plan(s3_client)
    running_activities_7d = [a for a in all_activities if a.get("activityType") == "running"]
    recent_runs_html = format_runs_as_html_bedrock(bedrock_client, running_activities_7d)

    logger.info("Requesting coach analysis (review last 7 days + look-ahead next 3 days)")
    analysis = analyze_runs_with_claude(
        bedrock_client,
        recent_runs_html,
        training_plan,
    )

    trigger_run = recent_runs[0]
    output_key = save_analysis_to_s3(
        s3_client, trigger_run, analysis, all_activities, recent_runs_html=recent_runs_html
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Coach analysis complete (last 7 days review + next 3 days look-ahead)",
            "runs_analyzed": len(recent_runs),
            "runs_in_context": len(running_activities_7d),
            "total_activities_fetched": len(all_activities_raw),
            "output_key": output_key,
        }),
    }
