FROM python:3.11-slim

WORKDIR /app

# ── System dependencies ────────────────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir --default-timeout=600 -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY . .

# ── Environment ───────────────────────────────────────────────────────────────
ENV DJANGO_SETTINGS_MODULE=config.settings.production
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Collect static files (non-fatal so build doesn't fail if DB isn't ready)
RUN python manage.py collectstatic --noinput || true

EXPOSE 5000
