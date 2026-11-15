# Fitness RAG CLI — Milestone 2 starter

This prototype embeds five project-authored demonstration notes (not externally validated source documents) with SentenceTransformers, retrieves with FAISS, and answers via a local OpenAI-compatible llama.cpp server. No Garmin data, trainer review, cloud GPU, or real-time streaming yet.

## Setup

Use a compatible Python environment (Python 3.12 recommended):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python ingest.py
```

Start your existing llama.cpp server separately, listening on port 8001, then:

```bash
python chatbot.py
```

Optional configuration: `LLM_API_BASE=http://127.0.0.1:8001/v1`, `LLM_MODEL=<server model ID>`.

Ask: "What is progressive overload?" or "How should I approach running endurance?". Type `quit` to exit.

## Limitations

- The knowledge notes are illustrative, not externally sourced/verified; replace with reviewed, attributed materials before claiming evidence-grounded fitness guidance.
- Retrieved-source similarity is not proof of correctness; citations are prompt-guided, not independently validated.
- No authenticated trainer approval or cross-user isolation yet.
- Local inference on Apple Silicon does not fulfill a cloud GPU requirement.
