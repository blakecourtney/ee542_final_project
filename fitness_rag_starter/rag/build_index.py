
import json
import re
import hashlib
from pathlib import Path

import fitz
import faiss
import numpy as np
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "knowledge_base"
OUT = ROOT / "index_v2"

MODEL = "sentence-transformers/all-MiniLM-L6-v2"

CHUNK_WORDS = 350
OVERLAP_WORDS = 50


def clean_text(text):
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def is_references_heading(text):
    """Identify a standalone bibliography heading."""
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return normalized in {
        "references",
        "bibliography",
        "works cited",
        "literature cited",
    }


def clean_pdf_boilerplate(text):
    """Remove common browser-print navigation and cookie text."""
    unwanted_patterns = [
        r"^Shop the holiday sale!.*$",
        r"^GARMIN TECHNOLOGY$",
        r"^GARMIN COACH$",
        r"^GARMIN HUMAN PERFORMANCE LAB$",
        r"^FILTER BY CATEGORY$",
        r"^SHOP SMARTWATCHES$",
        r"^Check product pages for feature compatibility\.$",
        r"^ACCEPT$",
        r"^DECLINE$",
        r"^This site uses cookies.*$",
        r"^purposes\. You may choose.*$",
        r"^technologies, or further manage.*$",
    ]

    lines = text.splitlines()
    cleaned = []

    for line in lines:
        stripped = line.strip()

        if any(
            re.match(pattern, stripped, flags=re.IGNORECASE)
            for pattern in unwanted_patterns
        ):
            continue

        cleaned.append(line)

    return clean_text("\n".join(cleaned))


def is_low_information_garmin_page(text):
    """Detect Garmin pages dominated by navigation or legal text."""
    lower = text.lower()

    noise_terms = [
        "site map",
        "terms of use",
        "privacy",
        "security",
        "digital accessibility",
        "do not share my personal information",
        "all rights reserved",
        "customer service",
        "platforms for business",
    ]

    noise_count = sum(term in lower for term in noise_terms)

    # Short pages containing many legal/footer elements
    if len(text.split()) < 180 and noise_count >= 4:
        return True

    return False


def load_pdf(path, stop_at_references=False):
    """Extract PDF text, skipping bibliography sections."""
    sections = []
    in_references = False

    with fitz.open(path) as pdf:
        for page_num, page in enumerate(pdf, start=1):
            blocks = page.get_text("blocks", sort=True)
            lines = []

            for block in blocks:
                if len(block) < 5 or not isinstance(block[4], str):
                    continue

                for line in block[4].splitlines():
                    line = line.strip()
                    if not line:
                        continue

                    if stop_at_references and is_references_heading(line):
                        in_references = True
                        break

                    if not in_references:
                        lines.append(line)

                if in_references:
                    break

            if in_references:
                print(
                    f"  References detected near PDF page {page_num}; "
                    "stopping extraction"
                )
                break

            text = clean_text("\n".join(lines))
            if "garmin_" in path.stem.lower():
                text = clean_pdf_boilerplate(text)
            if "garmin_" in path.stem.lower():
                if is_low_information_garmin_page(text):
                    continue

            if len(text) < 80:
                continue

            sections.append({
                "section": f"PDF page {page_num}",
                "page": page_num,
                "text": text,
            })

    return sections



