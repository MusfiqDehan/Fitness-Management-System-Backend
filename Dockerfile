FROM python:3.14.4-slim

# Prevent .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Tell uv to install into the system Python (no extra venv needed inside the image)
ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

# System deps required for psycopg2 (PostgreSQL adapter)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package installer)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Install Python dependencies first (Docker layer cache)
COPY requirements.txt .
RUN uv pip install -r requirements.txt

# Copy project source
COPY . .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8021

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8021", "--workers", "3", "--timeout", "120"]
