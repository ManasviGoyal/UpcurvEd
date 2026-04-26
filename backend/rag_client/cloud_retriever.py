# backend/rag_client/cloud_retriever.py
import os
from typing import Any
from urllib.parse import urljoin

import httpx


class CloudRAGRetriever:
    """
    HTTP client for querying the RAG microservice.

    Usage:
        retriever = CloudRAGRetriever(service_url="http://localhost:8001")
        results = retriever.query("How to use Transform?", top_k=5)
    """

    def __init__(self, service_url: str | None = None, timeout: float = 30.0):
        """
        Initialize the cloud RAG retriever.

        Args:
            service_url: URL of the RAG service (e.g., "http://localhost:8001")
                         Falls back to RAG_SERVICE_URL env var
            timeout: Request timeout in seconds
        """
        self.service_url = service_url or os.getenv("RAG_SERVICE_URL", "http://localhost:8001")
        self.timeout = timeout

        # Remove trailing slash
        if self.service_url.endswith("/"):
            self.service_url = self.service_url[:-1]

    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        """Make HTTP request to the RAG service."""
        url = urljoin(self.service_url + "/", endpoint.lstrip("/"))

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            raise RuntimeError(f"RAG service request timed out after {self.timeout}s") from None
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"RAG service error: {e.response.status_code} - {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Failed to connect to RAG service at {self.service_url}: {str(e)}"
            ) from e

    def health_check(self) -> bool:
        """Check if the RAG service is healthy and accessible."""
        try:
            response = self._make_request("GET", "/health")
            return response.get("status") == "healthy"
        except Exception:
            return False

    def query(
        self, query_text: str, top_k: int = 5, include_metadata: bool = True
    ) -> list[dict[str, Any]]:
        """
        Query the knowledge base for relevant documents.

        Args:
            query_text: The search query
            top_k: Number of results to return
            include_metadata: Whether to include metadata in results

        Returns:
            List of result dictionaries with keys:
                - id: Document ID
                - content: Document text
                - score: Similarity score (lower is better - it's a distance)
                - metadata: Optional metadata dict (source, category, etc.)
        """
        if not query_text or not query_text.strip():
            return []

        payload = {"query": query_text, "top_k": top_k, "include_metadata": include_metadata}

        response = self._make_request("POST", "/query", json=payload)
        return response.get("results", [])

    def query_multiple(
        self, queries: list[str], top_k_per_query: int = 3, deduplicate: bool = True
    ) -> list[dict[str, Any]]:
        """
        Query multiple search terms and combine results.

        Args:
            queries: List of search queries
            top_k_per_query: Number of results per query
            deduplicate: Remove duplicate documents by id

        Returns:
            Combined list of results, sorted by similarity score
        """
        if not queries or all(not q.strip() for q in queries):
            return []

        payload = {
            "queries": [q for q in queries if q.strip()],
            "top_k_per_query": top_k_per_query,
            "deduplicate": deduplicate,
        }

        response = self._make_request("POST", "/query-multiple", json=payload)
        return response.get("results", [])

    def query_formatted(self, query_text: str, top_k: int = 5, max_length: int = 2000) -> str:
        """
        Query the knowledge base and return formatted text for LLM prompts.

        Args:
            query_text: The search query
            top_k: Number of results to retrieve
            max_length: Maximum formatted text length

        Returns:
            Formatted string with numbered documentation snippets
        """
        if not query_text or not query_text.strip():
            return ""

        payload = {"query": query_text, "top_k": top_k, "max_length": max_length}

        response = self._make_request("POST", "/query-formatted", json=payload)
        return response.get("formatted_docs", "")

    def get_collection_info(self) -> dict[str, Any]:
        """Get information about the ChromaDB collection."""
        return self._make_request("GET", "/collection/info")


def get_rag_retriever(use_cloud: bool | None = None) -> Any:
    """
    Factory function to get the appropriate RAG retriever (cloud or local).

    Args:
        use_cloud: If True, use CloudRAGRetriever. If False, use local RAGRetriever.
                   If None, check RAG_USE_CLOUD environment variable (defaults to True).

    Returns:
        Either CloudRAGRetriever or RAGRetriever instance
    """
    if use_cloud is None:
        use_cloud = os.getenv("RAG_USE_CLOUD", "true").lower() == "true"

    if use_cloud:
        return CloudRAGRetriever()
    else:
        # Import locally to avoid requiring ChromaDB when using cloud mode
        from .retriever import RAGRetriever

        db_path = os.getenv("RAG_DB_PATH", "rag-data/processed/chroma_db")
        return RAGRetriever(db_path=db_path)
