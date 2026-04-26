FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# System deps (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/*

# Python deps needed by the service
RUN pip install --no-cache-dir \
    fastapi>=0.111.0 \
    uvicorn[standard]>=0.30.0 \
    pydantic>=2.7.0 \
    httpx>=0.27.0 \
    chromadb>=0.5.0 \
    sentence-transformers>=3.2.0 \
    numpy>=1.26.0

# Copy only what this service imports from your repo
COPY backend/__init__.py                        /app/backend/__init__.py
COPY backend/rag_service                        /app/backend/rag_service
COPY backend/rag_client/__init__.py             /app/backend/rag_client/__init__.py
COPY backend/rag_client/formatting.py           /app/backend/rag_client/formatting.py

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8001/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.rag_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
