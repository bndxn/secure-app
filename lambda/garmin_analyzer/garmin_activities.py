"""
Garmin Connect API client for fetching running activities and interval data.

This module handles:
- Authentication with Garmin Connect
- Fetching recent activities
- Downloading TCX files for interval/lap data
- Parsing TCX XML to extract lap information
"""

import json
import logging
import os
import shutil
import zipfile
from xml.etree import ElementTree as ET

try:
    from dotenv import load_dotenv
    load_dotenv()  # Only needed for local development
except ImportError:
    pass  # dotenv not needed in Lambda environment

from garminconnect import Garmin  # type: ignore

logger = logging.getLogger(__name__)

# Constants
CACHE_DIR_NAME = ".fitcache"


def _format_pace(min_per_km: float | None) -> str | None:
    """Format pace as MM:SS min/km."""
    if min_per_km is None:
        return None
    mins = int(min_per_km)
    secs = int(round((min_per_km - mins) * 60))
    return f"{mins}:{secs:02d} min/km"


def _calculate_pace(dist_m: float | int | None, dur_s: float | int | None) -> float | None:
    """Calculate pace in min/km from distance (meters) and duration (seconds)."""
    if not isinstance(dist_m, (int, float)) or not isinstance(dur_s, (int, float)):
        return None
    if dist_m <= 0 or dur_s <= 0:
        return None
    return (dur_s / 60.0) / (dist_m / 1000.0)


def _format_duration(seconds: float | int | None) -> str:
    """Format duration as H:MM:SS or MM:SS."""
    if not isinstance(seconds, (int, float)):
        return "?"
    secs = int(round(seconds))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"


def _format_interval_row(
    label: str,
    dist_m: float | None,
    dur_s: float | None,
    avg_speed_mps: float | None,
    avg_hr: float | None,
) -> str:
    """Format a single interval/lap row with distance, duration, pace, and HR."""
    # Calculate pace from speed if available, otherwise from distance/time
    if isinstance(avg_speed_mps, (int, float)) and avg_speed_mps > 0:
        pace = (1000.0 / avg_speed_mps) / 60.0
    else:
        pace = _calculate_pace(dist_m, dur_s)

    distance_km = round(dist_m / 1000.0, 2) if isinstance(dist_m, (int, float)) else None
    duration_str = _format_duration(dur_s)
    pace_str = _format_pace(pace) or "?"
    hr_str = f"{int(avg_hr)}" if isinstance(avg_hr, (int, float)) else "?"

    return f"{label} - {distance_km}km - {duration_str} (duration) - {pace_str} pace - {hr_str} HR"


