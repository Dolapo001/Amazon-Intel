"""
Apify client — replaces both Keepa (product/BSR data) and Playwright (reviews).

No proxies. No browser binaries. No rotating user-agents.
Apify handles all of that internally.

Two actors are used:
  1. junglee/amazon-product-scraper  → BSR, price, rating, title, brand, category
  2. junglee/amazon-reviews-scraper  → review text, rating, date, verified flag

Both are called via Apify's synchronous run endpoint, which blocks until the
actor finishes and returns the dataset directly — no polling needed.

Public interface:
  fetch_product(asin)            → dict  (same shape the old KeepaClient returned)
  fetch_products_batch(asins)    → list[dict]
  fetch_reviews(asin, max_count) → list[dict]
"""
import logging
import re
from typing import Optional

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

_APIFY_BASE = "https://api.apify.com/v2"

# Actor IDs — stable Apify marketplace slugs
_ACTOR_PRODUCTS = "junglee~amazon-crawler"
_ACTOR_REVIEWS  = "junglee~amazon-reviews-scraper"

# Generous timeout: actors can take 30–90s for a batch
_TIMEOUT = httpx.Timeout(120.0, connect=20.0)

# Global client for connection pooling
_CLIENT = httpx.Client(timeout=_TIMEOUT)


def _retry_request(method, url, **kwargs):
    """Simple retry for transient network/DNS errors."""
    import time
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = _CLIENT.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Apify request failed (attempt {attempt+1}/{max_retries}): {exc}")
            time.sleep(1 * (attempt + 1))
    return None


# ── Product data ──────────────────────────────────────────────────────────────

def fetch_product(asin: str, country: str = "US") -> tuple[Optional[dict], list[dict]]:
    """
    Fetch current product snapshot and embedded reviews for a single ASIN via Apify.

    Returns a dict with the keys the rest of the pipeline expects:
      asin, title, brand, category_id, category_name, image_url,
      current_bsr, current_price, current_rating, current_review_count,
      bsr_series  ← always [] — Apify gives current data only, not history.
                    History is built up over repeated ingestion runs.
    """
    api_key = _get_api_key()
    if not api_key:
        return None, []

    url = f"{_APIFY_BASE}/acts/{_ACTOR_PRODUCTS}/run-sync-get-dataset-items"
    payload = {
        "categoryOrProductUrls": [{"url": f"https://www.amazon.com/dp/{asin}"}],
    }

    try:
        resp = _retry_request("POST", url, json=payload, params={"token": api_key}, timeout=_TIMEOUT)
        if not resp:
            return None
        items = resp.json()

        if not items:
            logger.warning("apify_no_product", extra={"asin": asin})
            return None, []

        item = items[0]
        product = _parse_product(item, asin)
        
        # Extract reviews already present in the product detail (efficient!)
        raw_reviews = item.get("productPageReviews", []) or item.get("productPageReviewsFromOtherCountries", [])
        reviews = [_parse_review(r) for r in raw_reviews]
        
        return product, reviews

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 402:
            logger.error("apify_credits_exhausted")
        else:
            logger.error("apify_http_error", extra={"status": exc.response.status_code, "asin": asin})
    except Exception as exc:
        logger.exception("apify_product_error", extra={"asin": asin, "error": str(exc)})
    
    return None, []


def fetch_products_batch(asins: list[str], country: str = "US") -> list[dict]:
    """
    Fetch up to 50 ASINs in one Apify run.
    More cost-efficient than individual calls since Apify charges per
    compute unit, not per ASIN.
    """
    if not asins:
        return []

    api_key = _get_api_key()
    if not api_key:
        return []

    results = []
    for chunk in _chunks(asins, 50):
        url = f"{_APIFY_BASE}/acts/{_ACTOR_PRODUCTS}/run-sync-get-dataset-items"
        payload = {"asins": chunk, "country": country, "maxReviews": 0, "scrapeProductDetails": True}
        try:
            resp = httpx.post(url, json=payload, params={"token": api_key}, timeout=_TIMEOUT)
            resp.raise_for_status()
            for item in resp.json():
                parsed = _parse_product(item, item.get("asin", ""))
                if parsed:
                    results.append(parsed)
        except Exception as exc:
            logger.exception("apify_batch_error", extra={"error": str(exc)})

    return results


# ── Reviews ───────────────────────────────────────────────────────────────────

