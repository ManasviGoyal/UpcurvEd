# backend/rag_service/main.py
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Import formatting helper
from backend.rag_client.formatting import format_retrieved_docs

app = FastAPI(
    title="RAG Service",
    description="Vector database query service for Manim documentation retrieval",
    version="1.0.0",
)

# middleware for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ChromaDB HTTP connection config
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION_NAME = os.getenv("RAG_COLLECTION_NAME", "manim_knowledge")

# Global ChromaDB client
_client: Any | None = None
_collection: Any | None = None


def get_chroma_client():
    """Lazy-load and return the ChromaDB HTTP client."""
    global _client
    if _client is None:
        import chromadb

        _client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return _client


def get_collection():
    """Lazy-load and return the ChromaDB collection."""
    global _collection
    if _collection is None:
        client = get_chroma_client()
        try:
            _collection = client.get_collection(name=COLLECTION_NAME)
        except Exception as e:
            raise RuntimeError(
                f"Collection '{COLLECTION_NAME}' not found. "
                f"Ensure ChromaDB is initialized. Error: {e}"
            ) from e
    return _collection


class QueryRequest(BaseModel):
    """Request model for single query."""

    query: str = Field(..., description="The search query text")
    top_k: int = Field(5, ge=1, le=20, description="Number of results to return (1-20)")
    include_metadata: bool = Field(True, description="Include metadata in results")


class MultiQueryRequest(BaseModel):
    """Request model for multiple queries."""

    queries: list[str] = Field(..., description="List of search queries")
    top_k_per_query: int = Field(3, ge=1, le=10, description="Results per query (1-10)")
    deduplicate: bool = Field(True, description="Remove duplicate documents by ID")


class FormatRequest(BaseModel):
    """Request model for formatting retrieved documents."""

    query: str = Field(..., description="The search query text")
    top_k: int = Field(5, ge=1, le=20, description="Number of results to retrieve")
    max_length: int = Field(2000, ge=100, le=10000, description="Maximum formatted text length")


class QueryResult(BaseModel):
    """Single query result."""

    id: str
    content: str
    score: float
    metadata: dict[str, Any] | None = None


class QueryResponse(BaseModel):
    """Response model for query endpoints."""

    results: list[QueryResult]
    query: str | None = None
    count: int


@app.get("/health")
def health_check():
    """Health check endpoint."""
    try:
        # Verify ChromaDB connection
        client = get_chroma_client()
        client.heartbeat()  # Check if ChromaDB is responding
        return {"status": "healthy", "chroma_host": CHROMA_HOST, "chroma_port": CHROMA_PORT}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}") from e


@app.post("/query", response_model=QueryResponse)
def query_rag(request: QueryRequest):
    """
    Query the RAG knowledge base for relevant documents.

    Returns semantically similar documents based on the query text.
    """
    try:
        from sentence_transformers import SentenceTransformer

        # Get embedding model
        model = SentenceTransformer("all-MiniLM-L6-v2")

        # Generate query embedding
        query_embedding = model.encode([request.query], normalize_embeddings=True)[0]

        # Query ChromaDB
        collection = get_collection()
        results = collection.query(
            query_embeddings=[query_embedding.tolist()], n_results=request.top_k
        )

        # Format results
        formatted_results = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = (
            results.get("metadatas", [[]])[0] if request.include_metadata else [{}] * len(ids)
        )

        for doc_id, content, score, metadata in zip(
            ids, documents, distances, metadatas, strict=False
        ):
            result = {
                "id": doc_id,
                "content": content,
                "score": score,
            }
            if request.include_metadata and metadata:
                result["metadata"] = metadata
            formatted_results.append(QueryResult(**result))

        return QueryResponse(
            results=formatted_results, query=request.query, count=len(formatted_results)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}") from e


@app.post("/query-multiple", response_model=QueryResponse)
def query_multiple(request: MultiQueryRequest):
    """
    Query multiple search terms and combine results.

    Useful for retrieving documents for multiple contexts from a plan.
    Results are deduplicated and sorted by relevance score.
    """
    try:
        from sentence_transformers import SentenceTransformer

        # Get embedding model
        model = SentenceTransformer("all-MiniLM-L6-v2")
        collection = get_collection()

        all_results = []
        seen_ids = set()

        for query_text in request.queries:
            if not query_text or not query_text.strip():
                continue

            # Generate query embedding
            query_embedding = model.encode([query_text], normalize_embeddings=True)[0]

            # Query ChromaDB
            results = collection.query(
                query_embeddings=[query_embedding.tolist()], n_results=request.top_k_per_query
            )

            # Process results
            ids = results.get("ids", [[]])[0]
            documents = results.get("documents", [[]])[0]
            distances = results.get("distances", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]

            for doc_id, content, score, metadata in zip(
                ids, documents, distances, metadatas, strict=False
            ):
                if request.deduplicate and doc_id in seen_ids:
                    continue
                seen_ids.add(doc_id)
                all_results.append(
                    QueryResult(
                        id=doc_id,
                        content=content,
                        score=score,
                        metadata=metadata if metadata else None,
                    )
                )

        # Sort by score (lower is better)
        all_results.sort(key=lambda x: x.score)

        return QueryResponse(results=all_results, count=len(all_results))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Multiple query failed: {str(e)}") from e


@app.post("/query-formatted")
def query_formatted(request: FormatRequest):
    """
    Query the knowledge base and return formatted text for LLM prompts.

    This endpoint combines retrieval and formatting in one call,
    returning ready-to-use documentation snippets for inclusion in prompts.
    """
    try:
        from sentence_transformers import SentenceTransformer

        # Get embedding model
        model = SentenceTransformer("all-MiniLM-L6-v2")

        # Generate query embedding
        query_embedding = model.encode([request.query], normalize_embeddings=True)[0]

        # Query ChromaDB
        collection = get_collection()
        results = collection.query(
            query_embeddings=[query_embedding.tolist()], n_results=request.top_k
        )

        # Format results
        formatted_results = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for doc_id, content, score, metadata in zip(
            ids, documents, distances, metadatas, strict=False
        ):
            formatted_results.append(
                {
                    "id": doc_id,
                    "content": content,
                    "score": score,
                    "metadata": metadata if metadata else {},
                }
            )

        formatted_text = format_retrieved_docs(formatted_results, max_length=request.max_length)

        return {
            "formatted_docs": formatted_text,
            "query": request.query,
            "num_docs": len(formatted_results),
            "char_count": len(formatted_text),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Formatted query failed: {str(e)}") from e


@app.get("/collection/info")
def collection_info():
    """Get information about the ChromaDB collection."""
    try:
        collection = get_collection()
        count = collection.count()

        return {
            "name": COLLECTION_NAME,
            "document_count": count,
            "embedding_model": "all-MiniLM-L6-v2",
            "chroma_host": CHROMA_HOST,
            "chroma_port": CHROMA_PORT,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get collection info: {str(e)}"
        ) from e


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
