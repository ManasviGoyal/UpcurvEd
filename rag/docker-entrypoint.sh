#!/usr/bin/env bash
set -euo pipefail

# Activate venv (uv put it in /.venv)
if [ -f "/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "/.venv/bin/activate"
fi

CMD="${1:-all}"
shift || true

# Default dirs and environment
BASE_DIR="${BASE_DIR:-/var/lib/app/rag-data}"
GCS_BUCKET="${GCS_BUCKET:-}"
GCS_PREFIX="${GCS_PREFIX:-rag-cache/v1}"

# Fetch behavior knobs
SKIP_IF_EXISTS="${SKIP_IF_EXISTS:-1}"      # 1 = skip if repo exists
FORCE_FETCH="${FORCE_FETCH:-0}"            # 1 = always refresh to latest
MANIM_COMMUNITY_REF="${MANIM_COMMUNITY_REF:-main}"
MANIM_3B1B_REF="${MANIM_3B1B_REF:-master}"

# Ensure BASE_DIR exists and is writable
echo "[entrypoint] BASE_DIR: $BASE_DIR"

if [ ! -d "$BASE_DIR" ]; then
  echo "[entrypoint] Creating $BASE_DIR"
  install -d -m 2775 "$BASE_DIR"
fi

if [ ! -w "$BASE_DIR" ]; then
  echo "[entrypoint] WARN: $BASE_DIR not writable; falling back to /tmp/rag-data"
  BASE_DIR="$(mktemp -d /tmp/rag-data.XXXXXX)"
  export BASE_DIR
  install -d -m 2775 "$BASE_DIR"
fi

# Create predictable subdirs
install -d -m 2775 "$BASE_DIR/documentation" "$BASE_DIR/examples"

# Repo fetch logic
fetch() {
  echo "[fetch] base: $BASE_DIR"

  DOCS_DIR="$BASE_DIR/documentation/manim-docs"
  EX_COMM="$BASE_DIR/examples/manim-community"
  EX_3B1B="$BASE_DIR/examples/manim-3b1b"

  _ensure_repo () {
    local url="$1" dir="$2" ref="$3"


    if [ -d "$dir/.git" ]; then
      if [ "$FORCE_FETCH" = "1" ]; then
        echo "[fetch] forcing update for $dir ($ref)"
        git -C "$dir" fetch --depth 1 origin "$ref" || true
        git -C "$dir" checkout -q "$ref" || true
        git -C "$dir" pull --ff-only || true
      elif [ "$SKIP_IF_EXISTS" = "1" ]; then
        echo "[fetch] exists, skipping: $dir"
      else
        echo "[fetch] updating $dir ($ref)"
        git -C "$dir" fetch --depth 1 origin "$ref" || true
        git -C "$dir" checkout -q "$ref" || true
        git -C "$dir" pull --ff-only || true
      fi
    else
      echo "[fetch] cloning $url → $dir (ref=$ref)"
      git clone --depth 1 --branch "$ref" "$url" "$dir"
    fi
  }

  _ensure_repo "https://github.com/ManimCommunity/manim.git" "$DOCS_DIR" "$MANIM_COMMUNITY_REF"
  _ensure_repo "https://github.com/ManimCommunity/manim.git" "$EX_COMM"  "$MANIM_COMMUNITY_REF"
  _ensure_repo "https://github.com/3b1b/manim.git"           "$EX_3B1B"  "$MANIM_3B1B_REF"

  echo "[fetch] done."
}

# Command routing
case "$CMD" in
  fetch)
    fetch
    ;;
  preprocess)
    python /app/preprocess_rag_smart.py --base-dir "$BASE_DIR"
    ;;
  upload)
    if [ -z "$GCS_BUCKET" ]; then
      echo "[upload] ERROR: GCS_BUCKET is required" >&2; exit 2;
    fi
    python /app/create_vector_db.py \
      --base-dir "$BASE_DIR" \
      --mode upload \
      --gcs-bucket "$GCS_BUCKET" \
      --gcs-prefix "$GCS_PREFIX"
    ;;
  download)
    if [ -z "$GCS_BUCKET" ]; then
      echo "[download] ERROR: GCS_BUCKET is required" >&2; exit 2;
    fi
    python /app/create_vector_db.py \
      --base-dir "$BASE_DIR" \
      --mode download \
      --gcs-bucket "$GCS_BUCKET" \
      --gcs-prefix "$GCS_PREFIX"
    ;;
  all)
    "$0" fetch
    "$0" preprocess
    "$0" upload
    ;;
  bash|sh)
    exec "$CMD" "$@"
    ;;
  query)
    # Only prep DB if missing; otherwise go straight to querying
    if [ -n "$GCS_BUCKET" ] && [ ! -f "$BASE_DIR/processed/chroma_db/chroma.sqlite3" ]; then
        "$0" download || true
    fi
    python /app/query_db.py --base-dir "$BASE_DIR" "$@"
    ;;
  *)
    echo "Usage: all | fetch | preprocess | upload | download | query | bash"
    exit 2
    ;;
esac