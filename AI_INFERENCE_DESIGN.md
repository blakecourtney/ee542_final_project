# Fitness Training Partner — AI Inference Architecture Proposal

**EE542 Final Project | Milestone 1 | November 7, 2026**  
**Status:** Design proposal; not an implemented AI system.

## 1. Problem and objective
Wearable devices collect activity data, but users may struggle to translate it into practical, goal-specific training decisions. The proposed system combines measured workout trends with evidence-grounded coaching explanations. Initial focus: running/endurance, because the currently available Garmin data supports distance, moving duration, pace, and heart rate. Strength progression requires verified sets/reps/weight data or manual logging.

## 2. Current implemented baseline
- Garmin Personal API ingestion and FIT decoding (teammate work).
- SQLite activity summaries (teammate work).
- Python `analytics.py` computes running distance, pace, heart-rate summaries, and a comparison of the latest two sessions against the preceding two.
- Python `recommend.py` emits transparent, rule-based suggestions; `demo.py` exercises the pipeline.
- Observed local demonstration: 512 imported activities, 107 running activities, 625.29 km total running distance, +5.0% recent pace time (slower pace). The comparison is unadjusted for distance, terrain, workout purpose, and effort; it is not a validated performance prediction.

**Not yet implemented:** RAG, LLM inference, GPU acceleration, cloud deployment, real-time streaming, frontend, or trained predictive model.

## 3. Candidate inference strategies
| Approach | Role | Advantages | Risks / effort | Decision |
|---|---|---|---|---|
| Prompt-only LLM | Explain activity metrics | Fast prototype | Ungrounded advice and numerical mistakes | Baseline only |
| RAG + instruction LLM | Retrieve expert knowledge and generate grounded feedback | Updateable knowledge, source traceability, potential expert-clone path | Document curation, retrieval evaluation | **Recommended next step** |
| Time-series ML (LSTM/TCN/Transformer) | Forecast individual training metrics | Quantitative model | Sparse labels, leakage, data volume | Research extension |
| Hybrid analytics + RAG + LLM + optional ML | Structured calculations + evidence + coaching | Separation of concerns | More integration | Target architecture |

## 4. Proposed system architecture
```text
Garmin API / FIT / future wearable streams
                  |
            Ingestion layer
                  |
       SQL activity database
                  |
     Deterministic analytics  <--- user goal and preferences
                  |                     |
          Metrics JSON -----------------+
                  |                     |
                  v                     v
       Prompt/context builder     RAG retriever
                  |                     ^
                  |               FAISS vector index
                  |                     ^
                  |             Embedded expert documents
                  +----------+----------+
                             |
                GPU-hosted instruction LLM
                             |
             Schema validation / safety rules
                             |
              Coaching API / future frontend
```
**Important:** RAG retrieves expert training documents, not raw numerical workout history. SQL and Python calculate metrics. The LLM explains them and cites retrieved knowledge. Real-time sensor alerts should use a separate low-latency deterministic path.

## 5. Proposed RAG pipeline
1. Curate a small, licensed/appropriately usable expert knowledge base: general physical-activity guidelines, training principles, workout recovery, and goal-setting. Record title, publisher, URL, license/usage basis, date, and scope.
2. Extract and clean documents; chunk by semantic sections with overlap where needed.
3. Compute embeddings with SentenceTransformers; store vectors in FAISS and source metadata in SQL/JSON.
4. At query time, select relevant documents using the user's goal and metrics; retrieve top-k passages and optionally rerank.
5. Compose a structured prompt containing *computed* activity metrics, user goal, retrieved passages, uncertainty notes, and output constraints.
6. Run an instruction-tuned LLM on a cloud GPU; return JSON with `summary`, `observations`, `suggestions`, `evidence`, and `caveats`.
7. Validate JSON and reject unsupported claims, unsafe intensity prescriptions, or recommendations unsupported by available data.

**Example prompt context (illustrative):** `goal=endurance; sessions=107; total_distance_km=625.29; recent_pace_change_pct=+5.0; comparison=last 2 vs prior 2; confounders=terrain/effort unknown`. A positive pace-time change means slower pace, not improvement.

