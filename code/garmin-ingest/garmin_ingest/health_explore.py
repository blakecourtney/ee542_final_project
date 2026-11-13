import json
from datetime import date, timedelta

from .api import make_client

client = make_client()
end = date.today()
start = end - timedelta(days=6)   # the last 7 days

for name, fn in [
    ("sleep", client.get_daily_sleep_summaries),
    ("hrv", client.get_daily_hrv_summaries),
    ("daily", client.get_daily_summaries),
]:
    data = fn(start, end)
    with open(f"sample_{name}.json", "w") as f:
        json.dump(data, f, indent=2)
    print(name, type(data).__name__)


def unwrap(data):
    """Return the per-day list, whatever the endpoint's shape."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("hrvSummaries") or data.get("data") or []
    return []


end = date.today()

# 1. Find the sleep endpoint's maximum range
for days in (31, 45, 60, 89):
    start = end - timedelta(days=days - 1)
    try:
        entries = client.get_daily_sleep_summaries(start, end) or []
        print(f"sleep {days:3} days: OK, {len(entries)} entries")
    except Exception as exc:
        print(f"sleep {days:3} days: FAILED ({str(exc)[:60]})")

# 2. Look at entries with no date
start = end - timedelta(days=29)
entries = client.get_daily_sleep_summaries(start, end) or []
undated = [e for e in entries if not e.get("calendarDate")]
print(f"\n{len(undated)} of {len(entries)} sleep entries have no calendarDate")
if undated:
    print(json.dumps(undated[0], indent=2)[:1500])