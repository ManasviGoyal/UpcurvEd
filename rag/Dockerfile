# rag/Dockerfile
# Use the official Debian-hosted Python image
FROM python:3.12-slim-bookworm

# Minimal system deps. libgomp1 helps with PyTorch wheels used by sentence-transformers
ARG DEBIAN_PACKAGES="build-essential curl git ca-certificates libgomp1"

# Stable non-root identity for prod
ARG APP_UID=10001
ARG APP_GID=10001
ARG APP_USER=app
ARG APP_GROUP=app
ARG APP_HOME=/home/${APP_USER}
ARG APP_DATA=/var/lib/app/rag-data

# Noninteractive apt, UTF-8, unbuffered Python
ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1

# uv config: copy wheels into venv, create venv at /.venv
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/.venv

# We'll also expose the venv on PATH
ENV PATH="/.venv/bin:${PATH}"

# System setup, deps, uv, and non-root user with stable UID/GID
RUN set -ex; \
    for i in $(seq 1 8); do mkdir -p "/usr/share/man/man${i}"; done && \
    apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends $DEBIAN_PACKAGES && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir uv && \
    addgroup --system --gid ${APP_GID} ${APP_GROUP} && \
    adduser  --system --uid ${APP_UID} --ingroup ${APP_GROUP} --home ${APP_HOME} ${APP_USER} && \
    # Create venv dir and app data path with correct ownership/permissions
    install -d -o ${APP_UID} -g ${APP_GID} /.venv && \
    # setgid (2) ensures group is preserved on new files; group-writable for team use
    install -d -m 2775 -o ${APP_UID} -g ${APP_GID} ${APP_DATA} && \
    # App workspace
    install -d -m 0775 -o ${APP_UID} -g ${APP_GID} /app
    
# Switch to non-root
# Switch to non-root
USER ${APP_UID}:${APP_GID}
WORKDIR /app

# Copy dependency files first for build cache
COPY --chown=${APP_UID}:${APP_GID} pyproject.toml uv.lock* ./

# If lock exists, enforce it; otherwise resolve & install from pyproject
RUN if [ -f uv.lock ]; then \
      uv sync --frozen; \
    else \
      uv sync; \
    fi

# Copy the rest of the source
COPY --chown=${APP_UID}:${APP_GID} . ./

# Defaults (override via compose/env at runtime)
# BASE_DIR is where preprocess writes chunks and Chroma persists
ENV BASE_DIR=${APP_DATA}

# Make sure entrypoint is executable if it isn't already
RUN chmod +x /app/docker-entrypoint.sh

# Encourage using a named volume for production (optional but helpful)
VOLUME ["/var/lib/app/rag-data"]

# Entry point routes: all | preprocess | upload | download | bash
ENTRYPOINT ["/bin/bash","/app/docker-entrypoint.sh"]
# Default to full pipeline (preprocess -> upload embeddings to GCS -> build Chroma)
CMD ["all"]
