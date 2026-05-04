"""Production settings — extends base."""
from .base import *  # noqa
import os
import environ

env = environ.Env()

# ── Hosts ─────────────────────────────────────────────────────────────────────
# Default accepts all .herokuapp.com subdomains; override via ALLOWED_HOSTS env var.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[".herokuapp.com", "localhost", "127.0.0.1"])
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

# ── SSL / HTTPS ───────────────────────────────────────────────────────────────
# Heroku terminates SSL at the router and forwards requests over HTTP internally.
# Using SECURE_PROXY_SSL_HEADER tells Django to trust the X-Forwarded-Proto header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)

# ── Celery — derive from REDIS_URL if per-service vars are absent ─────────────
# Heroku Redis add-on exports a single REDIS_URL; fall back to it automatically.
# Note: For Heroku Redis SSL (rediss://), we must skip cert verification.
_redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# If REDIS_URL uses SSL (rediss://), append the parameter to skip cert verification for Celery
_celery_url = _redis_url
if _celery_url.startswith("rediss://") and "ssl_cert_reqs" not in _celery_url:
    _celery_url += "?ssl_cert_reqs=none"

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", _celery_url)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", _celery_url)

# Update Django cache to skip SSL verification
CACHES["default"]["LOCATION"] = _redis_url
CACHES["default"]["OPTIONS"]["CONNECTION_POOL_KWARGS"] = {
    "ssl_cert_reqs": None,
    "max_connections": 100,
}

# ── Sentry — only initialise when a DSN is provided ──────────────────────────
_SENTRY_DSN = env("SENTRY_DSN", default="")
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
    )

