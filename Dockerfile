# ============ PRODUCTION DOCKERFILE FOR SIDEJOB ============
FROM python:3.11-slim

WORKDIR /app

# Install system deps (none needed for SQLite)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install production server with WebSocket support
RUN pip install --no-cache-dir gunicorn==21.2.0 eventlet==0.36.1

# Copy application code
COPY . .

# Create required directories
RUN mkdir -p /app/static/uploads /app/instance

# Expose the port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/')" || exit 1

# Run with Gunicorn + Eventlet for WebSocket support
CMD ["gunicorn", "--worker-class", "eventlet", "--workers", "1", "--bind", "0.0.0.0:5000", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
