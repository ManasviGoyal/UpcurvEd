import argparse
from pathlib import Path
from typing import Any, Dict, List

import chromadb
import numpy as np

# Use the same embedding model as indexing
EMBED_MODEL = "all-MiniLM-L6-v2"


def embed_query(text: str) -> List[float]:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("Error: sentence-transformers not installed.")
        return None
    model = SentenceTransformer(EMBED_MODEL)
    vec = model.encode([text], normalize_embeddings=True)
    return vec[0].astype(np.float32).tolist()


def get_collection(db_path: Path):
    client = chromadb.PersistentClient(path=str(db_path))
    try:
        return client.get_collection("manim_knowledge")
    except Exception:
        raise SystemExit(
            f"Collection 'manim_knowledge' not found at {db_path}.\n"
            "Run the download (or upload) step first to build the DB."
        )


def main():
    p = argparse.ArgumentParser("Query local ChromaDB (built by create_vector_db.py)")
    p.add_argument("--base-dir", default="rag-data", help="Base directory for RAG data")
    p.add_argument("--q", required=True, help="Query text")
    p.add_argument("--top-k", type=int, default=5, help="Number of results")
    args = p.parse_args()

    db_path = Path(args.base_dir) / "processed" / "chroma_db"
    coll = get_collection(db_path)

    q_emb = embed_query(args.q)
    res = coll.query(query_embeddings=[q_emb], n_results=args.top_k)

    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas: List[Dict[str, Any]] = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    print("\n=== Query ===")
    print(args.q)
    print(f"\n=== Top {len(docs)} results ===")
    for i, (cid, doc, meta, dist) in enumerate(zip(ids, docs, metas, dists), 1):
        src = meta.get("source") or meta.get("path") or meta.get("file", "")
        cat = meta.get("category", "")
        tpe = meta.get("type", "")
        where = " · ".join([x for x in [src, cat or tpe] if x])
        preview = (doc[:300] + "…") if len(doc) > 300 else doc
        print(f"\n[{i}] id={cid}  score={dist:.4f}")
        if where:
            print(f"    {where}")
        print(f"    {preview}")


if __name__ == "__main__":
    main()
