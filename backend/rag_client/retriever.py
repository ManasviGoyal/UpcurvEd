# backend/rag_client/retriever.py
from pathlib import Path
from typing import Any

import numpy as np

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
except ImportError as e:
    raise ImportError(
        "Missing required packages for RAG. Install with: "
        "pip install chromadb sentence-transformers"
    ) from e

# Use the same embedding model as indexing
EMBED_MODEL = "all-MiniLM-L6-v2"
COLLECTION_NAME = "manim_knowledge"


class RAGRetriever:
    """
    Client for retrieving relevant documentation from ChromaDB.

    Usage:
        retriever = RAGRetriever(db_path="rag-data/processed/chroma_db")
        results = retriever.query("How to use Transform?", top_k=5)
    """

    def __init__(self, db_path: str | Path, collection_name: str = COLLECTION_NAME):
        """
        Initialize the RAG retriever.

        Args:
            db_path: Path to the ChromaDB directory
            collection_name: Name of the collection to query
        """
        self.db_path = Path(db_path)
        self.collection_name = collection_name
        self._embedding_model: SentenceTransformer | None = None
        self._collection = None

    def _get_embedding_model(self) -> SentenceTransformer:
        """Lazy-load the embedding model."""
        if self._embedding_model is None:
            self._embedding_model = SentenceTransformer(EMBED_MODEL)
        return self._embedding_model

    def _get_collection(self):
        """Lazy-load the ChromaDB collection."""
        if self._collection is None:
            # Use settings to avoid tenant issues with newer ChromaDB versions
            settings = chromadb.Settings(allow_reset=False, anonymized_telemetry=False)
            client = chromadb.PersistentClient(path=str(self.db_path), settings=settings)
            try:
                self._collection = client.get_collection(self.collection_name)
            except Exception as e:
                raise RuntimeError(
                    f"Collection '{self.collection_name}' not found at {self.db_path}."
                    f"Run the RAG setup first to build the DB. Error: {e}"
                ) from e
        return self._collection

    def _embed_text(self, text: str) -> list[float]:
        """Convert text to embedding vector."""
        model = self._get_embedding_model()
        vec = model.encode([text], normalize_embeddings=True)
        return vec[0].astype(np.float32).tolist()

    def query(
        self, query_text: str, top_k: int = 1, include_metadata: bool = True
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

        collection = self._get_collection()
        query_embedding = self._embed_text(query_text)

        # Query ChromaDB
        results = collection.query(query_embeddings=[query_embedding], n_results=top_k)

        # Parse results
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0] if include_metadata else [{}] * len(ids)

        # Format as list of dicts
        formatted_results = []
        for doc_id, content, score, metadata in zip(
            ids, documents, distances, metadatas, strict=False
        ):
            result = {
                "id": doc_id,
                "content": content,
                "score": score,
            }
            if include_metadata and metadata:
                result["metadata"] = metadata
            formatted_results.append(result)

        return formatted_results

    def query_multiple(
        self, queries: list[str], top_k_per_query: int = 1, deduplicate: bool = True
    ) -> list[dict[str, Any]]:
        """
        Query multiple search terms and combine results.
        Useful for retrieving docs for multiple contexts from the plan.

        Args:
            queries: List of search queries
            top_k_per_query: Number of results per query
            deduplicate: Remove duplicate documents (by ID)

        Returns:
            Combined list of results, sorted by score
        """
        all_results = []
        seen_ids = set()

        for query_text in queries:
            if not query_text or not query_text.strip():
                continue

            results = self.query(query_text, top_k=top_k_per_query)

            for result in results:
                doc_id = result["id"]
                if deduplicate and doc_id in seen_ids:
                    continue
                seen_ids.add(doc_id)
                all_results.append(result)

        # Sort by score (lower is better in ChromaDB distance metric)
        all_results.sort(key=lambda x: x["score"])

        return all_results


def format_retrieved_docs(results: list[dict[str, Any]], max_length: int = 2000) -> str:
    """
    Format retrieved documents for inclusion in LLM prompts.

    Args:
        results: List of retrieval results from RAGRetriever.query()
        max_length: Maximum total character length

    Returns:
        Formatted string with numbered documentation snippets
    """
    if not results:
        return ""

    formatted_parts = []
    current_length = 0

    for i, result in enumerate(results, 1):
        content = result["content"]
        metadata = result.get("metadata", {})
        score = result.get("score", 0.0)

        # Extract source info from metadata
        source = metadata.get("source") or metadata.get("path") or metadata.get("file", "")
        category = metadata.get("category") or metadata.get("type", "")

        # Build header
        header_parts = []
        if source:
            header_parts.append(f"Source: {source}")
        if category:
            header_parts.append(f"Type: {category}")
        header_parts.append(f"Relevance: {score:.3f}")
        header = " | ".join(header_parts)

        # Format this doc
        doc_str = f"[Doc {i}] {header}\n{content}\n"

        # Check length limit
        if current_length + len(doc_str) > max_length:
            remaining = max_length - current_length
            # add if space > 100 chars
            if remaining > 100:
                truncated = content[: remaining - 50] + "... [truncated]"
                doc_str = f"[Doc {i}] {header}\n{truncated}\n"
                formatted_parts.append(doc_str)
            break

        formatted_parts.append(doc_str)
        current_length += len(doc_str)

    return "\n".join(formatted_parts).strip()
