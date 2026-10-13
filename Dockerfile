# ==============================================================================
# DubFlow Studio - Universal Dockerfile for Cloud VMs & Production Servers
# ==============================================================================

FROM python:3.11-slim-bookworm

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    HOST=0.0.0.0 \
    PORT=8000

# Install system dependencies (FFmpeg, libsndfile for audio processing, curl, Node.js 22 LTS for yt-dlp challenges)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    ca-certificates \
    build-essential \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Upgrade pip & build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install PyTorch CPU wheels first (keeps Docker image lightweight and fast on CPU VMs)
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure storage directories exist
RUN mkdir -p /app/workspace_api/uploads /app/workspace_api/jobs

# Expose API and Admin Panel port
EXPOSE 8000

# Container healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-3333}/api/health || curl -f http://localhost:8000/api/health || exit 1

# Start DubFlow Studio via Uvicorn / api.py
CMD ["python", "api.py"]
