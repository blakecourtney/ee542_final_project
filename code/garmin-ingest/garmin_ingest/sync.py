"""Pull activities from Garmin into the local database."""

from .api import make_client, iter_all_activities
from .store import connect, upsert_activity, has_activity

DB_PATH = "data/garmin.db"


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


if __name__ == "__main__":
    import sys

    full = "--full" in sys.argv
    client = make_client()
    conn = connect(DB_PATH)
    written = sync_summaries(client, conn, full=full)
    total = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    print(f"{'Full' if full else 'Incremental'} sync: {written} written, {total} total")
    conn.close()