## 6. Model / infrastructure options
- **Initial LLM:** Evaluate an instruction-tuned 3B–8B model that can run on a single cloud GPU; use a model whose license permits the intended use. Quantized inference can reduce GPU memory needs. Benchmark actual latency, memory, output correctness, and cost rather than assuming a specific instance will suffice.
- **Embeddings:** SentenceTransformers model; initially CPU is acceptable for indexing small corpora, while GPU inference of the LLM satisfies the planned GPU requirement once deployed.
- **Serving:** FastAPI coaching endpoint -> GPU inference server (e.g., vLLM or llama.cpp, subject to model/hardware compatibility) -> structured response.
- **Cloud:** AWS/GCP GPU VM for inference; cloud-managed SQL/object storage optional. Protect the API with authentication and avoid exposing personal activity data in logs.
- **Prior work reuse:** The HeartWise lab's extraction -> chunking -> embeddings -> FAISS -> LLM pattern is reusable conceptually. Do not assume its exact scripts or models can be copied without adaptation.

## 7. Potential time-series ML extension
Try predicting next-week running volume or a normalized pace metric using historical windows. Compare simple baselines (last-week value, moving average) against a small LSTM/TCN. Use chronological train/validation/test splits and report MAE; never random-split adjacent time windows. One person's 107 runs is not sufficient to claim generalization across users. Avoid injury-risk diagnosis or exact safe-load prescriptions without validated datasets and expert oversight.

## 8. Real-time coaching extension
Wearable/fitness-equipment telemetry -> authenticated stream -> timestamped feature window -> rule-based alert engine -> phone/wearable feedback. Use LLM only for occasional explanations or post-session summaries. Measure end-to-end latency, packet loss, disconnect handling, battery impact, and alert usefulness. Verify Garmin/device APIs actually permit the desired live streaming; historical Personal API access does not imply live access.

## 9. Evaluation plan
- **Analytics correctness:** unit tests for pace calculations, units, missing fields, and comparison sign.
- **Retrieval:** human-labeled question/passage set; recall@k and source relevance.
- **LLM:** groundedness, correct numerical interpretation, actionable specificity, abstention on missing data, unsafe advice rate.
- **GPU/cloud:** p50/p95 inference latency, throughput, peak GPU memory, cloud cost per 1000 coaching requests.
- **Product:** user interviews, willingness to pay, retention intent, preference for live feedback vs expert persona. Interview results are hypotheses until collected.

## 10. Milestones
| Phase | Deliverable | Acceptance check |
|---|---|---|
| M1 (complete) | Garmin -> SQLite -> analytics -> rule-based recommendations | Run `python3 demo.py --db data/garmin.db --goal endurance` |
| M2 | Curated expert documents, embedding index, RAG retrieval | Relevant passages returned with source metadata |
| M3 | Cloud GPU-hosted LLM coaching endpoint | Demonstrated GPU inference + structured, cited responses |
| M4 | Comparative evaluation and frontend integration | Benchmark against rule-based and prompt-only baselines |
| Stretch | Real-time wearable feedback or predictive time-series model | Latency/accuracy results on real test data |

## 11. Risks and decisions
- **Expert clone definition:** Confirm Path II interpretation with instructor. A generic coach persona may not meet a strict 'digital clone of an expert' requirement; obtain permission for any identifiable expert likeness/voice and associated materials.
- **Privacy:** Garmin data can be sensitive. Keep API credentials in `.env`, exclude databases from Git, minimize retention, and get teammate's permission before cloud upload.
- **Commercial viability:** Interview target users and verify profitability of actual comparator companies using company filings or credible sources. A company's revenue does not establish profitability.
- **Safety:** The system provides general training guidance, not diagnosis or personalized medical clearance. Escalate concerning symptoms to appropriate professional help.
- **Scope:** Start with endurance running; add strength training only after validating available metrics.

## 12. Suggested vlog outline (2–3 minutes)
1. Show current working output: 512 activities, 107 runs, 625.29 km, and the preliminary +5% pace-time change.
2. Explain why raw sensor data alone cannot produce reliable coaching: calculations, expert context, and safeguards are needed.
3. Walk through the architecture: SQLite analytics -> FAISS knowledge retrieval -> GPU-hosted LLM -> validated recommendations.
4. Contrast prompt-only LLM, RAG, and time-series ML; explain why RAG + structured analytics is the next milestone.
5. Explicitly distinguish implemented work from proposed future work; identify GPU/cloud deployment and expert-clone interpretation as next steps.
