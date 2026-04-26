# Data Versioning

The RAG pipeline uses a snapshot-based data versioning strategy on GCS with a single, per-version manifest that is overwritten on each upload. 

```
gs://{GCS_BUCKET}/{prefix}/manifest.json
```

Example: `gs://manim_embeddings/rag-cache/v1/manifest.json`

We chose snapshots (not DVC) because our artifacts are small binaries (e.g., all_chunks.json, embeddings.npz) and the corpus updates infrequently (6–12 months)—diff-based tooling adds overhead without benefit.

**Structure per version:**
```
gs://<bucket>/rag-cache/v1/
├── all_chunks.json
├── embeddings.npz
└── manifest.json
```

Each manifest contains:
- Version ID (extracted from prefix, e.g., `v1`)
- GCS prefix path
- Timestamp (updated on each upload)
- Embedding model used
- Chunk count
- File paths (embeddings, chunks)

## Uploading with Manifest

When uploading, the manifest is automatically created/updated:

```bash
python create_vector_db.py \
  --mode upload \
  --gcs-bucket your-rag-bucket \
  --gcs-prefix rag-cache/v1 \
  --model-name all-MiniLM-L6-v2
```

**Note:** The manifest is overwritten on each upload, so each version maintains only one manifest file. This prevents storage bloat while still tracking the latest upload metadata.

## GCS Object Versioning (Recommended)

Enable GCS Object Versioning to retain history when overwriting files:

```bash
gsutil versioning set on gs://your-rag-bucket
```

This allows you to:
- Keep a clean, simple structure (one file per version)
- Still access historical versions when needed via GCS versioning
- Automatically retain overwritten files without manual cleanup

## Version Bumping

When formats change (e.g., new embedding dimensions, different preprocessing), bump the version folder:

```bash
# Old version
--gcs-prefix rag-cache/v1

# New version
--gcs-prefix rag-cache/v2
```

This keeps old versions accessible while allowing format changes.

## Reproducibility

- We pin code and environment for each upload and write them into `manifest.json` along with chunking params.
- Re-running the pipeline with the same commit, model, and params recreates identical artifacts. We also store `sha256` and `size_bytes` for `all_chunks.json` and `embeddings.npz` in the manifest so outputs can be verified byte-for-byte.
- For rollbacks, GCS Object Versioning preserves prior generations of manifest.json and artifacts.

## Reference

For complete details on RAG setup and usage, see [`rag/README.md`](../rag/README.md).
