"""
Garmin Run Analyzer Lambda Function

This Lambda function:
1. Retrieves Garmin credentials from AWS Secrets Manager
2. Connects to Garmin Connect and fetches recent activities (last 7 days)
3. If a run occurred in the last 12 hours, triggers analysis
4. Reads the training plan from S3
5. Sends the data to Claude Sonnet 4.5 via AWS Bedrock for analysis
6. Saves the analysis output to S3
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from garmin_activities import get_recent_garmin_activities

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
CONTEXT_DAYS = 7    # Include last 7 days of runs for context


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
    """Set Garmin credentials as environment variables for get_from_garmin module."""
    os.environ["GARMIN_USERNAME"] = username
    os.environ["GARMIN_PASSWORD"] = password


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


def filter_activities_by_date(activities, days=CONTEXT_DAYS):
    """Filter activities to only include those from the last N days."""
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
    filtered = []
    
    for activity in activities:
        # Parse start time
        start_time_str = activity.get("startTimeLocal")
        if not start_time_str:
            continue
            
        try:
            # Parse format like "2024-01-15 10:30:00"
            start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
            start_time = start_time.replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning(f"Could not parse start time: {start_time_str}")
            continue
        
        # Check if within date window
        if start_time >= cutoff_time:
            filtered.append(activity)
    
    return filtered


def filter_recent_runs(activities, hours=TRIGGER_HOURS):
    """Filter activities to only include runs from the last N hours."""
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent_runs = []
    
    for activity in activities:
        # Only process running activities
        if activity.get("activityType") != "running":
            continue
            
        # Parse start time
        start_time_str = activity.get("startTimeLocal")
        if not start_time_str:
            continue
            
        try:
            # Parse format like "2024-01-15 10:30:00"
            start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
            start_time = start_time.replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning(f"Could not parse start time: {start_time_str}")
            continue
        
        # Check if within trigger window
        if start_time >= cutoff_time:
            recent_runs.append(activity)
    
    return recent_runs


def format_run_for_prompt(activity):
    """Format a single run activity for the Claude prompt."""
    lines = []
    lines.append(f"### {activity.get('name', 'Untitled Run')}")
    lines.append(f"- **Date/Time**: {activity.get('startTimeLocal', 'Unknown')}")
    lines.append(f"- **Distance**: {activity.get('distanceKm', 'N/A')} km")
    lines.append(f"- **Duration**: {activity.get('durationMin', 'N/A')} minutes")
    
    # Add intervals if available
    intervals = activity.get("intervals")
    if intervals:
        lines.append(f"- **Intervals/Laps**:")
        for interval in intervals:
            lines.append(f"  - {interval}")
    
    return "\n".join(lines)


def format_all_runs_for_context(activities):
    """Format all recent runs for context in the prompt."""
    running_activities = [a for a in activities if a.get("activityType") == "running"]
    
    if not running_activities:
        return "No running activities in the last 7 days."
    
    sections = []
    for activity in running_activities:
        sections.append(format_run_for_prompt(activity))
    
    return "\n\n".join(sections)


def analyze_runs_with_claude(bedrock_client, recent_run, all_runs_context, training_plan):
    """
    Send run data to Claude Sonnet 4.5 via Bedrock for analysis.
    
    Args:
        recent_run: The most recent run to analyze (triggered the Lambda)
        all_runs_context: Formatted string of all runs in the last 7 days
        training_plan: The user's training plan
    
    Returns the analysis text.
    """
    prompt = f"""You are an expert running coach. Analyze this run and provide a very concise response.

Training Plan:
{training_plan}

Recent Runs (Last 7 Days):
{all_runs_context}

Run to Analyze:
{format_run_for_prompt(recent_run)}

IMPORTANT: When checking if a pace is "in range":
- Easy/Long runs: 5:00-6:00 min/km is the target range. A pace of 5:29 min/km IS within range and correct.
- Only flag paces as "too fast" if they are FASTER than the minimum of the range (e.g., faster than 5:00 for easy runs).
- Only flag paces as "too slow" if they are SLOWER than the maximum of the range (e.g., slower than 6:00 for easy runs).

