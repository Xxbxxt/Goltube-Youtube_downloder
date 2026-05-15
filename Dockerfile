# ===== Gol tube — Dockerfile =====
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies: ffmpeg + build tools for yt-dlp
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        && \
    rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy application
COPY . .

# Create downloads directory
RUN mkdir -p /downloads

# Volume for downloads (mount with -v /host/path:/downloads)
VOLUME ["/downloads"]

EXPOSE 5001

ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5001

CMD ["python", "main.py"]
