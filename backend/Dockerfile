# backend/Dockerfile
# Backend - production image (Python 3.12 + uv)
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/home/app/.venv
ENV PATH="/home/app/.venv/bin:${PATH}"

RUN set -ex; \
    apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      ffmpeg \
      sox \
      libsox-fmt-all \
      pkg-config \
      libcairo2-dev \
      libpango1.0-dev \
      libgl1-mesa-dev \
      libglib2.0-0 \
      texlive-latex-base \
      texlive-latex-recommended \
      texlive-latex-extra \
      texlive-fonts-recommended \
      texlive-fonts-extra \
      texlive-science \
      dvisvgm \
      ghostscript \
    && apt-get clean && rm -rf /var/lib/apt/lists/* && \
    python -m pip install --no-cache-dir --upgrade pip uv

RUN useradd -ms /bin/bash app -d /home/app -u 1000
USER app
WORKDIR /app

# Copy metadata and lock for reproducible installs
COPY --chown=app:app backend/pyproject.toml ./pyproject.toml
COPY --chown=app:app backend/uv.lock ./uv.lock
RUN uv sync --no-dev

# Copy app code + entrypoint
COPY --chown=app:app backend/ ./backend/
COPY --chown=app:app backend/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/bin/bash", "/app/docker-entrypoint.sh"]
