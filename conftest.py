"""
Pytest configuration for the Amazon-Intel test suite.

Uses a minimal in-memory SQLite database so tests run without a live
Postgres / Redis / ClickHouse stack.
"""
import django
import pytest


def pytest_configure(config):
    """Inject test settings before Django setup."""
    import django.conf as conf

    if not conf.settings.configured:
        conf.settings.configure(
            SECRET_KEY="test-secret-key-not-for-production",
            DEBUG=True,
            ALLOWED_HOSTS=["*"],
            INSTALLED_APPS=[
                "django.contrib.contenttypes",
                "django.contrib.auth",
                "rest_framework",
                "corsheaders",
                "apps.products",
                "apps.analytics",
                "apps.ingestion",
            ],
            MIDDLEWARE=[
                "django.middleware.common.CommonMiddleware",
            ],
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            CACHES={
                "default": {
                    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                }
            },
            ROOT_URLCONF="config.urls",
            REST_FRAMEWORK={
                "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
                "DEFAULT_AUTHENTICATION_CLASSES": [],
                "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
                "DEFAULT_THROTTLE_CLASSES": [],
            },
            CELERY_TASK_ALWAYS_EAGER=True,
            APIFY_API_KEY="",
            RAINFOREST_API_KEY="",
            NLP_SENTIMENT_MODEL="",
            NLP_BATCH_SIZE=8,
            MODEL_STORAGE_PATH="/tmp",
            USE_TZ=True,
            TIME_ZONE="UTC",
            LANGUAGE_CODE="en-us",
            DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
            STATIC_URL="/static/",
            CACHE_TTL={
                "tier_1": 24 * 3600,
                "tier_2": 3 * 24 * 3600,
                "tier_3": 7 * 24 * 3600,
                "default": 24 * 3600,
            },
            # Stub ClickHouse — tests never touch it
            CLICKHOUSE={
                "host": "localhost",
                "port": 9000,
                "database": "amazon_intel",
                "user": "default",
                "password": "",
            },
        )
