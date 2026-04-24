# syntax=docker/dockerfile:1.7

# ─── Stage 1: reranker-builder ───────────────────────────────────────
# Exports the RAG cross-encoder (cross-encoder/mmarco-mMiniLMv2-L12-H384-v1)
# to ONNX int8. This stage carries heavy build-only deps (torch CPU,
# optimum, sentence-transformers — together ~2 GB) which are discarded
# after the export. The final image only takes the ~135 MB artefact.
FROM python:3.12-slim AS reranker-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/hf-cache

WORKDIR /build

COPY requirements-setup.txt ./
RUN pip install -r requirements-setup.txt \
      --extra-index-url https://download.pytorch.org/whl/cpu

# Only scripts are needed for the export — not the whole app tree.
COPY scripts ./scripts

# BuildKit cache mount keeps HF hub downloads across rebuilds, so
# iterating on the Dockerfile doesn't re-download the 500 MB model.
RUN --mount=type=cache,target=/hf-cache \
    python -m scripts.export_reranker_onnx


# ─── Stage 2: runtime ────────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

# App code + config tree + pre-built widget bundle + knowledge seed
COPY app ./app
COPY chatbots ./chatbots
COPY widget_dist ./widget_dist
COPY run.py ./
COPY knowledge ./knowledge
COPY scripts ./scripts

# Pull ONLY the exported ONNX model from the builder stage. No torch,
# no sentence-transformers, no optimum end up in the runtime image.
COPY --from=reranker-builder /build/models ./models

RUN mkdir -p /data
ENV DATABASE_PATH=/data/badboerdi.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
