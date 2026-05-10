FROM python:3.12-slim

# Prevent .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Tell uv to install into the system Python (no extra venv needed inside the image)
ENV UV_SYSTEM_PYTHON=1

ARG APP_UID=1000
ARG APP_GID=1000

WORKDIR /app

# Install system deps, uv (via install script), and Python dependencies
COPY requirements.txt .
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq-dev gcc curl build-essential \
 && curl -LsSf https://astral.sh/uv/install.sh | sh \
 && export PATH="/root/.local/bin:$PATH" \
 && uv pip install --system --no-cache -r requirements.txt \
 && groupadd --gid ${APP_GID} app \
 && useradd --uid ${APP_UID} --gid ${APP_GID} --create-home --shell /usr/sbin/nologin app \
 && apt-get purge -y build-essential \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Copy project source
COPY . .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8021

ENTRYPOINT ["/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8021", "config.asgi:application"]
