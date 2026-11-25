FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CARVEOUT_CHECKPOINT_DB=/app/.carveout/checkpoints.sqlite \
    CARVEOUT_API_HOST=0.0.0.0 \
    CARVEOUT_API_PORT=8000

WORKDIR /app

# Create non-root runtime user
RUN groupadd --system carveout && useradd --system --gid carveout --create-home carveout

# Install project and optional extras (agents, optimization, api)
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY data/ ./data/
COPY config/ ./config/

RUN pip install --no-cache-dir -e ".[agents,optimization,api]" \
    && mkdir -p /app/.carveout /app/output \
    && chown -R carveout:carveout /app

USER carveout

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["uvicorn", "carveout.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
