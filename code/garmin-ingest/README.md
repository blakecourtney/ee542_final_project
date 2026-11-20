# garmin-ingest

Pulls your workouts and daily health data from Garmin Connect's official **Personal API** into a local SQLite database, then summarizes it for the AI coach with one function call: `get_athlete_context()`.

## What it gives you

- **Activities.** Every workout in your history: type, start time, distance, duration, HR, power and training load, plus Garmin's full summary as JSON.
- **Daily health.** One row per day, with sleep, HRV, resting HR, body battery and stress.
- **Athlete context.** A compact summary for the chatbot, covering recovery against your own baselines, this week's load against your 6-week average, and recent sessions.

## Setup

Requires **Python 3.12+**. On a Mac with conda, run `conda deactivate` first.

```bash
cd code/garmin-ingest
uv venv --python 3.12              # or: python3.12 -m venv .venv
source .venv/bin/activate
uv pip install garmin-connect-personal-api-python python-dotenv fitdecode
```

To install everything for the whole project (portal and RAG chatbot), run `uv pip install -r ../../requirements.txt`.

## Add your Garmin API key

1. Log in at **connect.garmin.com** and open the **Personal API Key** page in settings.
2. Create a key, choose an expiration, and **copy it right away**. Garmin shows it only once.
3. Create a file named `.env` in the project root (`final_project/.env`) containing:
   ```
   GARMIN_PERSONAL_API_KEY=paste-your-key-here
   ```
4. Check that it works:
   ```bash
   python -c "from garmin_ingest.api import make_client; print(make_client().get_user_profile_settings()['timeZone'])"
   ```
   It should print your time zone.

`.env` is listed in `.gitignore`, so **never commit it or share it**. If the key leaks, delete it on Garmin Connect and create a new one.

## Sync your data

Run these from `code/garmin-ingest`:

```bash
python -m garmin_ingest.sync           # normal sync
python -m garmin_ingest.sync --full    # also re-check every past activity
```

- **First run** downloads your full activity list and backfills daily health data in 30-day chunks.
- **Later runs** fetch only new activities and refresh the last 3 days of health data, since today's numbers keep changing until midnight.
- **Interrupted runs** resume automatically on the next run, because progress is saved after every chunk.
- **Use `--full`** when you've edited old activities in the Garmin app (renamed them, for example) and want those changes picked up.

From Python, for example a web app's sync button:
```python
from garmin_ingest.sync import run_sync
run_sync()   # {"activities_written": 2, "health_days_updated": 4}
```

## Get the athlete context

```python
from datetime import datetime
from garmin_ingest.context import get_athlete_context

get_athlete_context()                        # as of today
get_athlete_context(datetime(2026, 11, 8))   # as of a past date
```

Or print it from the terminal: `python -m garmin_ingest.context`

| Field | Meaning |
|---|---|
| `recovery.sleep_hours`, `sleep_score` | the night before `as_of` |
| `recovery.hrv_last_night`, `hrv_normal_range`, `hrv_vs_normal` | `"below"`, `"within"` or `"above"` your normal range |
| `recovery.resting_hr`, `resting_hr_30d_avg`, `resting_hr_vs_avg` | bpm; a positive difference means elevated |
| `recovery.body_battery_peak` | 0–100; how recharged you were that morning |
| `last_7_days` | `sessions`, `hours`, `training_load` |
| `last_42_days` | `weekly_avg_hours`, `weekly_avg_load` |
| `load_ratio` | this week ÷ 6-week average; ~1.0 is a normal week, >1.3 is ramping fast |
| `recent_sessions` | last 7 workouts: date, type, duration, distance, HR, load, Garmin label |

**`null` means no data** (for example, the watch wasn't worn). It never means zero.

## Project layout

```
garmin-ingest/
├── garmin_ingest/
│   ├── api.py          # all Garmin API calls (auth, activities, sleep, HRV, daily summaries)
│   ├── store.py        # SQLite schema and upserts
│   ├── sync.py         # incremental sync logic; run_sync()
│   ├── context.py      # get_athlete_context()
│   └── fit_parse.py    # extracts .fit files from Garmin downloads (work in progress)
└── data/               # created on first sync; ignored by git
    └── garmin.db
```

Database tables:
- **`activities`:** one row per workout, keyed by `activity_id`
- **`daily_health`:** one row per date, keyed by `calendar_date`

Both tables keep Garmin's original JSON (`summary_json`, `sleep_json`, `hrv_json`, `daily_json`), so fields that aren't columns can still be queried, for example with `json_extract(summary_json, '$.trainingEffectLabel')`.

## Good to know

- **Rate limit:** Garmin allows about **100 requests per hour-scale window**. Normal syncs use under 10. If you see `HTTP 429`, wait about an hour and rerun; nothing is lost.
- **The sleep endpoint** accepts at most about 31 days per request, which is why syncing works in 30-day chunks.
- **Dates:** sleep and HRV for a given `calendar_date` describe the night **ending** that morning. Daily summaries cover that calendar day.
- **Privacy:** `data/garmin.db` holds personal health data, GPS coordinates and your name. Keep it out of git and out of anything you share.
