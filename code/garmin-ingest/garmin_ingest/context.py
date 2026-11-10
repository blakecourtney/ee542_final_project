"""What the chatbot calls to learn about the athlete's recent training."""


from datetime import datetime
def get_athlete_context(as_of: datetime | None = None) -> dict:
    """Summary of recent training for the chatbot. FAKE DATA for now."""
    return {
        "as_of": "2026-11-10T12:00:00",
        "last_7_days": {"sessions": 6, "hours": 7.5, "training_load": 610},
        "last_42_days": {"weekly_avg_hours": 6.1, "weekly_avg_load": 480},
        "load_ratio": 1.27,
        "recent_sessions": [
            {"date": "2026-11-04", "type": "running", "duration_min": 49,
             "distance_km": 8.1, "avg_hr": 165, "label": "TEMPO"},
        ],
        "recovery": {"sleep_hours_last_night": 6.2, "resting_hr": 52, "hrv_ms": 58},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(get_athlete_context(), indent=2))