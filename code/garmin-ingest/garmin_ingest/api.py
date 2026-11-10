#connect to garmin api and pull profile data
from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator
import os
from dotenv import load_dotenv
from collections.abc import Iterator


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

if __name__ == "__main__":
    import json
    import sys

    client = make_client()
    activities = list(iter_all_activities(client))

    print(f"{len(activities)} activities, oldest: {activities[-1]['startTimeLocal']}",
          file=sys.stderr)
    print(json.dumps(activities, indent=2))