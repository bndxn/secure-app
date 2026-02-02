import os

import sys
from flask import Flask, jsonify, render_template_string, Response

app = Flask(__name__)

# Get S3 bucket name from environment variable
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'secure-app-data')

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
        .status {
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        .status.success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .status.error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
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
        
        {% if status == 'success' %}
        <div class="status success">
            ✅ Successfully connected to S3 bucket: <code>{{ bucket_name }}</code>
        </div>
        {% else %}
        <div class="status error">
            ❌ Error: {{ error_message }}
        </div>
        {% endif %}
        
        {% if files %}
        <div class="bucket-info">
            <h2>Files in S3 Bucket</h2>
            <ul class="file-list">
                {% for file in files %}
                <li>{{ file }}</li>
                {% endfor %}
            </ul>
        </div>
        {% endif %}
        
        <div class="bucket-info" style="margin-top: 20px;">
            <h2>API Endpoints</h2>
            <ul class="file-list">
                <li><code>GET /</code> - This homepage</li>
                <li><code>GET /health</code> - Health check endpoint</li>
                <li><code>GET /api/files</code> - List files in S3 bucket</li>
                <li><code>GET /api/files/&lt;filename&gt;</code> - Get file content from S3</li>
            </ul>
        </div>
    </div>
</body>
</html>
"""


@app.route('/')
def index():
    """Homepage with S3 bucket information"""
    try:
        from botocore.exceptions import ClientError
        # List objects in the bucket (limit to 10 for display)
        s3_client = get_s3_client()
        response = s3_client.list_objects_v2(Bucket=S3_BUCKET_NAME, MaxKeys=10)
        files = [obj['Key'] for obj in response.get('Contents', [])]
        
        return render_template_string(
            HOME_TEMPLATE,
            status='success',
            bucket_name=S3_BUCKET_NAME,
            files=files if files else None
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
            status='error',
            error_message=error_message,
            bucket_name=S3_BUCKET_NAME
        ), 500
    except Exception as e:
        return render_template_string(
            HOME_TEMPLATE,
            status='error',
            error_message=f"Unexpected error: {str(e)}",
            bucket_name=S3_BUCKET_NAME
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
