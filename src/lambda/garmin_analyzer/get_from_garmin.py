"""Uses garminconnect to obtain running data."""

import json
import os
import shutil
import zipfile
from xml.etree import ElementTree as ET

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Lambda: credentials set via env by handler; no .env file
from garminconnect import Garmin  # type: ignore


# ── Helpers ───────────────────────────────────────────────────────────────────
def _fmt_pace(min_per_km: float | None):
    if min_per_km is None:
        return None
    mins = int(min_per_km)
    secs = int(round((min_per_km - mins) * 60))
    return f"{mins}:{secs:02d} min/km"


def _pace_from(dist_m, dur_s):
    if not isinstance(dist_m, (int, float)) or not isinstance(dur_s, (int, float)):
        return None
    if dist_m <= 0 or dur_s <= 0:
        return None
    return (dur_s / 60.0) / (dist_m / 1000.0)


def _format_hms(seconds: float | None) -> str:
    if not isinstance(seconds, (int, float)):
        return "?"
    secs = int(round(seconds))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"


def _add_row(rows, label, dist_m, dur_s, avg_speed_mps, avg_hr):
    # choose pace from speed if available, else compute from dist/time
    if isinstance(avg_speed_mps, (int, float)) and avg_speed_mps > 0:
        pace = (1000.0 / avg_speed_mps) / 60.0
    else:
        pace = _pace_from(dist_m, dur_s)

    distance_km = (
        round(dist_m / 1000.0, 2) if isinstance(dist_m, (int, float)) else None
    )
    duration_str = _format_hms(dur_s)
    pace_str = _fmt_pace(pace) or "?"
    hr_str = f"{int(avg_hr)}" if isinstance(avg_hr, (int, float)) else "?"

    rows.append(
        f"{label} - {distance_km}km - {duration_str} (duration) - {pace_str} pace - {hr_str} HR"
    )


def _save_bytes(path: str, data: bytes) -> bool:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return os.path.exists(path) and os.path.getsize(path) > 0


def _download_via_enum(api: Garmin, activity_id: int, fmt_member, to_path: str) -> bool:
    try:
        resp = api.download_activity(activity_id, fmt_member)  # bytes on your build
    except Exception as e:
        print(f"[{activity_id}] download_activity({fmt_member}) error: {e}")
        return False

    data = (
        resp if isinstance(resp, (bytes, bytearray)) else getattr(resp, "content", None)
    )
    if not data:
        print(f"[{activity_id}] download_activity({fmt_member}) returned no data")
        return False

    return _save_bytes(to_path, bytes(data))


def _ensure_tcx(api: Garmin, activity_id: int, cache_dir: str):
    """Return path to a TCX file for this activity, or None if we can’t get one.

    Tries direct TCX first; then ORIGINAL zip and extracts a TCX if present.
    """
    enum = api.ActivityDownloadFormat
    tcx_path = os.path.join(cache_dir, f"{activity_id}.tcx")
    os.makedirs(cache_dir, exist_ok=True)

    # 1) TCX direct
    if _download_via_enum(api, activity_id, enum.TCX, tcx_path):
        return tcx_path

    # 2) ORIGINAL zip → extract a TCX if present
    zip_path = os.path.join(cache_dir, f"{activity_id}.zip")
    if _download_via_enum(api, activity_id, enum.ORIGINAL, zip_path):
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                cand_tcx = [n for n in zf.namelist() if n.lower().endswith(".tcx")]
                if cand_tcx:
                    with zf.open(cand_tcx[0]) as f:
                        if _save_bytes(tcx_path, f.read()):
                            return tcx_path
        except Exception as e:
            print(f"[{activity_id}] unzip ORIGINAL error: {e}")

    return None


