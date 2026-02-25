"""Flask app: reads latest run analysis from S3 only. No LLM calls."""

import html
import json
import os

import boto3
import markdown
from botocore.exceptions import ClientError
from flask import Flask, render_template

app = Flask(__name__, template_folder="templates")

S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "")
ANALYSIS_PREFIX = os.environ.get("ANALYSIS_PREFIX", "run-analysis/")


def get_s3_client():
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-west-1"))


def get_latest_analysis_from_s3():
    """Get the most recent analysis JSON from S3 (Lambda output). No LLM calls.

    Returns dict with keys: recent_runs, suggestion (or analysis), recent_runs_html (optional).
    """
    if not S3_BUCKET:
        raise ValueError("S3_BUCKET_NAME environment variable is required")

    s3 = get_s3_client()
    try:
        response = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=ANALYSIS_PREFIX)
        objects = response.get("Contents", [])
        if not objects:
            return None
    except ClientError as e:
        raise Exception(f"Failed to list S3: {e}") from e

    latest = max(objects, key=lambda obj: obj["LastModified"])
    key = latest["Key"]

    try:
        response = s3.get_object(Bucket=S3_BUCKET, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))
    except Exception as e:
        raise Exception(f"Failed to read {key}: {e}") from e

    return {
        "recent_runs": data.get("recent_runs", []),
        "suggestion": data.get("suggestion")
        or data.get("analysis", "No suggestion yet."),
        "recent_runs_html": data.get("recent_runs_html"),
    }


def format_runs_fallback(recent_runs):
    """Simple HTML list from recent_runs when recent_runs_html not in S3. No LLM."""
    if not recent_runs:
        return "<ul><li>No recent runs.</li></ul>"
    parts = ["<ul>"]
    for r in recent_runs[:15]:
        date = (r.get("startTimeLocal") or "").split()[0] or "?"
        name = html.escape(r.get("name") or "Run")
        dist = r.get("distanceKm", "?")
        dur_min = r.get("durationMin")
        dur = (
            f"{int(dur_min)}:{int((dur_min or 0) % 1 * 60):02d}"
            if isinstance(dur_min, (int, float))
            else "?"
        )
        parts.append(f"<li>{date} - {name}, {dist} km, {dur}, avg HR N/A</li>")
    parts.append("</ul>")
    return "".join(parts)


@app.route("/health")
def health():
    return "OK", 200


@app.route("/")
def homepage():
    """Display latest runs and coach suggestion from S3 only."""
    try:
        data = get_latest_analysis_from_s3()
    except Exception as e:
        return render_template(
            "index.html",
            recent_runs_html=f"<p>Error loading data: {html.escape(str(e))}</p>",
            suggested_next_run="<p>No analysis available.</p>",
        ), 500 if "S3" in str(e) else 200

    if not data:
        return render_template(
            "index.html",
            recent_runs_html="<ul><li>No runs yet.</li></ul>",
            suggested_next_run="<p>No analysis yet. The Lambda will analyze your next run.</p>",
        )

    recent_runs_html = data.get("recent_runs_html")
    if not recent_runs_html:
        recent_runs_html = format_runs_fallback(data.get("recent_runs", []))

    suggestion = data.get("suggestion", "")
    suggested_next_run = markdown.markdown(suggestion, extensions=["nl2br"])

    return render_template(
        "index.html",
        recent_runs=recent_runs_html,  # already HTML, pass as safe in template
        suggested_next_run=suggested_next_run,
    )


if __name__ == "__main__":
    app.run(debug=False, port=8000, host="0.0.0.0")
