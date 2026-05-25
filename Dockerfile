# GitDiscord — Production Dockerfile
# Builds a minimal Python 3.12 image that runs both the Discord bot
# and the FastAPI webhook receiver as a single process via main.py

FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies as root so they land in the system site-packages.
# Copying requirements.txt first lets Docker cache this layer until deps change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create a non-root user for runtime security, and a writable data directory
# for the SQLite database that the bot creates at startup.
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app/data

# Copy source code and set ownership so appuser can read it
COPY --chown=appuser:appuser src/ ./src/

# The webhook server listens on this port; Railway injects PORT automatically
EXPOSE 8080

# Switch to non-root user for runtime
USER appuser

# Run as a module so Python resolves 'from src.x import ...' imports correctly
CMD ["python", "-m", "src.main"]
