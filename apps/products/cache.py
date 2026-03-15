"""
Two-layer caching.

L1 — Redis  (fast, TTL-based, tier-aware)
L2 — DB     (persistent, always available as fallback)

get_cached_intel → checks Redis
set_cached_intel → writes to Redis with correct TTL for the ASIN tier
"""
import json
import logging
from typing import Optional

from django.core.cache import cache
from django.conf import settings

from apps.products.models import ASIN

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "asin_intel"

# TTL map per ASIN tier — PRD §10
# Tier 1 (popular / top 50k)  → 24 hours
# Tier 2 (mid traffic)        → 3 days
# Tier 3 (long tail)          → 7 days
_TTL: dict[int, int] = {
    ASIN.TIER_1: 24 * 3600,        # popular  → 24h
    ASIN.TIER_2: 3 * 24 * 3600,   # mid      → 3d
    ASIN.TIER_3: 7 * 24 * 3600,   # long tail → 7d
}
_DEFAULT_TTL = 24 * 3600


def _key(asin: str) -> str:
    return f"{_CACHE_PREFIX}:{asin}"


def get_cached_intel(asin: str) -> Optional[dict]:
    """Return cached intelligence payload or None if missing/expired."""
    try:
        raw = cache.get(_key(asin))
        if raw is None:
            return None
        return json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except Exception as exc:
        logger.warning("cache_get_error", extra={"asin": asin, "error": str(exc)})
        return None


def set_cached_intel(asin: str, payload: dict, tier: int = ASIN.TIER_3) -> None:
    """Store intelligence payload in Redis with tier-appropriate TTL."""
    ttl = _TTL.get(tier, _DEFAULT_TTL)
    try:
        cache.set(_key(asin), json.dumps(payload, default=str), timeout=ttl)
    except Exception as exc:
        logger.warning("cache_set_error", extra={"asin": asin, "error": str(exc)})


def invalidate_intel(asin: str) -> None:
    """Evict a specific ASIN from cache (called after a successful refresh)."""
    try:
        cache.delete(_key(asin))
    except Exception as exc:
        logger.warning("cache_invalidate_error", extra={"asin": asin, "error": str(exc)})
