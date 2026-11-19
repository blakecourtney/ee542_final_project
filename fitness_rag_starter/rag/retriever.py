
from collections import Counter

import numpy as np


def retrieve_diverse(
    question,
    encoder,
    index,
    chunks,
    candidate_k=12,
    final_k=5,
    max_per_document=3,
):
    """Return relevant passages with document diversity."""
    qvec = np.asarray(
        encoder.encode(
            [question],
            normalize_embeddings=True
        ),
        dtype="float32",
    )

    scores, ids = index.search(
        qvec,
        min(candidate_k, index.ntotal),
    )

    selected = []
    per_document = Counter()
    seen_texts = set()

    for idx, score in zip(ids[0], scores[0]):
        if idx < 0:
            continue

        doc = chunks[int(idx)]
        document_id = doc["document_id"]
        text_key = doc["text"].strip().lower()

        if text_key in seen_texts:
            continue

        if per_document[document_id] >= max_per_document:
            continue

        selected.append((doc, float(score)))
        per_document[document_id] += 1
        seen_texts.add(text_key)

        if len(selected) >= final_k:
            break

    return selected

