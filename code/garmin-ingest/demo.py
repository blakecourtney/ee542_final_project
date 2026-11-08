"""Run a standalone analytics demo using the existing database or bundled sample.

Usage:
  python demo.py --sample
  python demo.py --db data/garmin.db --goal endurance
"""
import argparse
import json
import sqlite3
from pathlib import Path
from garmin_ingest.analytics import analyze
from garmin_ingest.recommend import recommend

SCHEMA = '''CREATE TABLE IF NOT EXISTS activities (
 activity_id INTEGER PRIMARY KEY, activity_type TEXT, start_time_local TEXT,
 start_time_gmt TEXT, distance_m REAL, moving_duration_s REAL, avg_hr REAL,
 max_hr REAL, avg_power_w REAL, training_load REAL, aerobic_te REAL,
 summary_json TEXT NOT NULL)'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sample', action='store_true', help='Use bundled sample without needing an API key')
    parser.add_argument('--db', default='data/garmin.db')
    parser.add_argument('--goal', choices=['endurance', 'pace'], default='endurance')
    args = parser.parse_args()
    if args.sample:
        conn = sqlite3.connect(':memory:')
        conn.execute(SCHEMA)
        raw = (Path(__file__).parent / 'sample.json').read_text()
        # Teammate's sample includes a console-output header before the JSON object.
        sample = json.loads(raw[raw.index('{'):])
        conn.execute('''INSERT INTO activities
          (activity_id, activity_type, start_time_local, start_time_gmt,
           distance_m, moving_duration_s, avg_hr, max_hr, avg_power_w,
           training_load, aerobic_te, summary_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
           (sample['activityId'], sample.get('activityType', {}).get('typeKey'),
            sample.get('startTimeLocal'), sample.get('startTimeGMT'),
            sample.get('distance'), sample.get('movingDuration'),
            sample.get('averageHR'), sample.get('maxHR'), sample.get('avgPower'),
            sample.get('activityTrainingLoad'), sample.get('aerobicTrainingEffect'),
            json.dumps(sample)))
    else:
        if not Path(args.db).is_file():
            parser.error(f'Database not found: {args.db}. Use --sample for a standalone demo.')
        conn = sqlite3.connect(args.db)
    try:
        metrics = analyze(conn)
        print('=== WORKOUT ANALYTICS ===')
        print(json.dumps(metrics, indent=2))
        print('\n=== TRAINING FEEDBACK ===')
        for suggestion in recommend(metrics, args.goal):
            print('- ' + suggestion)
    finally:
        conn.close()

if __name__ == '__main__':
    main()
