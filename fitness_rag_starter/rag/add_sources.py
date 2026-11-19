
import json
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "knowledge_base"
MANIFEST = KB / "manifest.json"

SOURCES = [
    (
        "sprint_interval_vo2max",
        "Sprint Interval Training and VO2 Max",
        "endurance",
        "Research article via PubMed Central",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC13385658/"
    ),
    (
        "concurrent_training_review",
        "Optimizing Concurrent Training Programs",
        "programming",
        "Research article via PubMed Central",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC11688070/"
    ),
    (
        "concurrent_training_meta",
        "Concurrent Strength and Endurance Training Meta-analysis",
        "programming",
        "Research article via PubMed Central",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC10933151/"
    ),
    (
        "athlete_sleep_recovery",
        "The Sleep and Recovery Practices of Athletes",
        "recovery",
        "Research article via PubMed Central",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC8072992/"
    ),
    (
        "hrv_recovery_review",
        "Monitoring Training Adaptation and Recovery Using HRV",
        "recovery",
        "Research article via PubMed Central",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC12787763/"
    ),
    (
        "hrv_strength_conditioning",
        "HRV Applications in Strength and Conditioning",
        "recovery",
        "Research article via PubMed Central",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC11204851/"
    ),
    (
        "garmin_training_readiness",
        "Garmin Training Readiness",
        "wearables",
        "Garmin",
        "https://www.garmin.com/en-IE/garmin-technology/running-science/physiological-measurements/training-readiness/"
    ),
    (
        "garmin_training_load",
        "Garmin Training Load",
        "wearables",
        "Garmin",
        "https://www.garmin.com/en-IE/garmin-technology/running-science/physiological-measurements/training-load/"
    ),
    (
        "garmin_hrv_status",
        "Garmin HRV Status",
        "wearables",
        "Garmin",
        "https://www.garmin.com/en-GB/garmin-technology/health-science/hrv-status/"
    ),
    (
        "garmin_load_focus",
        "Garmin Training Load Focus",
        "wearables",
        "Garmin",
        "https://www.garmin.com/en-US/garmin-technology/running-science/physiological-measurements/training-load-focus/"
    ),
    (
        "garmin_body_battery",
        "Garmin Body Battery FAQ",
        "wearables",
        "Garmin",
        "https://support.garmin.com/en-US/aviation/faq/VOFJAsiXut9K19k1qEn5W5/"
    ),
    (
        "cdc_getting_started",
        "CDC Getting Started With Physical Activity",
        "safety",
        "Centers for Disease Control and Prevention",
        "https://www.cdc.gov/healthy-weight-growth/physical-activity/getting-started.html"
    ),
]

ALLOWED_HOSTS = {
    "pmc.ncbi.nlm.nih.gov",
    "www.garmin.com",
    "support.garmin.com",
    "www.cdc.gov",
}

def main():
    manifest = json.loads(MANIFEST.read_text())
    existing_ids = {d["id"] for d in manifest}

    session = requests.Session()
    session.headers.update({
        "User-Agent": "EE542FitnessRAG/1.0 (educational research)"
    })

    for doc_id, title, category, organization, url in SOURCES:
        if doc_id in existing_ids:
            print(f"Already registered: {doc_id}")
            continue

        host = urlparse(url).hostname
        if host not in ALLOWED_HOSTS:
            print(f"Skipped unapproved host: {url}")
            continue

        destination = KB / "raw" / category / f"{doc_id}.html"
        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            response = session.get(
                url,
                timeout=30,
                allow_redirects=True
            )
            response.raise_for_status()

            final_host = urlparse(response.url).hostname
            if final_host not in ALLOWED_HOSTS:
                raise ValueError("Redirected to an unapproved host")

            content_type = response.headers.get(
                "Content-Type", ""
            ).lower()

            if "html" not in content_type:
                raise ValueError(
                    f"Unexpected content type: {content_type}"
                )

            if len(response.content) > 10_000_000:
                raise ValueError("HTML file exceeds size limit")

            destination.write_bytes(response.content)

            manifest.append({
                "id": doc_id,
                "title": title,
                "organization": organization,
                "category": category,
                "file": str(destination.relative_to(KB)),
                "url": url,
                "stop_at_references": False,
                "license_status": "review_before_redistribution"
            })

            existing_ids.add(doc_id)
            print(f"Downloaded: {title}")

        except Exception as exc:
            print(f"FAILED: {title}: {exc}")

    MANIFEST.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8"
    )

    print(f"\nRegistered documents: {len(manifest)}")


if __name__ == "__main__":
    main()

