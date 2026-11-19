import json 
import os
from pathlib import Path

import faiss
import httpx
import numpy as np
from sentence_transformers import SentenceTransformer
import sys
from rag.retriever import retrieve_diverse

ROOT = Path(__file__).resolve().parent
BASE_URL = os.getenv("LLM_API_BASE", "http://127.0.0.1:8001/v1").rstrip("/")
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

GARMIN_ROOT = ROOT.parent / "code" / "garmin-ingest"
sys.path.insert(0, str(GARMIN_ROOT))

from garmin_ingest.context import get_athlete_context


def main():
    index_path = ROOT / "index_v2/fitness.faiss"
    if not index_path.exists():
        raise SystemExit("Run python ingest.py first.")
    docs = json.loads(
        (ROOT / "index_v2/chunks.json").read_text()
    )
    index = faiss.read_index(str(index_path))
    encoder = SentenceTransformer(EMBED_MODEL)
    with httpx.Client(timeout=180) as client:
        try:
            models = client.get(f"{BASE_URL}/models")
            models.raise_for_status()
            model = os.getenv("LLM_MODEL") or models.json()["data"][0]["id"]
        except Exception as exc:
            raise SystemExit(f"LLM server unavailable at {BASE_URL}: {exc}")
        print(f"Fitness RAG ready (model: {model}). Type 'quit' to exit.")
        while True:
            try:
                question = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if question.lower() in {"quit", "exit"}:
                break
            if not question:
                continue
            try:
                athlete_context = get_athlete_context()
                print("\n[DEBUG] Garmin context:")
                print(json.dumps(athlete_context, indent=2))
                athlete_json = json.dumps(athlete_context, indent=2)
            except Exception as exc:
                print(f"Garmin context unavailable: {exc}")
                athlete_json = "No Garmin athlete data available."
            qvec = np.asarray(encoder.encode([question], normalize_embeddings=True), dtype="float32")
            scores, ids = index.search(qvec, min(3, len(docs)))
            hits = retrieve_diverse(
                question,
                encoder,
                index,
                docs,
                candidate_k=12,
                final_k=5,
                max_per_document=3,
            )
            context = "\n\n".join(
                (
                    f"[{n}] {doc['title']}\n"
                    f"Section: {doc['section']}\n"
                    f"PDF page: {doc.get('page')}\n"
                    f"Source: {doc['source_url']}\n"
                    f"Passage:\n{doc['text']}"
                )
                for n, (doc, _) in enumerate(hits, 1)
            )
            system = """
                You are a fitness coaching assistant that combines retrieved
                fitness knowledge with structured Garmin athlete data.

                DATA INTERPRETATION RULES:
                1. Use only measurements explicitly present in the Garmin data.
                2. Never invent missing workout, sleep, HRV, or recovery values.
                3. A null value means unavailable, not zero.
                4. Preserve measurement units exactly.
                5. Values ending in "_vs_avg" represent absolute differences,
                not percentages, unless explicitly specified otherwise.
                6. Do not convert absolute differences into percentages
                without showing the calculation.
                7. Preserve activity types. Hiking, cycling, walking, and
                running are distinct activities.
                8. Do not infer workout intensity solely from an activity label.
                9. Garmin Body Battery is generally measured on a 0–100 scale.
                Do not describe a value of 5 as moderate recovery.
                10. Do not treat a single recovery measurement as a diagnosis.

                COACHING RULES:
                1. Ground recommendations in retrieved fitness knowledge.
                2. Use Garmin metrics to personalize recommendations.
                3. Distinguish observations from interpretations and suggestions.
                4. Cite retrieved fitness knowledge using [1], [2], etc.
                5. Explicitly acknowledge missing or uncertain data.
                6. Avoid medical diagnoses or definitive claims about readiness.
                7. Recommend qualified professional advice when appropriate.

                RESPONSE FORMAT:
                - Recent training observations
                - Recovery observations
                - Suggested training focus
                - Data limitations

                Keep recommendations practical and concise.
                Distinguish activities explicitly present in Garmin records
                from activities that are merely recommended. Never claim the
                athlete performed resistance training unless the supplied
                activity data confirms it.

                Do not interpret missing activity records as proof that an
                activity never occurred.

                Use retrieved scientific passages to support recommendations.
                Do not present a specific training prescription as universally
                appropriate without considering the athlete's goals,
                experience, and recovery information.
                """
            try:
                response = client.post(f"{BASE_URL}/chat/completions", json={
                    "model": model,
                    "messages": [{"role": "system", "content": system},
                                 {
                                    "role": "user",
                                    "content": (
                                        f"Fitness knowledge:\n{context}\n\n"
                                        f"Garmin athlete data:\n{athlete_json}\n\n"
                                        f"Question: {question}"
                                    )
                                }],
                    "temperature": 0.2, "max_tokens": 450
                })
                response.raise_for_status()
                print("\nCoach:", response.json()["choices"][0]["message"]["content"])
                print("\nRetrieved sources:")
                for n, (doc, score) in enumerate(hits, 1):
                    print(f"  [{n}] {doc['title']} ({doc['source']}; similarity={score:.2f})")
            except Exception as exc:
                print(f"LLM request failed: {exc}")


if __name__ == "__main__":
    main()
