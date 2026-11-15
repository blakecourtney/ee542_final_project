import json
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    docs = json.loads((ROOT / "data/fitness_knowledge.json").read_text())
    if not docs:
        raise ValueError("No documents to index")
    encoder = SentenceTransformer(MODEL)
    vectors = encoder.encode([d["title"] + ". " + d["text"] for d in docs], normalize_embeddings=True)
    vectors = np.asarray(vectors, dtype="float32")
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    out = ROOT / "index"
    out.mkdir(exist_ok=True)
    faiss.write_index(index, str(out / "fitness.faiss"))
    (out / "documents.json").write_text(json.dumps(docs, indent=2))
    print(f"Indexed {len(docs)} knowledge entries in {out}")


if __name__ == "__main__":
    main()
