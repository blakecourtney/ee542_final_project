"""Workout analytics over the existing Garmin SQLite activities table."""
import sqlite3
from datetime import datetime


def analyze(conn: sqlite3.Connection, activity_type='running') -> dict:
    conn.row_factory = sqlite3.Row
    rows = conn.execute('''SELECT activity_id, start_time_local, distance_m,
        moving_duration_s, avg_hr FROM activities
        WHERE activity_type = ? ORDER BY start_time_local''', (activity_type,)).fetchall()
    sessions = []
    for r in rows:
        d, t = r['distance_m'], r['moving_duration_s']
        if not d or not t or d <= 0 or t <= 0:
            continue
        try:
            day = datetime.fromisoformat(r['start_time_local']).date().isoformat()
        except (ValueError, TypeError):
            continue
        sessions.append({'date': day, 'distance_km': round(d / 1000, 2),
                         'pace_min_per_km': round(t / 60 / (d / 1000), 2),
                         'avg_hr': r['avg_hr']})
    result = {'activity_type': activity_type, 'total_activities': len(rows),
              'valid_sessions': len(sessions), 'total_distance_km': round(sum(s['distance_km'] for s in sessions), 2),
              'sessions': sessions[-10:]}
    if len(sessions) >= 4:
        previous, recent = sessions[-4:-2], sessions[-2:]
        avg = lambda ss, k: sum(s[k] for s in ss) / len(ss)
        old_pace, new_pace = avg(previous, 'pace_min_per_km'), avg(recent, 'pace_min_per_km')
        result['recent_vs_previous_pace_change_pct'] = round((new_pace / old_pace - 1) * 100, 1)
        result['comparison_note'] = 'Last two valid sessions vs preceding two; unadjusted for route, terrain, or effort.'
    return result
