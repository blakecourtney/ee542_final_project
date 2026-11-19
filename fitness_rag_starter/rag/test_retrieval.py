
import json
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = ROOT / "index_v2"

config = json.loads(
    (INDEX_DIR / "config.json").read_text()
)

chunks = json.loads(
    (INDEX_DIR / "chunks.json").read_text()
)

index = faiss.read_index(
    str(INDEX_DIR / "fitness.faiss")
)

encoder = SentenceTransformer(config["embedding_model"])

print("Fitness Knowledge Retrieval Test")
print("Type 'quit' to exit.")

while True:
    question = input("\nQuestion: ").strip()

    if question.lower() in {"quit", "exit"}:
        break

    if not question:
        continue

    vector = encoder.encode(
        [question],
        normalize_embeddings=True
    )

    vector = np.asarray(vector, dtype="float32")

    scores, ids = index.search(
        vector,
        min(5, index.ntotal)
    )

    for rank, (idx, score) in enumerate(
        zip(ids[0], scores[0]), start=1
    ):
        if idx < 0:
            continue

        chunk = chunks[int(idx)]

        print(f"\n[{rank}] {chunk['title']}")
        print(f"Category: {chunk['category']}")
        print(f"Section: {chunk['section']}")
        print(f"Page: {chunk['page']}")
        print(f"Similarity: {score:.3f}")
        print(f"Source: {chunk['source_url']}")
        print(f"\n{chunk['text'][:700]}...")
PY

