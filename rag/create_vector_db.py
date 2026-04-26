"""
Create vector database from preprocessed chunks

This script takes the preprocessed chunks and creates a vector database
for RAG.

Usage:
    python scripts/create_vector_db.py
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import chromadb
import numpy as np


def load_chunks(chunks_file: Path) -> List[Dict[str, Any]]:
    """Load preprocessed chunks from JSON file"""
    with open(chunks_file) as f:
        chunks = json.load(f)
    print(f"Loaded {len(chunks)} chunks from {chunks_file}")
    return chunks


def generate_embeddings(chunks: List[Dict[str, Any]], model_name: str = "all-MiniLM-L6-v2"):
    """Generate embeddings using local SentenceTransformer model"""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("Error: sentence-transformers not installed.")
        return None

    print(f"\nLoading local embedding model: {model_name}")
    model = SentenceTransformer(model_name)

    print(f"\nGenerating embeddings for {len(chunks)} chunks...")
    texts = [chunk["content"] for chunk in chunks]
    embeddings = model.encode(
        texts, show_progress_bar=True, batch_size=32, normalize_embeddings=True
    )
    print(f"Generated {len(embeddings)} embeddings")
    return embeddings.tolist()


def save_embeddings_npz(embeddings: List[List[float]], ids: List[str], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_path,
        embeddings=np.asarray(embeddings, dtype=np.float32),
        ids=np.array(ids, dtype=object),
    )
    print(f"Saved embeddings NPZ to {out_path}")
    return out_path


def load_embeddings_npz(npz_path: Path):
    with np.load(npz_path, allow_pickle=True) as data:
        emb = data["embeddings"].astype(np.float32)
        ids = data["ids"].tolist()
    print(f"Loaded embeddings NPZ from {npz_path} ({emb.shape[0]} vectors)")
    return emb, ids


def get_client(local_path: str):
    host = os.getenv("CHROMA_HOST")
    port = os.getenv("CHROMA_PORT")
    if host and port:  # Server mode
        return chromadb.HttpClient(host=host, port=int(port))
    # Local persistent mode (default)
    return chromadb.PersistentClient(path=local_path)


def gcs_save_version_manifest(bucket: str, prefix: str, version_data: Dict[str, Any]) -> str:
    """Save version-specific manifest at {prefix}/manifest.json (overwrites on each upload)"""
    from google.cloud import storage

    manifest_path = f"{prefix.rstrip('/')}/manifest.json"

    try:
        client = storage.Client()
        bucket_ref = client.bucket(bucket)
        blob = bucket_ref.blob(manifest_path)
        blob.upload_from_string(json.dumps(version_data, indent=2), content_type="application/json")
        print(f"[manifest] Saved manifest: gs://{bucket}/{manifest_path}")
        return manifest_path
    except Exception as e:
        print(f"[manifest] ERROR: Failed to save manifest: {e}")
        raise


def gcs_upload_npz(
    bucket: str,
    prefix: str,
    local_npz: Path,
    chunks_path: Path = None,
    model_name: str = "all-MiniLM-L6-v2",
    chunk_count: int = 0,
):
    """Upload embeddings (and optional chunks JSON) to GCS, and update manifest"""
    from google.cloud import storage

    client = storage.Client()
    bucket_ref = client.bucket(bucket)

    # Upload embeddings
    blob_path = f"{prefix.rstrip('/')}/embeddings.npz"
    blob = bucket_ref.blob(blob_path)
    blob.upload_from_filename(str(local_npz))
    print(f"Uploaded {local_npz} → gs://{bucket}/{blob_path}")

    # Upload chunks if provided
    if chunks_path and chunks_path.exists():
        chunks_blob = bucket_ref.blob(f"{prefix.rstrip('/')}/all_chunks.json")
        chunks_blob.upload_from_filename(str(chunks_path))
        print(f"Uploaded {chunks_path} → gs://{bucket}/{prefix}/all_chunks.json")

    # Save version-specific manifest
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        version_id = prefix.split("/")[-1] if "/" in prefix else prefix

        manifest_data = {
            "version": version_id,
            "prefix": prefix,
            "timestamp": timestamp,
            "model": model_name,
            "chunk_count": chunk_count,
            "embeddings_path": blob_path,
            "chunks_path": f"{prefix.rstrip('/')}/all_chunks.json" if chunks_path else None,
        }

        gcs_save_version_manifest(bucket, prefix, manifest_data)
    except Exception as e:
        print(f"[manifest] WARNING: Failed to save manifest: {e}")
        import traceback

        traceback.print_exc()


def gcs_download_npz(bucket: str, prefix: str, dest_npz: Path, dest_chunks: Path = None) -> Path:
    """Try to download embeddings + chunks from GCS. Return True if found, False otherwise."""
    from google.cloud import storage

    client = storage.Client()
    bucket_ref = client.bucket(bucket)

    # Check embeddings
    blob_path = f"{prefix.rstrip('/')}/embeddings.npz"
    blob = bucket_ref.blob(blob_path)
    if not blob.exists():
        print("[download] embeddings.npz not found in GCS")
        return False

    dest_npz.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(dest_npz))
    print(f"Downloaded gs://{bucket}/{blob_path} → {dest_npz}")

    # Download chunks if path provided
    if dest_chunks is not None:
        chunks_blob = bucket_ref.blob(f"{prefix.rstrip('/')}/all_chunks.json")
        if chunks_blob.exists():
            dest_chunks.parent.mkdir(parents=True, exist_ok=True)
            chunks_blob.download_to_filename(str(dest_chunks))
            print(f"Downloaded gs://{bucket}/{prefix}/all_chunks.json → {dest_chunks}")
        else:
            print("[download] all_chunks.json not found in GCS")
            return False

    return True


def create_chromadb(
    chunks: List[Dict[str, Any]],
    embeddings_arr: np.ndarray,
    ids: List[str],
    db_path: Path,
):
    """Create ChromaDB collection, aligning documents/metadatas to provided ids order."""
    try:
        import chromadb
    except ImportError:
        print("Error: chromadb not installed.")
        return None

    if len(ids) != embeddings_arr.shape[0]:
        raise ValueError(f"IDs count ({len(ids)}) != embeddings rows ({embeddings_arr.shape[0]})")

    print(f"\nCreating ChromaDB at {db_path}...")
    client = get_client(str(db_path))

    # Delete existing collection if it exists
    try:
        client.delete_collection("manim_knowledge")
        print("Deleted existing collection")
    except Exception:
        pass

    collection = client.create_collection(
        name="manim_knowledge",
        metadata={"description": "Manim documentation and code examples", "hnsw:space": "cosine"},
    )
    print("Created collection: manim_knowledge")

    # Align docs/metas to ids order
    by_id: Dict[str, Dict[str, Any]] = {c["chunk_id"]: c for c in chunks}
    documents: List[str] = []
    metadatas: List[Dict[str, str]] = []
    for cid in ids:
        ch = by_id.get(cid)
        if ch is None:
            raise KeyError(f"Chunk id {cid} not found in chunks JSON")
        documents.append(ch["content"])
        metadatas.append({k: str(v) for k, v in ch.items() if k not in ["content", "chunk_id"]})

    # Add in batches
    batch_size = 1000
    total = len(ids)
    for i in range(0, total, batch_size):
        j = min(i + batch_size, total)
        collection.add(
            ids=ids[i:j],
            embeddings=embeddings_arr[i:j].tolist(),
            documents=documents[i:j],
            metadatas=metadatas[i:j],
        )
        print(f"Progress: {j}/{total} chunks added")

    print("\nChromaDB created successfully!")
    print(f"Location: {db_path}")
    print("Collection: manim_knowledge")
    print(f"Total chunks: {total}")
    return collection


def main():
    parser = argparse.ArgumentParser(
        description="Create ChromaDB vector DB with optional GCS cache"
    )
    parser.add_argument("--base-dir", default="rag-data", help="Base directory for RAG data")
    parser.add_argument(
        "--chunks-file", default="processed/chunks/all_chunks.json", help="Relative chunks JSON"
    )
    parser.add_argument(
        "--mode",
        choices=["upload", "download"],
        default="upload",
        help="'upload' to generate+push embeddings, 'download' to pull cached",
    )
    parser.add_argument("--gcs-bucket", required=True, help="GCS bucket name (no gs://)")
    parser.add_argument("--gcs-prefix", default="rag-cache/v1", help="GCS prefix/folder")
    parser.add_argument(
        "--db-subdir", default="processed/chroma_db", help="Relative Chroma persistence dir"
    )
    parser.add_argument(
        "--npz-subpath", default="processed/embeddings/embeddings.npz", help="Relative NPZ path"
    )
    parser.add_argument("--model-name", default="all-MiniLM-L6-v2", help="Embedding model name")
    args = parser.parse_args()

    base = Path(args.base_dir)
    chunks_path = base / args.chunks_file
    db_path = base / args.db_subdir
    local_npz = base / args.npz_subpath

    print("Starting vector DB build.\n")

    if args.mode == "upload":
        if not chunks_path.exists():
            print(
                f"Error: Chunks file not found: {chunks_path}\n"
                f"Run preprocessing first (e.g., entrypoint 'preprocess')."
            )
            return
        # Generate + save locally + upload to GCS
        chunks = load_chunks(chunks_path)
        embeddings = generate_embeddings(chunks, model_name=args.model_name)
        if embeddings is None:
            return
        ids = [c["chunk_id"] for c in chunks]
        save_embeddings_npz(embeddings, ids, local_npz)
        gcs_upload_npz(
            args.gcs_bucket,
            args.gcs_prefix,
            local_npz,
            chunks_path,
            model_name=args.model_name,
            chunk_count=len(chunks),
        )
        emb_arr = np.asarray(embeddings, dtype=np.float32)
    else:  # mode == "download"
        # Try to download both files from GCS
        found = gcs_download_npz(args.gcs_bucket, args.gcs_prefix, local_npz, chunks_path)
        if not found:
            # Fallback: only proceed if local chunks exist; then reuse upload path to keep logic DRY
            if not chunks_path.exists():
                print("[download] Cache missing and no local chunks found.")
                print(f"Please run preprocessing first to create: {chunks_path}")
                return
            print("[download] Cache missing → switching to upload path to regenerate + upload")
            args.mode = "upload"
            return main()  # re-enter as upload

        # We have local files now
        emb_arr, ids = load_embeddings_npz(local_npz)
        # Ensure chunks exist locally (download would have created them if present in GCS)
        if not chunks_path.exists():
            print(f"Error: Expected chunks at {chunks_path} after download.")
            return
        chunks = load_chunks(chunks_path)

    # Build Chroma using the authoritative ids+embeddings order
    db_exists = (db_path / "chroma.sqlite3").exists()
    if db_exists and args.mode == "download":
        print(f"\n[info] Found existing ChromaDB at {db_path}, skipping rebuild (no new data).")
        return

    create_chromadb(chunks, emb_arr, ids, db_path)
    print("\nVector database ready.")


if __name__ == "__main__":
    main()
