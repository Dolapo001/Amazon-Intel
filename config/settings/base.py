"""
Base settings shared across all environments.
"""
import environ
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# ── Applications ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "apps.products",
    "apps.analytics",
    "apps.ingestion",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# ── Database ──────────────────────────────────────────────────────────────────
DATABASES = {
    "default": env.db("DATABASE_URL", default="postgresql://postgres:postgres@localhost:5432/amazon_intel"),
}

# ClickHouse for time-series BSR data
CLICKHOUSE = {
    "host": env("CLICKHOUSE_HOST", default="localhost"),
    "port": env.int("CLICKHOUSE_PORT", default=9000),
    "database": env("CLICKHOUSE_DB", default="amazon_intel"),
    "user": env("CLICKHOUSE_USER", default="default"),
    "password": env("CLICKHOUSE_PASSWORD", default=""),
}

# ── Cache (Redis) ─────────────────────────────────────────────────────────────
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "CONNECTION_POOL_KWARGS": {"max_connections": 100},
        },
    }
}

# ── Cache TTLs — PRD §10 ──────────────────────────────────────────────────────
# Keyed by ASIN tier; values match "Popular / Mid / Long tail" labels in §10.
CACHE_TTL = {
    "tier_1": 24 * 3600,       # popular (top 50k)  → 24h
    "tier_2": 3 * 24 * 3600,   # mid traffic        → 3d
    "tier_3": 7 * 24 * 3600,   # long tail          → 7d
    "default": 24 * 3600,
}

# ── Celery ────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_BEAT_SCHEDULE = {
    # ── BSR ingestion tiers — PRD §11 ──────────────────────────────────────
    # These drive how often Keepa data is refreshed per ASIN tier.
    "bsr-ingest-tier1": {
        "task": "apps.ingestion.tasks.refresh_tier_asins",
        "schedule": 6 * 3600,           # top 50k  → every 6 hours
        "kwargs": {"tier": 1},
    },
    "bsr-ingest-tier2": {
        "task": "apps.ingestion.tasks.refresh_tier_asins",
        "schedule": 24 * 3600,          # next 500k → every 24 hours
        "kwargs": {"tier": 2},
    },
    "bsr-ingest-tier3": {
        "task": "apps.ingestion.tasks.refresh_tier_asins",
        "schedule": 7 * 24 * 3600,     # long tail  → weekly
        "kwargs": {"tier": 3},
    },

    # ── Review scrape cadence — PRD §4.2 ───────────────────────────────────
    # Separate from BSR ingestion — governs Playwright review scraping.
    "scrape-reviews-top": {
        "task": "apps.ingestion.tasks.scrape_tier_reviews",
        "schedule": 12 * 3600,          # top ASINs   → every 12 hours
        "kwargs": {"tier": 1},
    },
    "scrape-reviews-mid": {
        "task": "apps.ingestion.tasks.scrape_tier_reviews",
        "schedule": 3 * 24 * 3600,     # mid traffic  → every 3 days
        "kwargs": {"tier": 2},
    },
    "scrape-reviews-longtail": {
        "task": "apps.ingestion.tasks.scrape_tier_reviews",
        "schedule": 7 * 24 * 3600,     # long tail    → every 7 days
        "kwargs": {"tier": 3},
    },

    # ── Model retraining — PRD §8 ───────────────────────────────────────────
    "retrain-revenue-model": {
        "task": "apps.analytics.tasks.retrain_revenue_model",
        "schedule": 24 * 3600,
    },

    # ── New Systems: Discovery, Competitors, Opportunity ───────────────────
    "run-discovery-engine": {
        "task": "apps.analytics.tasks.run_discovery_engine",
        "schedule": 24 * 3600,          # Daily discovery
    },
    "run-competitor-analysis": {
        "task": "apps.analytics.tasks.run_competitor_analysis",
        "schedule": 7 * 24 * 3600,     # Weekly clustering
    },
    "run-opportunity-scoring": {
        "task": "apps.analytics.tasks.run_opportunity_scoring",
        "schedule": 7 * 24 * 3600,     # Weekly scoring
    },
}

# ── DRF ───────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "1000/hour",
        "user": "10000/hour",
    },
}

# ── Third-party API Keys ───────────────────────────────────────────────────────
APIFY_API_KEY = env("APIFY_API_KEY", default="")

# ── NLP / ML Model Config ────────────────────────────────────────────────────
NLP_SENTIMENT_MODEL = env("NLP_SENTIMENT_MODEL", default="cardiffnlp/twitter-roberta-base-sentiment-latest")
NLP_BATCH_SIZE = env.int("NLP_BATCH_SIZE", default=64)
MODEL_STORAGE_PATH = BASE_DIR / "ml_models"

STATIC_URL = "/static/"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
