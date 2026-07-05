# ── RMD-TRA Dockerfile ──
# Single-stage build dengan uv untuk dependency management
# Target: Google Cloud Run (linux/amd64)

FROM python:3.11-slim

# Metadata
LABEL maintainer="Rudy Max"
LABEL description="RMD-TRA: Transportation Research Assistant"
LABEL version="1.0.0"

# Variabel environment dasar
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency manifest lebih dahulu (untuk layer cache)
COPY pyproject.toml ./

# Install dependencies menggunakan uv (lebih cepat dari pip)
RUN uv sync --no-dev --no-install-project

# Copy source code
COPY app/ ./app/
COPY static/ ./static/

# Expose port Cloud Run
EXPOSE 8080

# Jalankan FastAPI dengan uvicorn
CMD ["uv", "run", "uvicorn", "app.fast_api_app:app", \
     "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "1", "--log-level", "info"]
