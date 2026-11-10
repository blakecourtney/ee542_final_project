import json
import sqlite3
from pathlib import Path

#libraries for testing
#from .api import make_client, iter_all_activities

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id       INTEGER PRIMARY KEY,
    activity_type     TEXT,
    start_time_local  TEXT,
    start_time_gmt    TEXT,
    distance_m        REAL,
    moving_duration_s REAL,
    avg_hr            REAL,
    max_hr            REAL,
    avg_power_w       REAL,
    training_load     REAL,
    aerobic_te        REAL,
    summary_json      TEXT NOT NULL
);
"""

def connect(path: str) -> sqlite3.Connection:
    """Open the database (creating the folder if needed) and make sure the table exists."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path) 
    conn.execute(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn

UPSERT_SQL = """
INSERT INTO activities (
    activity_id,
    activity_type,
    start_time_local,
    start_time_gmt,
    distance_m,
    moving_duration_s,
    avg_hr,
    max_hr,
    avg_power_w,
    training_load,
    aerobic_te,
    summary_json
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(activity_id) DO UPDATE SET
    activity_type     = excluded.activity_type,
    start_time_local  = excluded.start_time_local,
    start_time_gmt    = excluded.start_time_gmt,
    distance_m        = excluded.distance_m,
    moving_duration_s = excluded.moving_duration_s,
    avg_hr            = excluded.avg_hr,
    max_hr            = excluded.max_hr,
    avg_power_w       = excluded.avg_power_w,
    training_load     = excluded.training_load,
    aerobic_te        = excluded.aerobic_te,
    summary_json      = excluded.summary_json
"""


def upsert_activity(conn: sqlite3.Connection, summary: dict) -> None:
    """Insert or update one activity summary."""
    activity_type = (summary.get("activityType") or {}).get("typeKey")

    values = (
        summary["activityId"],
        activity_type,
        summary.get("startTimeLocal"),
        summary.get("startTimeGMT"),
        summary.get("distance"),
        summary.get("movingDuration"),
        summary.get("averageHR"),
        summary.get("maxHR"),
        summary.get("avgPower"),
        summary.get("activityTrainingLoad"),
        summary.get("aerobicTrainingEffect"),
        json.dumps(summary),
    )
    conn.execute(UPSERT_SQL, values)

def save_raw(data_dir: str, activity_id: int, content: bytes) -> Path:
    """Save Garmin's original download ZIP, untouched, and return where it went."""
    path = Path(data_dir) / "raw" / f"{activity_id}.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path

def has_activity(conn: sqlite3.Connection, activity_id: int) -> bool:
    """True if this activity is already in the database."""
    row = conn.execute("SELECT 1 FROM activities WHERE activity_id = ?", (activity_id,)).fetchone()
    return row is not None