def fetch_reviews(asin: str, max_count: int = 100, country: str = "US", fast_mode: bool = False) -> list[dict]:
    """
    Fetch reviews for a single ASIN via Apify.
    Uses a multi-probe approach (Recent + Helpful) to maximize review yield.
    fast_mode=True only does one probe for speed.
    """
    api_key = _get_api_key()
    if not api_key:
        return []

    url = f"{_APIFY_BASE}/acts/{_ACTOR_REVIEWS}/run-sync-get-dataset-items"
    
    unique_reviews = {}  # {text_hash: review_dict}
    
    # In fast mode, we only probe once to stay under the latency budget
    # Apify accepts "recent" and "helpful" (not "helpfulness")
    probes = ["recent"] if fast_mode else ["recent", "helpful"]
    timeout = 30.0 if fast_mode else _TIMEOUT

    for sort_by in probes:
        payload = {
            "productUrls": [{"url": f"https://www.amazon.com/dp/{asin}"}],
            "maxReviews": max_count,
            "proxyCountry": "AUTO_SELECT_PROXY_COUNTRY",
            "sortBy": sort_by,
        }
        try:
            resp = _retry_request("POST", url, json=payload, params={"token": api_key}, timeout=_TIMEOUT)
            if not resp:
                continue
            for r in resp.json():
                parsed = _parse_review(r)
                # Deduplicate by text content so we don't double-count across probes
                key = hash(parsed["text"][:200])
                if key not in unique_reviews:
                    unique_reviews[key] = parsed
        except Exception as exc:
            logger.warning(f"apify_reviews_probe_failed (asin={asin}, sort={sort_by}): {exc}")
            if fast_mode: break

    reviews = list(unique_reviews.values())
    logger.info("apify_reviews_fetched", extra={"asin": asin, "total_unique": len(reviews)})
    return reviews


def concurrent_fetch(asin: str, fast_mode: bool = True) -> tuple[Optional[dict], list[dict]]:
    """
    Fetch product and reviews efficiently. 
    Now uses the 'amazon-crawler' to get both in one shot.
    """
    product, reviews = fetch_product(asin)
    
    # If the combined scraper didn't get enough reviews, try the dedicated one (if not in fast mode)
    if not fast_mode and len(reviews) < 5:
        more_reviews = fetch_reviews(asin, max_count=50)
        if more_reviews:
            reviews.extend([r for r in more_reviews if r not in reviews])
            
    return product, reviews


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_product(item: dict, asin: str) -> Optional[dict]:
    """
    Normalise a junglee/amazon-product-scraper result into the internal shape.

    Apify fields used:
      asin, title, brand, categoryName, salesRank, price,
      stars, reviewsCount, thumbnailImage, breadCrumbs
    """
    if not item:
        return None

    bsr = item.get("salesRank") or item.get("bestSellersRank") or item.get("rank") or item.get("bsrank") or item.get("bestsellerRanks")
    if isinstance(bsr, dict):
        bsr = bsr.get("rank") or bsr.get("position") or bsr.get("value")
    elif isinstance(bsr, list) and bsr:
        # bestsellerRanks is often a list of objects like {"category": "Home", "rank": 123}
        first = bsr[0]
        if isinstance(first, dict):
            bsr = first.get("rank") or first.get("position") or first.get("value")
        else:
            bsr = first

    price = item.get("price")
    
    if isinstance(price, str):
        price = _parse_price_str(price)
    elif isinstance(price, dict):
        price = price.get("value") or price.get("price") or price.get("current_price")

    crumbs = item.get("breadCrumbs", [])
    if isinstance(crumbs, str):
        # Handle string like "Home > Kitchen > ..."
        crumbs = [c.strip() for c in crumbs.split(">") if c.strip()]
    
    category_name = None
    # Skip single-character crumbs (like "H" for Home) if better ones exist
    for c in crumbs:
        if len(c.strip()) > 1:
            category_name = c
            break
    if not category_name:
        category_name = crumbs[0] if crumbs else (item.get("category") or item.get("categoryName") or "")
    
    # Use the first segment as the primary category ID
    primary_category = crumbs[0] if crumbs else (category_name or "unknown")
    category_id = primary_category.lower().replace("&", "and").replace(" ", "_").replace(",", "").strip()

    return {
        "asin":                 item.get("asin", asin),
        "title":                item.get("title", ""),
        "brand":                item.get("brand", ""),
        "category_id":          category_id,
        "category_name":        category_name,
        "image_url":            item.get("thumbnailImage", ""),
        "current_bsr":          int(bsr) if bsr else None,
        "current_price":        float(price) if price else None,
        "current_rating":       float(item.get("stars", 0)) or None,
        "current_review_count": int(item.get("reviewsCount", 0)) or None,
        "bsr_series":           [],   # no history from Apify; built up over time internally
    }


def _parse_review(item: dict) -> dict:
    """
    Normalise a junglee/amazon-reviews-scraper result.
    """
    try:
        # Check ratingScore or rating
        rating_val = item.get("ratingScore") or item.get("rating", 3)
        rating = int(float(str(rating_val).split()[0]))
    except Exception:
        rating = 3

    # Try multiple text fields: reviewDescription is common in Junglee scraper
    text = item.get("reviewDescription") or item.get("text") or item.get("reviewText") or item.get("description", "")

    return {
        "text":     text,
        "rating":   rating,
        "date":     item.get("reviewDate") or item.get("date"),
        "verified": bool(item.get("isVerified") or item.get("verifiedPurchase", False)),
    }


def _parse_price_str(price_str: str) -> Optional[float]:
    match = re.search(r"[\d]+\.?\d*", price_str.replace(",", ""))
    return float(match.group()) if match else None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_api_key() -> Optional[str]:
    key = getattr(settings, "APIFY_API_KEY", "")
    if not key:
        logger.error("APIFY_API_KEY not configured — set APIFY_API_KEY in .env")
    return key or None


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[int(i) : int(i + n)]