def _save_file(path: str, data: bytes) -> bool:
    """Save bytes to a file, creating parent directories if needed."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return os.path.exists(path) and os.path.getsize(path) > 0
    except Exception as e:
        logger.error(f"Failed to save file {path}: {e}")
        return False


def _download_activity_file(api: Garmin, activity_id: int, format_type, file_path: str) -> bool:
    """Download an activity file in the specified format."""
    try:
        response = api.download_activity(activity_id, format_type)
    except Exception as e:
        logger.warning(f"[{activity_id}] Failed to download {format_type}: {e}")
        return False

    # Handle different response types
    data = response if isinstance(response, (bytes, bytearray)) else getattr(response, "content", None)
    if not data:
        logger.warning(f"[{activity_id}] No data returned for {format_type}")
        return False

    return _save_file(file_path, bytes(data))


def _get_tcx_file(api: Garmin, activity_id: int, cache_dir: str) -> str | None:
    """
    Get TCX file for an activity.
    
    Tries:
    1. Direct TCX download
    2. ORIGINAL zip download and extract TCX from it
    
    Returns path to TCX file or None if unavailable.
    """
    enum = api.ActivityDownloadFormat
    tcx_path = os.path.join(cache_dir, f"{activity_id}.tcx")
    os.makedirs(cache_dir, exist_ok=True)

    # Try direct TCX download
    if _download_activity_file(api, activity_id, enum.TCX, tcx_path):
        return tcx_path

    # Try ORIGINAL zip and extract TCX
    zip_path = os.path.join(cache_dir, f"{activity_id}.zip")
    if _download_activity_file(api, activity_id, enum.ORIGINAL, zip_path):
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                tcx_files = [name for name in zf.namelist() if name.lower().endswith(".tcx")]
                if tcx_files:
                    with zf.open(tcx_files[0]) as f:
                        if _save_file(tcx_path, f.read()):
                            return tcx_path
        except Exception as e:
            logger.warning(f"[{activity_id}] Failed to extract TCX from zip: {e}")

    return None


def _parse_tcx_intervals(tcx_path: str) -> list[str] | None:
    """Parse TCX file and extract interval/lap information."""
    try:
        ns = {"tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
        root = ET.parse(tcx_path).getroot()
        intervals = []

        for lap in root.findall(".//tcx:Lap", ns):
            dur_text = lap.findtext("tcx:TotalTimeSeconds", default="", namespaces=ns)
            dist_text = lap.findtext("tcx:DistanceMeters", default="", namespaces=ns)
            hr_text = lap.findtext("tcx:AverageHeartRateBpm/tcx:Value", default="", namespaces=ns)
            label = lap.findtext("tcx:Intensity", default="lap", namespaces=ns)  # 'Active' or 'Rest'

            dur_s = float(dur_text) if dur_text else None
            dist_m = float(dist_text) if dist_text else None
            avg_hr = float(hr_text) if hr_text else None

            interval_row = _format_interval_row(label, dist_m, dur_s, avg_speed_mps=None, avg_hr=avg_hr)
            intervals.append(interval_row)

        return intervals if intervals else None
    except Exception as e:
        logger.error(f"Failed to parse TCX file {tcx_path}: {e}")
        return None


def _cleanup_cache_dir(cache_dir: str) -> None:
    """
    Delete all files and subdirectories in the cache directory.
    
    Safety check: only cleans directories named '.fitcache' to prevent accidents.
    """
    if not cache_dir:
        return

    # Safety check: only clean .fitcache directories
    base = os.path.basename(os.path.normpath(cache_dir))
    if base != CACHE_DIR_NAME:
        logger.warning(f"Refusing to clean non-{CACHE_DIR_NAME} directory: {cache_dir}")
        return

    if not os.path.isdir(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
        return

    for entry in os.listdir(cache_dir):
        entry_path = os.path.join(cache_dir, entry)
        try:
            if os.path.islink(entry_path) or os.path.isfile(entry_path):
                os.unlink(entry_path)
            elif os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
        except Exception as e:
            logger.warning(f"Failed to remove {entry_path}: {e}")


def get_recent_garmin_activities(n_recent: int = 5) -> str:
    """
    Fetch recent Garmin activities with interval/lap data for running activities.
    
    Args:
        n_recent: Number of recent activities to fetch
        
    Returns:
        JSON string containing list of activities with their data
        
    Environment Variables:
        GARMIN_USERNAME: Garmin Connect email/username
        GARMIN_PASSWORD: Garmin Connect password
        GARMIN_CACHE_DIR: Directory for temporary file cache (default: /tmp)
    """
    username = os.getenv("GARMIN_USERNAME")
    password = os.getenv("GARMIN_PASSWORD")

    if not username or not password:
        error_msg = "Missing GARMIN_USERNAME or GARMIN_PASSWORD environment variables"
        logger.error(error_msg)
        return json.dumps({"error": error_msg})

    # Initialize Garmin API
    try:
        api = Garmin(username, password)
        api.login()
    except Exception as e:
        error_msg = f"Failed to authenticate with Garmin Connect: {e}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg})

    # Setup cache directory (Lambda uses /tmp)
    cache_root = os.environ.get("GARMIN_CACHE_DIR", "/tmp")
    cache_dir = os.path.join(cache_root, CACHE_DIR_NAME)
    _cleanup_cache_dir(cache_dir)

    try:
        # Fetch activities
        try:
            activities = api.get_activities(0, n_recent)
        except Exception as e:
            error_msg = f"Failed to fetch activities: {e}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        results = []

        for activity in activities:
            name = activity.get("activityName") or activity.get("activityNameOriginal")
            activity_type = (activity.get("activityType", {}) or {}).get("typeKey")
            start_time = activity.get("startTimeLocal")
            activity_id = (
                activity.get("activityId")
                or activity.get("activityIdOriginal")
                or activity.get("activityUUID")
            )

            # Extract distance and duration
            distance_km = (
                round(activity["distance"] / 1000.0, 2)
                if isinstance(activity.get("distance"), (int, float))
                else None
            )
            duration_min = (
                round(activity["duration"] / 60.0, 1)
                if isinstance(activity.get("duration"), (int, float))
                else None
            )

            # Get intervals for running activities
            intervals = None
            if activity_id and activity_type == "running":
                tcx_path = _get_tcx_file(api, activity_id, cache_dir)
                if tcx_path:
                    intervals = _parse_tcx_intervals(tcx_path)
                    logger.info(
                        f"[{activity_id}] Extracted {len(intervals) if intervals else 0} intervals"
                    )

            results.append({
                "activityId": activity_id,
                "startTimeLocal": start_time,
                "activityType": activity_type,
                "distanceKm": distance_km,
                "durationMin": duration_min,
                "name": name,
                "intervals": intervals,
            })

        return json.dumps(results)

    finally:
        # Always clean up cache and logout
        _cleanup_cache_dir(cache_dir)
        try:
            api.logout()
        except Exception:
            pass


if __name__ == "__main__":
    # For local testing
    logging.basicConfig(level=logging.INFO)
    result = get_recent_garmin_activities(5)
    print(result)
