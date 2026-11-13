"""Pull activities from Garmin into the local database."""

from .api import make_client, iter_all_activities, fetch_sleep, fetch_hrv, fetch_daily
from .store import connect, upsert_activity, has_activity, upsert_sleep, upsert_hrv, upsert_daily
from datetime import date, timedelta
import time

DB_PATH = "data/garmin.db"

CHUNK_DAYS = 30      # the sleep endpoint refuses ranges much over 31 days
REFRESH_DAYS = 3     # recent days are re-fetched because they may have been partial

def sync_summaries(client, conn, full: bool = False) -> int:
    """Store new activities. Stop at the first one we already have, unless full=True.

    Returns how many activities were written."""
    written = 0
    for summary in iter_all_activities(client):
        if not full and has_activity(conn, summary["activityId"]):
            break
        upsert_activity(conn, summary)
        written += 1
    conn.commit()
    return written

def health_start_date(conn) -> date:
    """Where the next health sync should begin."""
    newest = conn.execute("SELECT MAX(calendar_date) FROM daily_health").fetchone()[0]
    if newest:
        return date.fromisoformat(newest) - timedelta(days=REFRESH_DAYS)
    oldest_activity = conn.execute("SELECT MIN(start_time_local) FROM activities").fetchone()[0]
    return date.fromisoformat(oldest_activity[:10])     # "2024-07-18 21:01:49" -> "2024-07-18"


def sync_health(client, conn) -> int:
    """Fetch sleep, HRV and daily summaries from the start date to today. Returns rows touched."""
    start = health_start_date(conn)
    today = date.today()
    days = set()
    while start <= today:
        end = min(start + timedelta(days=CHUNK_DAYS - 1), today)
        print(f"  health {start} .. {end}")
        #update daily health table
        for entry in fetch_sleep(client, start, end):
            upsert_sleep(conn, entry)
            days.add(entry["calendarDate"])
        for entry in fetch_hrv(client, start, end):
            upsert_hrv(conn, entry)
            days.add(entry["calendarDate"])
        for entry in fetch_daily(client, start, end):
            upsert_daily(conn, entry)
            days.add(entry["calendarDate"])
        conn.commit()            # save after each chunk
        time.sleep(2) #go to sleep after each chunk to prevent reaching garmin API request limit
        start = end + timedelta(days=1)          # the day after this chunk's end
    return len(days)

if __name__ == "__main__":
    import sys

    full = "--full" in sys.argv
    client = make_client()
    conn = connect(DB_PATH)
    written = sync_summaries(client, conn, full=full)
    total = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    print(f"{'Full' if full else 'Incremental'} sync: {written} written, {total} total")
    days = sync_health(client, conn)
    print(f"Health sync: {days} days updated")
    conn.close()