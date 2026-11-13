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

def health_row(conn, day: str) -> sqlite3.Row | None:
    """The daily_health row for a calendar date, or None if there isn't one."""
    return conn.execute(FETCH_ROW, (day,)).fetchone()

def resting_hr_baseline(conn, day: str, days: int = 30) -> float | None:
    """Average resting HR over the `days` before `day` (not including it)."""
    start = (date.fromisoformat(day) - timedelta(days=days)).isoformat()
    return conn.execute(RESTING_HR_AVG, (start,day)).fetchone()[0]

def hrv_vs_normal(last_night, low, high) -> str | None:
    """'below' / 'within' / 'above' your normal HRV range, or None if anything is missing."""
    if(last_night < low):
        return 'below'
    elif(last_night > high):
        return 'above'
    elif((last_night > low) and (last_night < high)):
        return 'within'
    else:
        return None

def recovery_for(conn, day: str) -> dict:
    """The recovery section of the athlete context for one date."""
    row = health_row(conn, day)
    if row is None:
        return {"date": day, "data": None}#no health data at all for this date: watch not worn, battery died, etc

    #convert sleep seconds to hours, if it's not missing
    sleep_s = row["sleep_s"]
    sleep_hours = round(sleep_s / 3600, 1) if sleep_s is not None else None

    #compare resting HR vs your recent average
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
        "resting_hr_30d_avg": round(baseline, 1) if baseline is not None else None,
        "resting_hr_vs_avg": hr_diff,
        "body_battery_peak": row["body_battery_max"],
    }


def get_athlete_context(as_of: datetime | None = None) -> dict:
    """Summary of recent training for the chatbot. Recovery is real; the rest is still fake."""
    day = (as_of or datetime.now()).date().isoformat()
    conn = connect(DB_PATH)
    try:
        return {
            "as_of": day,
            "recovery": recovery_for(conn, day),
            # still fake, replaced in the next steps:
            "last_7_days": {"sessions": 6, "hours": 7.5, "training_load": 610},
            "last_42_days": {"weekly_avg_hours": 6.1, "weekly_avg_load": 480},
            "load_ratio": 1.27,
            "recent_sessions": [],
        }
    finally:
        conn.close()

if __name__ == "__main__":
    import json

    print(json.dumps(get_athlete_context(), indent=2))                          # today
    print(json.dumps(get_athlete_context(datetime(2026, 11, 8)), indent=2))     # a known bad day