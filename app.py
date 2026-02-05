import html
import json
import os
import re
import sys
from flask import Flask, jsonify, render_template_string, Response

app = Flask(__name__)

# Get S3 bucket name from environment variable
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'secure-app-data')
ANALYSIS_PREFIX = 'run-analysis/'

# Initialize S3 client lazily to avoid startup issues
def get_s3_client():
    """Get S3 client, creating it if needed - fails gracefully"""
    try:
        import boto3
        if not hasattr(get_s3_client, '_client'):
            get_s3_client._client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'eu-west-1'))
        return get_s3_client._client
    except Exception as e:
        # Log error but don't crash
        print(f"Warning: Could not initialize S3 client: {e}", file=sys.stderr)
        raise


def get_latest_analysis():
    """Get the most recent run analysis from S3."""
    try:
        from botocore.exceptions import ClientError
        s3_client = get_s3_client()
        
        # List all analysis files
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET_NAME,
            Prefix=ANALYSIS_PREFIX
        )
        
        if 'Contents' not in response or not response['Contents']:
            print(f"No analysis files found with prefix '{ANALYSIS_PREFIX}'", file=sys.stderr)
            return None
        
        print(f"Found {len(response['Contents'])} analysis files", file=sys.stderr)
        
        # Sort by LastModified (most recent first)
        files = sorted(
            response['Contents'],
            key=lambda x: x['LastModified'],
            reverse=True
        )
        
        # Get the most recent file
        latest_file = files[0]
        file_key = latest_file['Key']
        print(f"Loading latest analysis from: {file_key}", file=sys.stderr)
        
        # Download and parse the file
        file_response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=file_key)
        content = file_response['Body'].read().decode('utf-8')
        analysis_data = json.loads(content)
        
        print(f"Successfully loaded analysis with keys: {list(analysis_data.keys())}", file=sys.stderr)
        return analysis_data
    except (ClientError, json.JSONDecodeError, KeyError, Exception) as e:
        print(f"Error fetching latest analysis: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return None


def format_recent_runs_html(analysis_data):
    """Format the 3 most recent runs from analysis data as a simple bullet list."""
    if not analysis_data:
        return None
    
    recent_runs = analysis_data.get('recent_runs', [])
    if not recent_runs:
        return '<p><em>No recent runs found.</em></p>'
    
    html_parts: list[str] = []
    html_parts.append('<ul>')

    for run in recent_runs[:3]:  # Ensure max 3
        name = run.get("name", "Untitled Run") or "Untitled Run"
        distance = run.get("distanceKm", "N/A")
        duration = run.get("durationMin", "N/A")
        start_time = run.get("startTimeLocal", "Unknown")

        # Format date nicely (just the date part if it includes time)
        date_display = start_time.split()[0] if isinstance(start_time, str) and " " in start_time else start_time

        # Calculate pace and get HR if available
        pace = "?"
        avg_hr = run.get("averageHR") or "?"
        
        # Calculate pace from distance and duration if possible
        try:
            if isinstance(distance, (int, float)) and isinstance(duration, (int, float)) and distance > 0 and duration > 0:
                pace_min_per_km = duration / distance
                pace_min = int(pace_min_per_km)
                pace_sec = int((pace_min_per_km - pace_min) * 60)
                pace = f"{pace_min}:{pace_sec:02d}/km"
        except (ValueError, TypeError):
            pass

        # Top-level bullet for the run
        summary = f"{date_display} - {name}, {distance} km, {duration} min, {pace}, avg HR {avg_hr}"
        html_parts.append(f'<li>{html.escape(summary)}')

        # Nested bullets for intervals, if available
        intervals = run.get("intervals")
        if intervals:
            html_parts.append('<ul>')
            for interval in intervals[:6]:  # Limit to 6 intervals for readability
                # Interval text is already human-readable from the Lambda
                interval_text = str(interval)
                html_parts.append(f'<li>{html.escape(interval_text)}</li>')
            html_parts.append("</ul>")
        
        html_parts.append("</li>")

    html_parts.append("</ul>")

    return "".join(html_parts) if html_parts else "<p><em>No recent runs found.</em></p>"


def truncate_to_words(text, max_words=250):
    """Truncate text to a maximum number of words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return ' '.join(words[:max_words]) + '...'


def format_analysis_html(analysis_data):
    """Format the Claude analysis as HTML - simple plain text formatting."""
    if not analysis_data:
        return None
    
    analysis_text = analysis_data.get('analysis', '')
    if not analysis_text:
        return None
    
    # Truncate to 100 words
    analysis_text = truncate_to_words(analysis_text, max_words=100)
    
    # Escape HTML
    analysis_text = html.escape(analysis_text)
    
    # Simple formatting: split by line breaks and format as paragraphs
    lines = analysis_text.split('\n')
    formatted_lines = []
    prev_was_blank = False
    
    for line in lines:
        line = line.strip()
        
        # Skip multiple consecutive blank lines
        if not line:
            if not prev_was_blank:
                formatted_lines.append('<br>')
                prev_was_blank = True
            continue
        
        prev_was_blank = False
        
        # Format as paragraph
        formatted_lines.append(f'<p>{line}</p>')
    
    return '\n'.join(formatted_lines)

# HTML template for the homepage
HOME_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Secure App - S3 Data Viewer</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 40px;
            max-width: 800px;
            width: 100%;
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 2.5em;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
            font-size: 1.1em;
        }
        .bucket-info {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin-top: 20px;
        }
        .bucket-info h2 {
            color: #333;
            margin-bottom: 15px;
            font-size: 1.5em;
        }
        .file-list {
            list-style: none;
        }
        .file-list li {
            padding: 10px;
            margin: 5px 0;
            background: white;
            border-radius: 5px;
            border-left: 4px solid #667eea;
        }
        .block {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
        }
        .block h3 {
            color: #333;
            margin-bottom: 15px;
            font-size: 1.3em;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }
        .runs-list {
            margin-top: 10px;
            padding-left: 0;
        }
        .runs-list ul {
            list-style-type: disc;
            padding-left: 20px;
            margin: 8px 0;
        }
        .runs-list ul ul {
            list-style-type: circle;
            padding-left: 30px;
            margin-top: 4px;
        }
        .runs-list li {
            margin: 4px 0;
            list-style-position: outside;
        }
        .analysis-content {
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-top: 10px;
            line-height: 1.5;
        }
        .analysis-content h4 {
            color: #333;
            margin-top: 12px;
            margin-bottom: 6px;
            font-size: 1.1em;
        }
        .analysis-content p {
            margin: 6px 0;
        }
        .analysis-content br {
            line-height: 0.5;
        }
        code {
            background: #f1f1f1;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Secure App</h1>
        <p class="subtitle">Flask Application on AWS App Runner</p>
        
        <div class="block">
            <h3>Recent runs</h3>
            <div class="runs-list">
                {% if recent_runs %}
                    {{ recent_runs | safe }}
                {% else %}
                    <p><em>No recent runs available.</em></p>
                {% endif %}
            </div>
        </div>
        
        <div class="block">
            <h3>Analysis and suggested next run</h3>
            <div class="analysis-content">
                {% if suggested_next_run %}
                    {{ suggested_next_run | safe }}
                {% elif analysis_error %}
                    <div class="status error">
                        Unable to load analysis: {{ analysis_error }}
                    </div>
                {% else %}
                    <p><em>No analysis available yet. The Lambda will analyze your next run.</em></p>
                {% endif %}
            </div>
        </div>
        
    </div>
</body>
</html>
"""


@app.route('/')
def index():
    """Homepage with S3 bucket information and latest run analysis"""
    try:
        from botocore.exceptions import ClientError
        # Get latest analysis
        latest_analysis = None
        analysis_error = None
        try:
            latest_analysis = get_latest_analysis()
            print(f"Latest analysis result: {latest_analysis is not None}", file=sys.stderr)
            if latest_analysis:
                print(f"Analysis keys: {list(latest_analysis.keys())}", file=sys.stderr)
        except Exception as e:
            analysis_error = str(e)
            print(f"Exception getting analysis: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
        
        recent_runs_html = None
        analysis_html = None
        if latest_analysis:
            try:
                recent_runs_html = format_recent_runs_html(latest_analysis)
                analysis_html = format_analysis_html(latest_analysis)
                print(f"Recent runs HTML: {recent_runs_html is not None}", file=sys.stderr)
                print(f"Analysis HTML: {analysis_html is not None}", file=sys.stderr)
            except Exception as e:
                analysis_error = f"Error formatting analysis: {str(e)}"
                print(f"Exception formatting: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc(file=sys.stderr)
        
        return render_template_string(
            HOME_TEMPLATE,
            bucket_name=S3_BUCKET_NAME,
            recent_runs=recent_runs_html,
            suggested_next_run=analysis_html,
            analysis_error=analysis_error
        )
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchBucket':
            error_message = f"Bucket '{S3_BUCKET_NAME}' does not exist"
        elif error_code == 'AccessDenied':
            error_message = "Access denied to S3 bucket. Check IAM permissions."
        else:
            error_message = f"Error accessing S3: {str(e)}"
        
        return render_template_string(
            HOME_TEMPLATE,
            bucket_name=S3_BUCKET_NAME,
            analysis_error=error_message
        ), 500
    except Exception as e:
        return render_template_string(
            HOME_TEMPLATE,
            bucket_name=S3_BUCKET_NAME,
            analysis_error=f"Unexpected error: {str(e)}"
        ), 500


@app.route('/health')
def health():
    """Health check endpoint for App Runner - must be simple and fast"""
    # Always return 200 - this is just a basic health check
    # Return plain text for maximum compatibility
    from flask import Response
    return Response('OK', status=200, mimetype='text/plain')


@app.route('/api/files')
def list_files():
    """API endpoint to list all files in S3 bucket"""
    try:
        from botocore.exceptions import ClientError
        s3_client = get_s3_client()
        response = s3_client.list_objects_v2(Bucket=S3_BUCKET_NAME)
        files = [obj['Key'] for obj in response.get('Contents', [])]
        
        return jsonify({
            'bucket': S3_BUCKET_NAME,
            'file_count': len(files),
            'files': files
        }), 200
    except ClientError as e:
        return jsonify({
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }), 500


@app.route('/api/files/<path:filename>')
def get_file(filename):
    """API endpoint to retrieve file content from S3"""
    try:
        from botocore.exceptions import ClientError
        s3_client = get_s3_client()
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=filename)
        content = response['Body'].read().decode('utf-8')
        
        return jsonify({
            'filename': filename,
            'content': content,
            'content_type': response.get('ContentType', 'text/plain')
        }), 200
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchKey':
            return jsonify({'error': f'File {filename} not found'}), 404
        return jsonify({
            'error': str(e),
            'error_code': error_code
        }), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