def _intervals_from_tcx_path(tcx_path: str):
    try:
        ns = {"tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
        root = ET.parse(tcx_path).getroot()
        rows = []
        for lap in root.findall(".//tcx:Lap", ns):
            dur_text = lap.findtext("tcx:TotalTimeSeconds", default="", namespaces=ns)
            dist_text = lap.findtext("tcx:DistanceMeters", default="", namespaces=ns)
            hr_text = lap.findtext(
                "tcx:AverageHeartRateBpm/tcx:Value", default="", namespaces=ns
            )
            label = lap.findtext(
                "tcx:Intensity", default="lap", namespaces=ns
            )  # 'Active' or 'Rest'

            dur_s = float(dur_text) if dur_text else None
            dist_m = float(dist_text) if dist_text else None
            avg_hr = float(hr_text) if hr_text else None
            _add_row(rows, label, dist_m, dur_s, avg_speed_mps=None, avg_hr=avg_hr)
        return rows or None
    except Exception as e:
        print(f"[tcx parse error] {e}")
        return None


def _wipe_dir_contents(dir_path: str) -> None:
    """Delete all files and subdirectories inside dir_path, but not dir_path itself.

    Safe-guards against accidental dangerous values.
    """
    if not dir_path:
        return
    # Ensure we only touch a directory named '.fitcache'
    base = os.path.basename(os.path.normpath(dir_path))
    if base != ".fitcache":
        print(f"[warn] Refusing to wipe non-.fitcache directory: {dir_path}")
        return

    if not os.path.isdir(dir_path):
        os.makedirs(dir_path, exist_ok=True)
        return

    for entry in os.listdir(dir_path):
        p = os.path.join(dir_path, entry)
        try:
            if os.path.islink(p) or os.path.isfile(p):
                os.unlink(p)
            elif os.path.isdir(p):
                shutil.rmtree(p)
        except Exception as e:
            print(f"[wipe] Failed to remove {p}: {e}")


# ── Main function ──────────────────────────────────────────────────────────────
def get_recent_garmin_activities(n_recent: int = 10) -> str:
    """Get recent garmin activities in FIT format."""
    GARMIN_EMAIL = os.getenv("GARMIN_USERNAME")
    GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")

    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        return json.dumps({"error": "Missing GARMIN_EMAIL / GARMIN_PASSWORD in .env"})

    api = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    api.login()
    activities = api.get_activities(0, n_recent)

    # Lambda file storage: only /tmp is writable (configurable size, default 512MB)
    cache_root = os.environ.get("GARMIN_CACHE_DIR", "/tmp")
    cache_dir = os.path.join(cache_root, ".fitcache")

    # Clean before we start
    _wipe_dir_contents(cache_dir)

    try:
        out = []

        for a in activities:
            name = a.get("activityName") or a.get("activityNameOriginal")
            typ = (a.get("activityType", {}) or {}).get("typeKey")
            start = a.get("startTimeLocal")
            dist_km = (
                round(a["distance"] / 1000.0, 2)
                if isinstance(a.get("distance"), (int, float))
                else None
            )
            dur_min = (
                round(a["duration"] / 60.0, 1)
                if isinstance(a.get("duration"), (int, float))
                else None
            )
            act_id = (
                a.get("activityId")
                or a.get("activityIdOriginal")
                or a.get("activityUUID")
            )

            intervals, source = None, "none"
            if act_id and typ == "running":
                tcx_path = _ensure_tcx(api, act_id, cache_dir)
                if tcx_path:
                    intervals = _intervals_from_tcx_path(tcx_path)
                    source = "tcx(laps)" if intervals else "tcx-parse-failed"
                else:
                    source = "download-failed"

            print(
                f"[{act_id}] intervals source: {source} - count={len(intervals or [])}"
            )

            out.append(
                {
                    "activityId": act_id,
                    "startTimeLocal": start,
                    "activityType": typ,
                    "distanceKm": dist_km,
                    "durationMin": dur_min,
                    "name": name,
                    "intervals": intervals,
                }
            )

        # print(json.dumps(out, indent=2))
        return json.dumps(out)

    finally:
        # Always clean up cache afterward (even on exceptions)
        _wipe_dir_contents(cache_dir)
        try:
            api.logout()
        except Exception:
            pass

