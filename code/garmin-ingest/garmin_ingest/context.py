"""What the chatbot calls to learn about the athlete's recent training."""
import sqlite3
from datetime import datetime, timedelta, date  
from .store import connect

DB_PATH = "data/garmin.db"

FETCH_ROW = "SELECT * FROM daily_health WHERE calendar_date = ?"
RESTING_HR_AVG = """
SELECT AVG(resting_hr) FROM daily_health
WHERE calendar_date >= ? AND calendar_date < ?
"""

WINDOW_TOTALS = """
SELECT COUNT(*)                      AS sessions,
       SUM(moving_duration_s) / 3600 AS hours,
       SUM(training_load)            AS load
FROM activities
WHERE start_time_local >= ? AND start_time_local < ?
"""

RECENT_SESSIONS = """
SELECT start_time_local,
       activity_type,
       moving_duration_s,
       distance_m,
       avg_hr,
       training_load,
       json_extract(summary_json, '$.trainingEffectLabel') AS label
FROM activities
WHERE start_time_local < ?
ORDER BY start_time_local DESC
LIMIT ?
"""

def scaled(x, divisor: float = 1, ndigits: int | None = None):
    """x / divisor, rounded. Missing (None) stays None instead of crashing."""
    if x is None:
        return None
    return round(x / divisor, ndigits)

def health_row(conn, day: str) -> sqlite3.Row | None:
    """The daily_health row for a calendar date, or None if there isn't one."""
    return conn.execute(FETCH_ROW, (day,)).fetchone()

def resting_hr_baseline(conn, day: str, days: int = 30) -> float | None:
    """Average resting HR over the `days` before `day` (not including it)."""
    start = (date.fromisoformat(day) - timedelta(days=days)).isoformat()
    return conn.execute(RESTING_HR_AVG, (start, day)).fetchone()[0]

def hrv_vs_normal(last_night, low, high) -> str | None:
    """'below' / 'within' / 'above' your normal HRV range, or None if anything is missing."""
    if last_night is None or low is None or high is None:
        return None
    if last_night < low:
        return "below"
    if last_night > high:
        return "above"
    return "within"

def recovery_for(conn, day: str) -> dict:
    """The recovery section of the athlete context for one date."""
    row = health_row(conn, day)
    if row is None:
        return {"date": day, "data": None}#no health data at all for this date: watch not worn, battery died, etc
    #convert sleep seconds to hours, if it's not missing
    sleep_s = row["sleep_s"]
    sleep_hours = scaled(row["sleep_s"], 3600, 1)#compare resting HR vs your recent average
    resting = row["resting_hr"]
    baseline = resting_hr_baseline(conn, day)
    if resting is not None and baseline is not None:
        hr_diff = round(resting - baseline,1) #how many bpm above (or below) average
    else:
        hr_diff = None

    return {
        "date": day,
        "sleep_hours": sleep_hours,
        "sleep_score": row["sleep_score"],
        "hrv_last_night": row["hrv_last_night"],
        "hrv_normal_range": [row["hrv_baseline_low"], row["hrv_baseline_high"]],
        "hrv_vs_normal": hrv_vs_normal(row["hrv_last_night"], row["hrv_baseline_low"], row["hrv_baseline_high"]),
        "resting_hr": resting,
        "resting_hr_30d_avg": scaled(baseline, 1, 1),
        "resting_hr_vs_avg": hr_diff,
        "body_battery_peak": row["body_battery_max"],
    }

def window_totals(conn, day: str, days: int) -> dict:
    """Sessions, hours and training load over the `days` days ending on `day` (inclusive)."""
    end = (date.fromisoformat(day) + timedelta(days=1)).isoformat()# exclusive upper bound
    start = (date.fromisoformat(day) - timedelta(days=days-1)).isoformat()# N-1 days before day
    row = conn.execute(WINDOW_TOTALS, (start, end)).fetchone()
    return {"sessions": row["sessions"], 
            "hours": round(row["hours"] or 0, 1), 
            "load": round(row["load"] or 0)}

def load_for(conn, day: str) -> dict:
    """Training volume and load: this week vs your 6-week average."""
    week = window_totals(conn, day, 7)
    six_weeks = window_totals(conn, day, 42)
    weekly_avg_hours = round(six_weeks["hours"] / 6, 1)
    avg_load = six_weeks["load"] / 6
    weekly_avg_load = round(avg_load)
    if avg_load:
        load_ratio = round(week["load"] / avg_load, 2)
    else:
        load_ratio = None# no history to compare against
    return {
        "last_7_days": {
            "sessions": week["sessions"],
            "hours": week["hours"],
            "training_load": week["load"],
        },
        "last_42_days": {
            "weekly_avg_hours": weekly_avg_hours,
            "weekly_avg_load": weekly_avg_load,
        },
        "load_ratio": load_ratio,
    }

def recent_sessions(conn, day: str, limit: int = 7) -> list[dict]:
    """The most recent workouts up to and including `day`, newest first."""
    end = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    rows = conn.execute(RECENT_SESSIONS, (end, limit)).fetchall()
    sessions = []
    for r in rows:
        sessions.append({
            "date": r["start_time_local"][:10],
            "time": r["start_time_local"][11:16],
            "type": r["activity_type"],
            "duration_min": scaled(r["moving_duration_s"], 60),
            "distance_km": scaled(r["distance_m"], 1000, 1),
            "avg_hr": scaled(r["avg_hr"]),
            "training_load": scaled(r["training_load"]),
            "label": r["label"],
        })
    return sessions

def get_athlete_context(as_of: datetime | None = None) -> dict:
    """Summary of the athlete's recent training and recovery, for the chatbot."""
    day = (as_of or datetime.now()).date().isoformat()
    conn = connect(DB_PATH)
    try:
        return {
            "as_of": day,
            "recovery": recovery_for(conn, day),
            **load_for(conn, day),
            "recent_sessions": recent_sessions(conn, day),
        }
    finally:
        conn.close()

if __name__ == "__main__":
    import json
    print(json.dumps(get_athlete_context(), indent=2))
    print(json.dumps(get_athlete_context(datetime(2026, 11, 1)), indent=2))