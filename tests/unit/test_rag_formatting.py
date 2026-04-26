"""Unit tests for RAG client formatting functions."""

from backend.rag_client.formatting import format_retrieved_docs


class TestFormatRetrievedDocs:
    """Test suite for format_retrieved_docs function."""

    def test_empty_results(self):
        """Empty results should return empty string."""
        result = format_retrieved_docs([])
        assert result == ""

    def test_single_doc_basic(self):
        """Single document with basic metadata."""
        docs = [
            {
                "content": "This is test content",
                "metadata": {"source": "test.py", "category": "example"},
                "score": 0.95,
            }
        ]
        result = format_retrieved_docs(docs)
        assert "[Doc 1]" in result
        assert "Source: test.py" in result
        assert "Type: example" in result
        assert "Relevance: 0.950" in result
        assert "This is test content" in result

    def test_multiple_docs(self):
        """Multiple documents should be numbered correctly."""
        docs = [
            {"content": "First doc", "metadata": {"source": "first.py"}, "score": 0.9},
            {
                "content": "Second doc",
                "metadata": {"source": "second.py"},
                "score": 0.8,
            },
            {"content": "Third doc", "metadata": {"source": "third.py"}, "score": 0.7},
        ]
        result = format_retrieved_docs(docs)
        assert "[Doc 1]" in result
        assert "[Doc 2]" in result
        assert "[Doc 3]" in result
        assert "First doc" in result
        assert "Second doc" in result
        assert "Third doc" in result

    def test_missing_metadata(self):
        """Handle documents with missing metadata gracefully."""
        docs = [{"content": "Content without metadata", "score": 0.5}]
        result = format_retrieved_docs(docs)
        assert "Content without metadata" in result
        assert "Relevance: 0.500" in result

    def test_max_length_truncation(self):
        """Content should be truncated when exceeding max_length."""
        long_content = "x" * 3000
        docs = [{"content": long_content, "metadata": {}, "score": 0.9}]
        result = format_retrieved_docs(docs, max_length=500)
        assert len(result) <= 500
        assert "[truncated]" in result or len(result) < len(long_content)

    def test_max_length_multiple_docs(self):
        """Multiple docs should stop adding when max_length reached."""
        docs = [
            {"content": "A" * 800, "metadata": {}, "score": 0.9},
            {"content": "B" * 800, "metadata": {}, "score": 0.8},
            {"content": "C" * 800, "metadata": {}, "score": 0.7},
        ]
        result = format_retrieved_docs(docs, max_length=1000)
        # Should include first doc but may truncate subsequent ones
        assert "AAAA" in result
        assert len(result) <= 1000

    def test_alternative_metadata_keys(self):
        """Handle alternative metadata key names (path, file, type)."""
        docs = [
            {
                "content": "Test",
                "metadata": {"path": "/some/path.py", "type": "code"},
                "score": 0.8,
            }
        ]
        result = format_retrieved_docs(docs)
        assert "Source: /some/path.py" in result
        assert "Type: code" in result

    def test_none_metadata(self):
        """Handle None metadata without errors."""
        docs = [{"content": "Test content", "metadata": None, "score": 0.7}]
        result = format_retrieved_docs(docs)
        assert "Test content" in result
        assert "Relevance: 0.700" in result

    def test_empty_strings_in_metadata(self):
        """Handle empty string values in metadata."""
        docs = [
            {
                "content": "Test",
                "metadata": {"source": "", "category": ""},
                "score": 0.6,
            }
        ]
        result = format_retrieved_docs(docs)
        assert "Test" in result
        assert "Relevance: 0.600" in result

    def test_score_formatting(self):
        """Score should be formatted to 3 decimal places."""
        docs = [{"content": "Test", "metadata": {}, "score": 0.123456}]
        result = format_retrieved_docs(docs)
        assert "Relevance: 0.123" in result

    def test_default_max_length(self):
        """Default max_length should be 2000."""
        # Create content slightly over 2000 chars
        long_content = "x" * 2500
        docs = [{"content": long_content, "metadata": {}, "score": 0.9}]
        result = format_retrieved_docs(docs)
        assert len(result) <= 2100
