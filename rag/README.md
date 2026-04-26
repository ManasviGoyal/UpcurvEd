# RAG Pipeline

This folder manages the **Retrieval-Augmented Generation (RAG)** data layer for the project.  
It preprocesses Manim documentation, creates embeddings, and hosts a vector search API.

---

## Structure

```
rag/
├── secrets/                  # GCP key (service-account.json)
├── create_vector_db.py       # Embedding + upload/download logic
├── preprocess_rag_smart.py   # Chunking & preprocessing of source docs
├── docker-entrypoint.sh      # Entrypoint for ETL pipeline
├── Dockerfile                # llm-rag-job build definition
├── .env, .env.example        # Environment variables (GCS_BUCKET, BASE_DIR, etc.)
├── pyproject.toml, uv.lock   # Dependencies (managed via uv)
├── query_db.py               # Query embeddings manually
└── README.md
```

---

## Components

| Service | Purpose |
|----------|----------|
| **chroma** | Persistent ChromaDB instance for embeddings |
| **llm-rag-job** | One-off ETL job for building or downloading embeddings |
| **rag-service** | API layer for semantic retrieval (FastAPI, port 8001) |

---

## Setup

### 1. Service Account

Place a valid GCP service account in:
```
rag/secrets/service-account.json
```

This is mounted read-only into containers at `/secrets/service-account.json`.

### 2. Configure `.env`

```bash
GCS_BUCKET=your-rag-bucket
GCS_PREFIX=rag-cache/v1
BASE_DIR=/var/lib/app/rag-data
GOOGLE_APPLICATION_CREDENTIALS=/secrets/service-account.json
```

### 3. Run the full stack

```bash
docker compose --profile rag up -d
```

This launches:
- `chroma` on port 8000  
- `llm-rag-job` (runs then exits)  
- `rag-service` (FastAPI app on 8001)

---

## Query Examples

```bash
# Health
curl http://localhost:8001/health

# Collection info
curl http://localhost:8001/collection/info

# Semantic query
curl -X POST http://localhost:8001/query   -H 'Content-Type: application/json'   -d '{"query": "Transform", "top_k": 3}'
```

---

## Volumes

- `ragdata:` shared embedding volume between chroma, llm-rag-job, and rag-service. Only used internally by the containers for storing chunks and embeddings and doesn’t need to persist beyond rebuilds (but does because it is a named volume).
- `chroma-data:` persistent vector database

---

## Notes

- `backend/rag_service` contains the API code used by `rag-service`.  
- The `rag/` folder only handles **data and orchestration**, not app logic.

---

## License

This repository is currently unlicensed and private.

All rights reserved © 2025 Isabela Yepes, Manasvi Goyal, Nico Fidalgo.

Access is granted only to authorized course staff for evaluation purposes.
