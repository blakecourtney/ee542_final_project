
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rag"))

from build_index import load_document

KB = ROOT / "knowledge_base"
manifest = json.loads(
    (KB / "manifest.json").read_text(encoding="utf-8")
)

print(f"{'DOCUMENT':42} {'SECTIONS':>9} {'WORDS':>9} STATUS")
print("-" * 76)

for doc in manifest:
    path = KB / doc["file"]

    try:
        sections = load_document(path, doc)
        words = sum(
            len(section["text"].split())
            for section in sections
        )

        status = "OK" if words >= 200 else "REVIEW"

        print(
            f"{doc['id'][:42]:42} "
            f"{len(sections):9} "
            f"{words:9} {status}"
        )

    except Exception as exc:
        print(f"{doc['id'][:42]:42} ERROR: {exc}")

