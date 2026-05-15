# ===== Gol tube — Dockerfile =====
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps + ffmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy only dependency metadata first (better layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy application source (excludes .gitignore'd files via .dockerignore)
COPY main.py .
COPY static/ ./static/
COPY Templates/ ./Templates/

# Create downloads directory
RUN mkdir -p /downloads

# Volume for downloads
VOLUME ["/downloads"]

EXPOSE 5001

ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5001

CMD ["python", "main.py"]
