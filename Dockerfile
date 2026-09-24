# Agent backend for the deployed dashboard: the live /api/investigate and /api/cases/{id}/approve
# endpoints. Browsing is served as static JSON from Vercel, so this container only has to handle the
# two endpoints that genuinely need TigerGraph, an LLM, and the embedding model.
#
# Build and push from a machine that has data/profile/profile.duckdb, which is gitignored (225 MB) and
# therefore never present in a git-based build:
#   docker build --platform linux/amd64 -t ghcr.io/<user>/fraud-agent:latest .
#   docker push ghcr.io/<user>/fraud-agent:latest
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf \
    TOKENIZERS_PARALLELISM=false

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch first, pinned to PyTorch's CPU index. sentence-transformers would otherwise pull the
# CUDA build: ~590 MB of GPU runtime that cannot be used on any of these hosts.
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.2,<3"

COPY pyproject.toml ./
# Install the declared dependencies without the package itself (no source copied yet, so a build of the
# project would fail here). torch is already satisfied above and is not re-resolved.
RUN pip install \
      "duckdb>=1.5,<2" "pandas>=3.0,<4" "pyarrow>=25,<26" "scikit-learn>=1.9,<2" \
      "joblib>=1.6,<2" "numpy>=2.4,<3" "requests>=2.34,<3" "python-dotenv>=1.2,<2" \
      "pyTigerGraph>=2.0.4,<3" "openai>=3.16,<4" "langgraph>=1.2,<2" "langchain-core>=1.6,<2" \
      "langchain-google-genai>=4.4,<5" "langchain-openai>=1.6,<2" \
      "sentence-transformers>=3,<4" "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1"

# Bake the embedding model into the image. Downloading it on first request costs a judge 20-30 s of
# dead air on top of the Savanna wake, and a rate-limited Hugging Face can fail the request outright.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Runtime data. profile.duckdb backs the propensity scorer and the episode reconstruction; the policy
# chunks back GraphRAG retrieval. Both are read-only at runtime.
COPY data/profile/profile.duckdb ./data/profile/profile.duckdb
COPY data/models ./data/models
COPY data/policy ./data/policy
COPY cases ./cases

COPY api ./api
COPY agent ./agent
COPY detectors ./detectors
COPY graphrag ./graphrag
COPY tigergraph ./tigergraph
COPY scripts ./scripts

# Secrets arrive as environment variables (TG_HOST, TG_SECRET, TG_GRAPH, GEMINI_API_KEY,
# NVIDIA_API_KEY). No .env is copied into the image.
ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
