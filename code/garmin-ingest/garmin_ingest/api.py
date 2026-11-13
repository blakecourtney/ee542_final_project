#connect to garmin api and pull profile data
from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator
import os
from dotenv import load_dotenv
from collections.abc import Iterator
from datetime import date

def load_api_key():
    load_dotenv() #pulls api key from local .env file
    api_key = os.getenv("GARMIN_PERSONAL_API_KEY")
    if not api_key:
        raise RuntimeError("GARMIN_PERSONAL_API_KEY is not set (check your .env file)")
    return api_key

def make_client() -> GarminPersonalApiClient:
    """Return a Garmin client ready to make authenticated requests."""
    key = load_api_key()
    authenticator = PersonalApiAuthenticator()
    token = authenticator.obtain_token(key)
    return GarminPersonalApiClient(token.access_token)

def list_activities(client: GarminPersonalApiClient, start: int = 0, limit: int = 20) -> list[dict]:
    """Return one page of activity summaries."""
    return client.search_activities(start=start, limit=limit) or []

def iter_all_activities(client: GarminPersonalApiClient, page_size: int = 50) -> Iterator[dict]:
    """Yield every activity, page by page, until Garmin runs out."""
    start = 0
    while True:
        page = list_activities(client, start=start, limit=page_size)
        if not page:
            return
        yield from page
        if len(page) < page_size:
            return
        start += len(page)

def download_activity_file(client, activity_id: int) -> bytes:
    """Return Garmin's original download for an activity, as ZIP bytes."""
    return client.download_activity(activity_id)

def _dated(entries) -> list[dict]:
    """Keep only entries that have a calendarDate (drops empty no-data nights)."""
    return [e for e in (entries or []) if e.get("calendarDate")]


def fetch_sleep(client: GarminPersonalApiClient, start: date, end: date) -> list[dict]:
    """Sleep summaries for start..end inclusive. Garmin allows at most ~31 days per call."""
    data = client.get_daily_sleep_summaries(start, end)
    return _dated(data)# already a plain list


def fetch_hrv(client: GarminPersonalApiClient, start: date, end: date) -> list[dict]:
    """HRV summaries for start..end inclusive. Nights without HRV are simply absent."""
    data = client.get_daily_hrv_summaries(start, end) or {}
    return _dated(data.get("hrvSummaries"))# unwrap {"hrvSummaries": [...]}


def fetch_daily(client: GarminPersonalApiClient, start: date, end: date) -> list[dict]:
    """Daily wellness summaries (resting HR, body battery, stress) for start..end inclusive."""
    data = client.get_daily_summaries(start, end) or {}
    return _dated(data.get("data"))# unwrap {"data": [...]}

if __name__ == "__main__":
    from datetime import timedelta
    end = date.today()
    start = end - timedelta(days=29)
    for name, fn in [("sleep", fetch_sleep), ("hrv", fetch_hrv), ("daily", fetch_daily)]:
        entries = fn(client, start, end)
        print(name, len(entries), entries[0]["calendarDate"] if entries else None)