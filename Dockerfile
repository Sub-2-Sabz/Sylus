FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose HTTP port (default 8080 or PORT env)
EXPOSE 8080

# Environment defaults
ENV HTTP_HOST=0.0.0.0
ENV PORT=8080
ENV HTTP_PORT=8080

# Run application single entrypoint
CMD ["python", "-m", "sylus.main"]