Provide ONLY:
1. Quick Assessment (2-3 sentences max): How does this run fit the training plan? Only mention concerns if the pace is actually outside the target range.
2. Suggested Next Run: Distance in km, pace target in min/km, and HR zone (e.g., "5km at 5:30 min/km, HR zone 2")

No headers, no markdown, no bullet points. Just plain text, maximum 100 words total. Use normal professional language, not pirate speak."""

    try:
        response = bedrock_client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 300,  # ~100 words max
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


def save_analysis_to_s3(s3_client, run_data, analysis, all_activities):
    """Save the analysis output to S3."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    key = f"{OUTPUT_PREFIX}{timestamp}_analysis.json"
    
    # Get the 3 most recent running activities
    running_activities = [a for a in all_activities if a.get("activityType") == "running"]
    running_activities.sort(
        key=lambda x: x.get("startTimeLocal", ""),
        reverse=True
    )
    recent_runs = running_activities[:3]
    
    output = {
        "timestamp": timestamp,
        "analyzed_run": run_data,
        "recent_runs": recent_runs,  # Top 3 most recent runs
        "analysis": analysis,
        "context_activities_count": len(running_activities)
    }
    
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
    
    # Validate environment variables
    if not SECRET_ARN:
        raise ValueError("GARMIN_SECRET_ARN environment variable is required")
    if not S3_BUCKET:
        raise ValueError("S3_BUCKET_NAME environment variable is required")
    
    # Initialize AWS clients
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    
    # Get Garmin credentials and set them for the get_from_garmin module
    username, password = get_garmin_credentials()
    set_garmin_env_credentials(username, password)
    
    # Fetch recent activities (get enough to cover 7 days - assuming max 3-4 activities per day)
    logger.info("Fetching recent Garmin activities...")
    activities_json = get_recent_garmin_activities(n_recent=30)
    all_activities_raw = json.loads(activities_json)
    
    # Check for error response
    if isinstance(all_activities_raw, dict) and "error" in all_activities_raw:
        logger.error(f"Error fetching activities: {all_activities_raw.get('error')}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": all_activities_raw.get("error")})
        }
    
    # Ensure we have a list
    if not isinstance(all_activities_raw, list):
        logger.error(f"Unexpected response format: {type(all_activities_raw)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Unexpected response format from Garmin API"})
        }
    
    # Filter to only include activities from the last 7 days
    all_activities = filter_activities_by_date(all_activities_raw, days=CONTEXT_DAYS)
    logger.info(f"Fetched {len(all_activities_raw)} total activities, {len(all_activities)} from last {CONTEXT_DAYS} days")
    
    # Filter for runs in the last 12 hours (trigger condition)
    recent_runs = filter_recent_runs(all_activities, hours=TRIGGER_HOURS)
    
    if not recent_runs:
        logger.info(f"No runs found in the last {TRIGGER_HOURS} hours. Exiting.")
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": f"No runs in the last {TRIGGER_HOURS} hours",
                "runs_analyzed": 0,
                "total_activities_fetched": len(all_activities)
            })
        }
    
    logger.info(f"Found {len(recent_runs)} run(s) in the last {TRIGGER_HOURS} hours")
    
    # Get training plan
    training_plan = get_training_plan(s3_client)
    
    # Format all runs for context
    all_runs_context = format_all_runs_for_context(all_activities)
    
    # Analyze each recent run and save results
    results = []
    for run in recent_runs:
        run_name = run.get("name", "Untitled Run")
        distance = run.get("distanceKm", "N/A")
        logger.info(f"Analyzing run: {run_name} ({distance} km)")
        
        # Get analysis from Claude
        analysis = analyze_runs_with_claude(
            bedrock_client, 
            run, 
            all_runs_context, 
            training_plan
        )
        
        # Save to S3
        output_key = save_analysis_to_s3(s3_client, run, analysis, all_activities)
        
        results.append({
            "run_name": run_name,
            "distance_km": distance,
            "output_key": output_key
        })
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"Analyzed {len(results)} run(s)",
            "runs_analyzed": len(results),
            "total_activities_fetched": len(all_activities),
            "results": results
        })
    }
