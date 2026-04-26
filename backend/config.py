# backend/config.py
import os

# Max total characters for the single ERROR CONTEXT block (title + body)
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "500"))

# Whether to delete failed job directories after logging a compact failure entry
CLEANUP_FAILED_JOBS = os.getenv("CLEANUP_FAILED_JOBS", "false").lower() == "true"

# Where to append compact JSONL entries for failed renders
FAILURE_LOG_PATH = os.getenv("FAILURE_LOG_PATH", "storage/failure_log.jsonl")

# RAG Configuration

# Use cloud-based RAG service (True) or local ChromaDB (False)
RAG_USE_CLOUD = os.getenv("RAG_USE_CLOUD", "true").lower() == "true"

# URL of the RAG microservice (when RAG_USE_CLOUD=true)
RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://localhost:8001")

# Local ChromaDB path (when RAG_USE_CLOUD=false)
RAG_DB_PATH = os.getenv("RAG_DB_PATH", "rag-data/processed/chroma_db")

# ChromaDB collection name
RAG_COLLECTION_NAME = os.getenv("RAG_COLLECTION_NAME", "manim_knowledge")
