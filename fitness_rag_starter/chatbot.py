import json 
import os
from pathlib import Path

import faiss
import httpx
import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent
BASE_URL = os.getenv("LLM_API_BASE", "http://127.0.0.1:8001/v1").rstrip("/")
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    index_path = ROOT / "index/fitness.faiss"
    if not index_path.exists():
        raise SystemExit("Run python ingest.py first.")
    docs = json.loads((ROOT / "index/documents.json").read_text())
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
            qvec = np.asarray(encoder.encode([question], normalize_embeddings=True), dtype="float32")
            scores, ids = index.search(qvec, min(3, len(docs)))
            hits = [(docs[int(i)], float(s)) for i, s in zip(ids[0], scores[0]) if i >= 0]
            context = "\n\n".join(f"[{n}] {doc['title']}\n{doc['text']}" for n, (doc, _) in enumerate(hits, 1))
            system = ("You are a cautious fitness education assistant. Answer using ONLY the supplied context. "
                      "Cite context sections like [1]. If the context does not support an answer, say so. "
                      "Do not fabricate workout measurements or personalized diagnoses. "
                      "For alarming symptoms or injury concerns, recommend appropriate professional care.")
            try:
                response = client.post(f"{BASE_URL}/chat/completions", json={
                    "model": model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}],
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
