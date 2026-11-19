
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "knowledge_base"
MANIFEST = KB / "manifest.json"

SOURCES = [
    ("sprint_interval_vo2max", "endurance",
     "https://pmc.ncbi.nlm.nih.gov/articles/PMC13385658/"),
    ("concurrent_training_review", "programming",
     "https://pmc.ncbi.nlm.nih.gov/articles/PMC11688070/"),
    ("concurrent_training_meta", "programming",
     "https://pmc.ncbi.nlm.nih.gov/articles/PMC10933151/"),
    ("athlete_sleep_recovery", "recovery",
     "https://pmc.ncbi.nlm.nih.gov/articles/PMC8072992/"),
    ("hrv_recovery_review", "recovery",
     "https://pmc.ncbi.nlm.nih.gov/articles/PMC12787763/"),
    ("hrv_strength_conditioning", "recovery",
     "https://pmc.ncbi.nlm.nih.gov/articles/PMC11204851/"),
]

manifest = json.loads(MANIFEST.read_text())
existing = {doc["id"] for doc in manifest}

for doc_id, category, url in SOURCES:
    if doc_id in existing:
        continue

    folder = KB / "raw" / category
    candidates = [
        folder / f"{doc_id}.pdf",
        folder / f"{doc_id}.html",
    ]

    path = next((p for p in candidates if p.exists()), None)

    if path is None:
        print(f"Not downloaded yet: {doc_id}")
        continue

    manifest.append({
        "id": doc_id,
        "title": doc_id.replace("_", " ").title(),
        "organization": "Research article via PubMed Central",
        "category": category,
        "file": str(path.relative_to(KB)),
        "url": url,
        "stop_at_references": path.suffix == ".pdf",
        "license_status": "review_before_redistribution",
    })

    existing.add(doc_id)
    print(f"Registered: {doc_id}")

MANIFEST.write_text(
    json.dumps(manifest, indent=2),
    encoding="utf-8"
)

print(f"\nTotal registered documents: {len(manifest)}")

