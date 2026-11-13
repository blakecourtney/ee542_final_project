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
CREATE TABLE IF NOT EXISTS daily_health (
    calendar_date     TEXT PRIMARY KEY,

    -- sleep (the night ending this morning)
    sleep_s           REAL,
    deep_s            REAL,
    light_s           REAL,
    rem_s             REAL,
    awake_s           REAL,
    sleep_score       REAL,
    sleep_hr          REAL,
    sleep_stress      REAL,
    sleep_need_min    REAL,

    -- HRV (the night ending this morning)
    hrv_last_night    REAL,
    hrv_weekly_avg    REAL,
    hrv_baseline_low  REAL,
    hrv_baseline_high REAL,
    hrv_status        TEXT,

    -- daily summary (this calendar day)
    resting_hr        REAL,
    body_battery_max  REAL,
    body_battery_min  REAL,
    stress_avg        REAL,
    stress_qualifier  TEXT,
    steps             INTEGER,
    active_calories   REAL,

    -- full originals, so nothing is lost
    sleep_json        TEXT,
    hrv_json          TEXT,
    daily_json        TEXT        
);
"""

def connect(path: str) -> sqlite3.Connection:
    """Open the database (creating the folder if needed) and make sure the table exists."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path) 
    conn.executescript(SCHEMA)
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

SLEEP_UPSERT = """
INSERT INTO daily_health (
    calendar_date, sleep_s, deep_s, light_s, rem_s, awake_s,
    sleep_score, sleep_hr, sleep_stress, sleep_need_min, sleep_json
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(calendar_date) DO UPDATE SET
    sleep_s        = excluded.sleep_s,
    deep_s         = excluded.deep_s,
    light_s        = excluded.light_s,
    rem_s          = excluded.rem_s,
    awake_s        = excluded.awake_s,
    sleep_score    = excluded.sleep_score,
    sleep_hr       = excluded.sleep_hr,
    sleep_stress   = excluded.sleep_stress,
    sleep_need_min = excluded.sleep_need_min,
    sleep_json     = excluded.sleep_json
"""


def upsert_sleep(conn: sqlite3.Connection, entry: dict) -> None:
    """Insert or update the sleep columns for one day. Leaves HRV/daily columns alone."""
    scores = entry.get("sleepScores") or {}
    need = entry.get("sleepNeed") or {}
    values = (
        entry["calendarDate"],
        entry.get("sleepTimeSeconds"),
        entry.get("deepSleepSeconds"),
        entry.get("lightSleepSeconds"),
        entry.get("remSleepSeconds"),
        entry.get("awakeSleepSeconds"),
        (scores.get("overall") or {}).get("value"),
        entry.get("avgHeartRate"),
        entry.get("avgSleepStress"),
        need.get("actual"),
        json.dumps(entry),
    )
    conn.execute(SLEEP_UPSERT, values)

HRV_UPSERT = """
INSERT INTO daily_health (
    calendar_date, hrv_last_night, hrv_weekly_avg,
    hrv_baseline_low, hrv_baseline_high, hrv_status, hrv_json
)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(calendar_date) DO UPDATE SET
    hrv_last_night    = excluded.hrv_last_night,
    hrv_weekly_avg    = excluded.hrv_weekly_avg,
    hrv_baseline_low  = excluded.hrv_baseline_low,
    hrv_baseline_high = excluded.hrv_baseline_high,
    hrv_status        = excluded.hrv_status,
    hrv_json          = excluded.hrv_json
"""


def upsert_hrv(conn: sqlite3.Connection, entry: dict) -> None:
    """Insert or update the HRV columns for one day. Leaves sleep/daily columns alone."""
    baseline = entry.get("baseline") or {}
    values = (
        entry["calendarDate"],
        entry.get("lastNightAvg"),
        entry.get("weeklyAvg"),
        baseline.get("balancedLow"),
        baseline.get("balancedUpper"),
        entry.get("status"),
        json.dumps(entry),
    )
    conn.execute(HRV_UPSERT, values)

DAILY_UPSERT = """
INSERT INTO daily_health (
    calendar_date, resting_hr, body_battery_max, body_battery_min,
    stress_avg, stress_qualifier, steps, active_calories, daily_json
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(calendar_date) DO UPDATE SET
    resting_hr       = excluded.resting_hr,
    body_battery_max = excluded.body_battery_max,
    body_battery_min = excluded.body_battery_min,
    stress_avg       = excluded.stress_avg,
    stress_qualifier = excluded.stress_qualifier,
    steps            = excluded.steps,
    active_calories  = excluded.active_calories,
    daily_json       = excluded.daily_json
"""


def upsert_daily(conn: sqlite3.Connection, entry: dict) -> None:
    """Insert or update the daily-summary columns for one day. Leaves sleep/HRV columns alone."""
    heart = entry.get("heartRate") or {}
    battery = entry.get("bodyBattery") or {}
    stress = entry.get("stress") or {}
    steps = ((entry.get("movement") or {}).get("steps") or {}).get("value")
    calories = entry.get("calories") or {}
    values = (
        entry["calendarDate"],
        heart.get("restingValue"),
        battery.get("maxValue"),
        battery.get("minValue"),
        stress.get("avgLevel"),
        stress.get("qualifier"),
        steps,
        calories.get("burnedActive"),
        json.dumps(entry),
    )
    conn.execute(DAILY_UPSERT, values)