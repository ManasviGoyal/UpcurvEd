# backend/agent/nodes/retrieve.py
import re

from ...rag_client.cloud_retriever import get_rag_retriever
from ...rag_client.formatting import format_retrieved_docs
from ..state import AgentState

# Only keep docs with score <= this value, bc distance so lower is better
REL_THRESH = 0.5


def _extract_error_line(error_log: str, job_id: str | None = None) -> int | None:
    """
    Try to extract the failing line number from the error log.

    Prefer a frame of the form:
        /app/storage/jobs/<job_id>/scene.py:<line>

    Otherwise, return None.
    """

    # Prefer the specific job if we know the job_id
    if job_id:
        pattern = rf"jobs/{re.escape(str(job_id))}/scene\.py:(\d+)"
        m = re.search(pattern, error_log)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
        return None


def _slice_code_line(
    previous_code: str,
    line_no: int | None,
) -> str:
    """
    Return the code line given the line number.
    """
    lines = previous_code.splitlines()
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _build_rag_query(
    error_log: str,
    previous_code: str,
    job_id: str | None = None,
    error_context: str | None = None,
    max_code_lines: int = 12,
) -> str:
    """
    Build a RAG query that is primarily the offending Manim code line.

    Since our RAG corpus is Manim documentation, the API usage (e.g. BarChart,
    Axes, Code, etc.) is more important than the English error message.
    """
    rag_query = ""
    error_log = (error_log or "").strip()
    previous_code = (previous_code or "").strip()
    error_context = (error_context or "").strip()

    line_no = _extract_error_line(error_log, job_id)
    line = None
    if line_no is not None:
        line = _slice_code_line(previous_code, line_no)
        if line:
            rag_query += line.strip() + "\n"
    first_line = error_context.splitlines()[0].strip()
    rag_query += f"Manim render error: {first_line}\n\n"
    return rag_query


def retrieve_node(
    state: AgentState,
    top_k_max: int = 2,
    max_doc_length: int = 3000,
) -> AgentState:
    """
    Retrieve relevant documentation from the RAG knowledge base.

    This node uses the cloud RAG service by default (configurable via RAG_USE_CLOUD env var).
    Falls back if RAG is unavailable.
    """
    new_state: AgentState = dict(state)
    # bump tries once per loop
    new_state["tries"] = int(state.get("tries", 0)) + 1

    error_context = (state.get("error_context") or "").strip()
    error_log = (state.get("error_log") or "").strip()
    previous_code = (state.get("previous_code") or "").strip()
    job_id = state.get("job_id")

    # If we have literally nothing diagnostic, skip RAG
    if not error_log and not previous_code and not error_context and not job_id:
        new_state["retrieved_docs"] = ""
        return new_state

    rag_query = _build_rag_query(
        error_log=error_log,
        previous_code=previous_code,
        job_id=job_id,
        error_context=error_context,
    )
    if not rag_query.strip():
        new_state["retrieved_docs"] = ""
        return new_state

    try:
        # Get the appropriate retriever (cloud or local based on config)
        retriever = get_rag_retriever()

        # Query the knowledge base
        results = retriever.query_multiple(
            queries=[rag_query],
            top_k_per_query=min(max(1, top_k_max), 2),
            deduplicate=True,
        )

        # Apply relevance threshold: keep only sufficiently relevant docs
        filtered_results = [r for r in results if r.get("score", 999.0) <= REL_THRESH]

        # If nothing passes the floor, don't include any RAG context
        if not filtered_results:
            new_state["retrieved_docs"] = ""
            return new_state

        # Format results for inclusion in prompts
        formatted_docs = format_retrieved_docs(filtered_results, max_length=max_doc_length)
        new_state["retrieved_docs"] = formatted_docs
        return new_state
    except Exception as e:
        print(f"Warning: RAG retrieval failed: {e}")
        new_state["retrieved_docs"] = ""
        return new_state
