# GitDiscord — Production Dockerfile
# Builds a minimal Python 3.12 image that runs both the Discord bot
# and the FastAPI webhook receiver as a single process via main.py

FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Install dependencies before copying source to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source code
COPY src/ ./src/

# The webhook server listens on this port; Railway injects PORT automatically
EXPOSE 8080

# Use a non-root user for security
RUN useradd --create-home appuser
USER appuser

# Start both the Discord bot and webhook server
CMD ["python", "src/main.py"]