def load_html(path):
    soup = BeautifulSoup(
        path.read_text(encoding="utf-8"),
        "lxml"
    )

    for tag in soup.select(
        "script, style, nav, footer, header, aside, "
        ".ref-list, .ref-list-sec, .references, "
        ".back, .related-articles, .supplementary-material"
    ):
        tag.decompose()

    article = (
        soup.find("article")
        or soup.find("main")
    )

    # Garmin pages may not use <article> or <main>.
    if article is None:
        article = soup.find("body") or soup

    sections = []
    heading = "Introduction"
    buffer = []

    def flush():
        if buffer:
            text = clean_text("\n".join(buffer))

            if len(text) >= 80:
                sections.append({
                    "section": heading,
                    "page": None,
                    "text": text
                })

            buffer.clear()

    for element in article.find_all(
        ["h1", "h2", "h3", "p", "li"]
    ):
        if element.find_parent(["p", "li"]):
            continue

        text = element.get_text(" ", strip=True)

        if not text:
            continue

        if element.name in {"h1", "h2", "h3"}:
            flush()
            heading = text
        else:
            buffer.append(text)

    flush()
    return sections


    def flush():
        if buffer:
            text = clean_text("\n".join(buffer))
            if len(text) >= 80:
                sections.append({
                    "section": heading,
                    "page": None,
                    "text": text
                })
            buffer.clear()

    for element in article.find_all(
        ["h1", "h2", "h3", "p", "li"]
    ):
        if element.find_parent(["p", "li"]):
            continue

        text = element.get_text(" ", strip=True)

        if not text:
            continue

        if element.name in {"h1", "h2", "h3"}:
            flush()
            heading = text
        else:
            buffer.append(text)

    flush()
    return sections


def chunk_text(text):
    """Create overlapping word-based chunks."""
    words = text.split()

    if not words:
        return []

    step = CHUNK_WORDS - OVERLAP_WORDS
    chunks = []

    for start in range(0, len(words), step):
        piece = words[start:start + CHUNK_WORDS]

        if len(piece) < 40 and chunks:
            break

        chunks.append(" ".join(piece))

        if start + CHUNK_WORDS >= len(words):
            break

    return chunks



def load_document(path, doc):
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return load_pdf(
            path,
            stop_at_references=doc.get("stop_at_references", False)
        )

    if suffix in {".html", ".htm"}:
        return load_html(path)

    if suffix in {".txt", ".md"}:
        return [{
            "section": "Document",
            "page": None,
            "text": clean_text(
                path.read_text(encoding="utf-8")
            )
        }]

    raise ValueError(f"Unsupported format: {suffix}")



def build_chunks(manifest):
    all_chunks = []

    for doc in manifest:
        path = KB / doc["file"]

        if not path.exists():
            raise FileNotFoundError(path)

        print(f"\nProcessing: {doc['title']}")

        sections = load_document(path, doc)
        document_count = 0

        for section in sections:
            for text in chunk_text(section["text"]):
                chunk_id = hashlib.sha256(
                    (
                        doc["id"] +
                        section["section"] +
                        str(section["page"]) +
                        text
                    ).encode("utf-8")
                ).hexdigest()[:20]

                all_chunks.append({
                    "id": chunk_id,
                    "document_id": doc["id"],
                    "title": doc["title"],
                    "category": doc["category"],
                    "source": doc["organization"],
                    "source_url": doc["url"],
                    "section": section["section"],
                    "page": section["page"],
                    "text": text
                })

                document_count += 1

        print(f"  Generated {document_count} chunks")

    return all_chunks


def main():
    manifest = json.loads(
        (KB / "manifest.json").read_text(encoding="utf-8")
    )

    chunks = build_chunks(manifest)

    if not chunks:
        raise RuntimeError("No text chunks were extracted")

    print(f"\nTotal chunks: {len(chunks)}")
    print("Loading embedding model...")

    encoder = SentenceTransformer(MODEL)

    texts = [
        f"{chunk['title']}. "
        f"{chunk['section']}. "
        f"{chunk['text']}"
        for chunk in chunks
    ]

    vectors = encoder.encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=True
    )

    vectors = np.asarray(vectors, dtype="float32")

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    OUT.mkdir(parents=True, exist_ok=True)

    faiss.write_index(
        index,
        str(OUT / "fitness.faiss")
    )

    (OUT / "chunks.json").write_text(
        json.dumps(chunks, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    (OUT / "config.json").write_text(
        json.dumps({
            "embedding_model": MODEL,
            "chunk_words": CHUNK_WORDS,
            "overlap_words": OVERLAP_WORDS,
            "documents": len(manifest),
            "chunks": len(chunks)
        }, indent=2),
        encoding="utf-8"
    )

    print("\nIndex built successfully!")
    print(f"Documents: {len(manifest)}")
    print(f"Chunks: {len(chunks)}")
    print(f"FAISS vectors: {index.ntotal}")
    print(f"Output: {OUT}")


if __name__ == "__main__":
    main()

