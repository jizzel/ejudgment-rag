# One image for the API, the migrations and the worker (CPU-only; local models from the
# mounted Hugging Face cache, generation via Ollama on the host).
# Build from the repository root: docker build -f docker/python.Dockerfile .

ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN pip install "poetry==2.5.1" "poetry-plugin-export==1.10.1"
COPY pyproject.toml poetry.lock ./
COPY scripts/install-python-deps.sh ./scripts/
# Main dependencies only, pinned by the lock file, with CPU-only torch (the same script as CI).
RUN bash scripts/install-python-deps.sh /opt/venv

FROM python:${PYTHON_VERSION}-slim AS runtime
# OCR tools for worker.extract; curl for the health check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 ejudgment
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
# The repository layout is kept (/app/src, /app/config, /app/migrations): config.py finds
# config/models.yaml relative to the source tree, so the package is not pip-installed.
COPY alembic.ini ./
COPY migrations ./migrations
COPY config ./config
# The gold and smoke question sets: worker.evaluate / evaluate_answers default to evals/gold.jsonl.
COPY evals ./evals
COPY src ./src
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/models/huggingface \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    MODEL_DEVICE=cpu
USER ejudgment
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1
CMD ["uvicorn", "ejudgment.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
