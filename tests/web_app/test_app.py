import pytest
import html

from web_app.app import format_runs_fallback


def test_format_runs_empty_list():
    """Test that format_runs_fallback returns the correct HTML when the recent_runs list is empty."""
    result = format_runs_fallback([])
    assert result == "<ul><li>No recent runs.</li></ul>"

def test_format_runs_single_run():
    """Test that format_runs_fallback returns the correct HTML when the recent_runs list has a single run."""
    result = format_runs_fallback([{"startTimeLocal": "2026-02-24 10:00:00", "name": "Run 1", "distanceKm": 10, "durationMin": 60}])
    assert result == "<ul><li>2026-02-24 - Run 1, 10 km, 1:00, avg HR N/A</li></ul>"

def test_format_runs_multiple_runs():
    """Test that format_runs_fallback returns the correct HTML when the recent_runs list has multiple runs."""
    result = format_runs_fallback([{"startTimeLocal": "2026-02-24 10:00:00", "name": "Run 1", "distanceKm": 10, "durationMin": 60}, {"startTimeLocal": "2026-02-25 10:00:00", "name": "Run 2", "distanceKm": 15, "durationMin": 90}])
    assert result == "<ul><li>2026-02-24 - Run 1, 10 km, 1:00, avg HR N/A</li><li>2026-02-25 - Run 2, 15 km, 1:30, avg HR N/A</li></ul>"