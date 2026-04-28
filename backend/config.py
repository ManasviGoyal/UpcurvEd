# backend/config.py
import os

# Max total characters for the single ERROR CONTEXT block (title + body)
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "500"))

# Whether to delete failed job directories after logging a compact failure entry
CLEANUP_FAILED_JOBS = os.getenv("CLEANUP_FAILED_JOBS", "false").lower() == "true"

# Where to append compact JSONL entries for failed renders
FAILURE_LOG_PATH = os.getenv("FAILURE_LOG_PATH", "storage/failure_log.jsonl")

