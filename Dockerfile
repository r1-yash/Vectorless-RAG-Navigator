# Multi-stage Dockerfile using uv for fast, reproducible environment builds
FROM python:3.11-slim

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency definition files
COPY pyproject.toml README.md ./

# Copy application source and pre-built sample dataset
COPY src/ ./src/
COPY data/ ./data/

# Install dependencies using uv sync
RUN uv sync --frozen || uv sync

EXPOSE 8000

# Run FastAPI backend with Uvicorn
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
